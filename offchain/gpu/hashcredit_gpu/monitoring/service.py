"""Classify observation outages separately from payment/control breaches (GPU-044)."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select

from ..db.ledgers import CashReceipt, ExceptionCase, ProofRequest
from ..db.models import ControlAgreement, ControlObservation, Facility, Provider, ProviderAccount
from ..db.projections_models import ChainCursor, ChainDeployment
from ..jobs.outbox import emit
from ..jobs.queue import new_ulid, write_audit
from ..receivables.service import aware, lock


@dataclass(frozen=True)
class MonitorPolicy:
    observation_max_age_seconds: int = 3600
    projection_max_age_seconds: int = 300
    pending_cash_max_age_seconds: int = 3600


@dataclass(frozen=True)
class Finding:
    code: str
    blocks_new_draw: bool
    category: str


def assess_facility(
    session,
    facility_id: str,
    *,
    now: datetime,
    deployment_id: str,
    policy: MonitorPolicy | None = None,
) -> tuple[Finding, ...]:
    policy = policy or MonitorPolicy()
    aware(now, "now")
    facility = session.get(Facility, facility_id)
    if not facility:
        raise ValueError("unknown facility")
    deployment = session.get(ChainDeployment, deployment_id)
    findings = []
    control = (
        session.get(ControlAgreement, facility.control_agreement_id)
        if facility.control_agreement_id
        else None
    )
    if (
        not control
        or control.control_grade not in {"E2", "E3"}
        or control.version != facility.funded_agreement_version
        or control.effective_from is None
        or control.effective_from > now
        or (control.effective_to and control.effective_to <= now)
    ):
        findings.append(Finding("CONTROL_NOT_CURRENT", True, "CONTROL"))
    if control:
        if (
            not control.last_observed_at
            or (now - control.last_observed_at).total_seconds() > policy.observation_max_age_seconds
        ):
            findings.append(Finding("CONTROL_OBSERVATION_STALE", True, "OBSERVABILITY"))
        latest = session.scalar(
            select(ControlObservation)
            .where(ControlObservation.control_agreement_id == control.control_agreement_id)
            .order_by(ControlObservation.observed_at.desc())
            .limit(1)
        )
        if latest and latest.observed_at <= now:
            if latest.receiver_address and latest.receiver_address != control.receiver_address:
                findings.append(Finding("CONTROL_RECEIVER_CHANGED", True, "CONTROL"))
            if latest.provenance.get("borrowerCanChangeReceiver") is True:
                findings.append(Finding("CONTROL_BYPASS_OBSERVED", True, "CONTROL"))
        account = session.get(ProviderAccount, control.provider_account_id)
        provider = session.get(Provider, account.provider_id) if account else None
        if provider:
            if (
                provider.environment_status != "PROBED"
                or provider.capabilities.get("source_support") != "SUPPORTED"
            ):
                findings.append(Finding("NATIVE_ENVIRONMENT_UNAVAILABLE", True, "OBSERVABILITY"))
            statuses = set(
                session.scalars(
                    select(ProofRequest.status).where(
                        ProofRequest.provider_id == provider.provider_id,
                        ProofRequest.execution_profile == facility.execution_profile,
                        ProofRequest.manifest_hash == deployment.manifest_hash if deployment else False,
                    )
                )
            )
            if statuses & {"OBSERVED", "WAITING_ATTESTATION", "PROOF_READY", "SUBMITTED"}:
                # Pending new facts do not invalidate still-current previously verified collateral.
                findings.append(Finding("NATIVE_PROOF_PENDING", False, "OBSERVABILITY"))
            if statuses & {"INVALID", "UNSUPPORTED", "EXPIRED"}:
                findings.append(Finding("NATIVE_PROOF_REVIEW_REQUIRED", False, "OBSERVABILITY"))
    cursor = session.get(ChainCursor, deployment_id)
    if not cursor or (now - cursor.updated_at).total_seconds() > policy.projection_max_age_seconds:
        findings.append(Finding("PROJECTION_STALE", True, "OBSERVABILITY"))
    if session.scalar(
        select(CashReceipt.cash_receipt_id)
        .where(
            CashReceipt.vault_id == facility.vault_id,
            CashReceipt.chain_id == facility.loan_chain_id,
            CashReceipt.execution_profile == facility.execution_profile,
            CashReceipt.cash_state == "DESTINATION_RECEIVED",
            CashReceipt.source_kind == "UNKNOWN",
        )
        .limit(1)
    ):
        findings.append(Finding("UNALLOCATED_CASH_REVIEW", False, "CASH"))
    return tuple(findings)


def record_findings(
    session, facility_id: str, findings: tuple[Finding, ...], *, now: datetime
) -> list[str]:
    """Idempotent exception lifecycle + review events. Never defaults a facility or suspends repayment."""
    aware(now, "now")
    lock(session, f"monitoring:{facility_id}")
    existing = list(
        session.scalars(
            select(ExceptionCase).where(
                ExceptionCase.entity_table == "facilities",
                ExceptionCase.entity_id == facility_id,
                ExceptionCase.resolved_at.is_(None),
            )
        )
    )
    existing = [row for row in existing if row.detail.get("source") == "GPU044_MONITOR"]
    active = {f.code for f in findings}
    ids = []
    for finding in findings:
        row = next((r for r in existing if r.kind == finding.code), None)
        if row is None:
            row = ExceptionCase(
                exception_id=new_ulid(),
                kind=finding.code,
                severity="BLOCKING" if finding.blocks_new_draw else "WARNING",
                entity_table="facilities",
                entity_id=facility_id,
                detail={
                    "source": "GPU044_MONITOR",
                    "category": finding.category,
                    "blocksNewDraw": finding.blocks_new_draw,
                    "repaymentPermitted": True,
                    "defaultApplied": False,
                },
            )
            session.add(row)
            session.flush()
            emit(
                session.connection(),
                aggregate_type="facility",
                aggregate_id=facility_id,
                event_type="MONITORING_REVIEW_REQUIRED",
                idempotency_key=f"monitor-open:{row.exception_id}",
                payload={"exceptionId": row.exception_id, "reason": finding.code, **row.detail},
            )
            write_audit(
                session.connection(),
                actor="gpu-monitor",
                actor_role="system",
                action="MONITOR_FINDING_OPENED",
                entity_table="exceptions",
                entity_id=row.exception_id,
                before=None,
                after=row.detail,
                correlation_id=None,
            )
        ids.append(row.exception_id)
    for row in existing:
        # An actual payment/control breach still needs a reviewed cure; only telemetry failures auto-resolve.
        if row.kind not in active and row.detail.get("category") == "OBSERVABILITY":
            row.resolved_at, row.resolved_by = now, "system"
            row.resolution = "Current monitored source recovered; no financial state changed"
            emit(
                session.connection(),
                aggregate_type="facility",
                aggregate_id=facility_id,
                event_type="MONITORING_OBSERVATION_RECOVERED",
                idempotency_key=f"monitor-recovered:{row.exception_id}",
                payload={"exceptionId": row.exception_id, "reason": row.kind},
            )
    return ids
