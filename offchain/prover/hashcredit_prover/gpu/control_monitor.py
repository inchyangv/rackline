"""Run GPU control/proof/data freshness monitoring; emit reviewed actions only."""

import argparse
import logging
import os
import time
from datetime import UTC, datetime

from hashcredit_gpu.db.models import Facility
from hashcredit_gpu.db.product_models import FacilityBinding
from hashcredit_gpu.db.projections_models import (
    ChainBlock,
    ChainCursor,
    ChainDeployment,
    ProjectedFacility,
)
from hashcredit_gpu.monitoring.alerts import Alerter
from hashcredit_gpu.monitoring.service import assess_facility, record_findings
from sqlalchemy import create_engine, select
from sqlalchemy.exc import DisconnectionError, OperationalError
from sqlalchemy.orm import Session


def indexer_freshness(engine, deployment_id, *, max_age_seconds=300, now=None):
    """Deployment-level watchdog on the projector cursor (independent of the indexer process itself)."""
    now = now or datetime.now(UTC)
    with Session(engine) as s:
        cursor = s.get(ChainCursor, deployment_id)
        if cursor is None:
            return {"state": "MISSING", "ageSeconds": None, "lastBlock": None}
        age = (now - cursor.updated_at).total_seconds()
        return {"state": "FRESH" if age <= max_age_seconds else "STALE", "ageSeconds": int(age), "lastBlock": cursor.last_block_number}


def watch_indexer(engine, deployment_id, alerter, *, max_age_seconds=300, now=None):
    """Alert (deduplicated) while the projector cursor is missing or stale; resolve once it moves again."""
    status = indexer_freshness(engine, deployment_id, max_age_seconds=max_age_seconds, now=now)
    if status["state"] == "FRESH":
        alerter.alert("indexer-stale", f"projector cursor fresh again (last block {status['lastBlock']})", resolved=True)
    elif status["state"] == "MISSING":
        alerter.alert("indexer-stale", f"no projector cursor for deployment {deployment_id}: the indexer has never synced", severity="critical")
    else:
        alerter.alert("indexer-stale", f"projector cursor is {status['ageSeconds']} s old (last block {status['lastBlock']}); "
                      f"the API reports EVIDENCE_STALE and new draws are paused until the indexer catches up", severity="critical")
    return status


def run_once(engine, deployment_id):
    count = 0
    with Session(engine) as s, s.begin():
        deployment = s.get(ChainDeployment, deployment_id)
        if deployment is None:
            raise ValueError("monitor deployment is not registered")
        cursor = s.get(ChainCursor, deployment_id)
        for facility, binding in s.execute(
            select(Facility, FacilityBinding).join(FacilityBinding, FacilityBinding.facility_id == Facility.facility_id).where(
                FacilityBinding.deployment_id == deployment_id,
                Facility.execution_profile == deployment.execution_profile,
                Facility.loan_chain_id == deployment.chain_id,
            )
        ):
            now = datetime.now(UTC)
            projected = s.get(ProjectedFacility, (deployment_id, "FINALIZED", binding.onchain_id))
            block = s.get(ChainBlock, (deployment_id, projected.last_block)) if projected else None
            terminal = (
                projected is not None and projected.execution_profile == deployment.execution_profile
                and projected.state in {"REPAID", "RELEASED", "CLOSED_WITH_LOSS"}
                and cursor is not None and projected.last_block <= cursor.finalized_block_number
                and block is not None and block.tier == "FINALIZED"
            )
            # Metadata is not financial state. Only this deployment's canonical terminal
            # projection ends active monitoring; no principal/control-grade writes occur.
            findings = () if terminal else assess_facility(s, facility.facility_id, now=now, deployment_id=deployment_id)
            record_findings(s, facility.facility_id, findings, now=now)
            count += len(findings)
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deployment-id", required=True)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    engine = create_engine(
        os.environ.get("HASHCREDIT_GPU_DATABASE_URL") or os.environ["GPU_DATABASE_URL"]
    )
    alerter = Alerter.from_env("gpu-monitor")
    max_age = int(os.environ.get("GPU_INDEXER_STALE_ALERT_SECONDS") or 300)
    log = logging.getLogger(__name__)
    log.info("monitor alerts %s", "webhook configured" if alerter.configured else "log-only (GPU_ALERT_WEBHOOK_URL unset)")
    try:
        while True:
            try:
                findings = run_once(engine, args.deployment_id)
                indexer = watch_indexer(engine, args.deployment_id, alerter, max_age_seconds=max_age)
                print({"monitorFindings": findings, "indexer": indexer}, flush=True)
            except (OperationalError, DisconnectionError) as exc:
                log.warning("monitor database unavailable (%s)", type(exc).__name__)
                if args.once:
                    raise
            except Exception as exc:
                alerter.alert("monitor-crash", f"control monitor stopped on {type(exc).__name__}: {exc}", severity="critical")
                raise
            if args.once:
                return
            time.sleep(30)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
