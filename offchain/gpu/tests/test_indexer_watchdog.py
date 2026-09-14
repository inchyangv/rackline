"""The control monitor watches the projector cursor independently of the indexer process."""

from datetime import UTC, datetime, timedelta

import json

import pytest

DEP = "01K54G0000QN0QHY2GCA10HGXN"
from hashcredit_gpu.db.projections_models import ChainCursor, ChainDeployment
from hashcredit_gpu.monitoring.alerts import Alerter
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

pytest.importorskip("hashcredit_prover.gpu.control_monitor")  # the worker package is installed alongside in CI/dev
from hashcredit_prover.gpu.control_monitor import indexer_freshness, watch_indexer  # noqa: E402


def test_watchdog_alerts_on_missing_or_stale_cursor_and_resolves_when_fresh(migrated_db_url):
    engine = create_engine(migrated_db_url)
    with Session(engine) as s, s.begin():
        s.add(ChainDeployment(deployment_id=DEP, chain_id=102031, execution_profile="NATIVE_TESTNET", env_id="cc3-testnet",
                              manifest_hash="sha256:" + "a" * 64, deployment_block=1, contracts={}, finality_depth=2))
    sent = []
    alerter = Alerter(service="gpu-monitor", webhook_url="https://hooks.example.test/x")
    alerter._transport = lambda url, body: sent.append(json.loads(body))
    now = datetime(2026, 9, 18, tzinfo=UTC)
    assert watch_indexer(engine, DEP, alerter, now=now)["state"] == "MISSING"
    with Session(engine) as s, s.begin():
        s.add(ChainCursor(deployment_id=DEP, last_block_number=5504401, last_block_hash="0x" + "ab" * 32,
                          finalized_block_number=5504395, updated_at=now - timedelta(minutes=20)))
    stale = watch_indexer(engine, DEP, alerter, max_age_seconds=300, now=now)
    assert (stale["state"], stale["ageSeconds"], stale["lastBlock"]) == ("STALE", 1200, 5504401)
    assert watch_indexer(engine, DEP, alerter, max_age_seconds=300, now=now)["state"] == "STALE"  # deduplicated
    with Session(engine) as s, s.begin():
        s.get(ChainCursor, DEP).updated_at = now
    assert indexer_freshness(engine, DEP, now=now)["state"] == "FRESH"
    assert watch_indexer(engine, DEP, alerter, now=now)["state"] == "FRESH"
    assert [(a["key"], a["severity"], a["resolved"]) for a in sent] == [
        ("indexer-stale", "critical", False), ("indexer-stale", "warning", True)]  # a resolve carries the default severity
    assert "EVIDENCE_STALE" in sent[0]["text"] or "never synced" in sent[0]["text"]
