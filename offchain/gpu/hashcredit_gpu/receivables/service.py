"""Observed obligations are not approved collateral (R2-D04/D05/D06/D07).

The caller owns the SQLAlchemy transaction; these services flush but never commit.
Only trusted ingestion/workers may call mutations after authenticating the raw
observation. They are not public API request models. No method changes facility debt,
native status, control grade or approval. The current schema has no authoritative
decoded business/checkpoint binding; assessment reports that missing gate explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ..db.ledgers import (
    EvidenceConsumption,
    ExceptionCase,
    NativeVerification,
    RawSourceObservation,
    Receivable,
    ReceivableRevision,
)
from ..db.models import (
    ControlAgreement,
    CreditDecision,
    Facility,
    PolicyVersion,
    Provider,
    ProviderAccount,
)
from ..domain import AssetRef
from ..jobs.outbox import emit


class RevenueKind(StrEnum):
    OPERATING_RECEIVABLE = "OPERATING_RECEIVABLE"
    SELF_TRANSFER = "SELF_TRANSFER"
    INCENTIVE = "INCENTIVE"
    REFUND = "REFUND"
    BORROWING = "BORROWING"
    FUTURE_REVENUE = "FUTURE_REVENUE"
    UNKNOWN = "UNKNOWN"


class ReceivableError(ValueError):
    pass


def units(value: int, name: str, *, signed: bool = False) -> int:
    if type(value) is not int or (not signed and value < 0) or abs(value) >= 10**78:
        raise ReceivableError(
            f"{name} must be exact {'signed ' if signed else 'nonnegative '}integer base units"
        )
    return value


def aware(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ReceivableError(f"{name} must be timezone-aware")
    return value


def lock(session: Session, key: str) -> None:
    """Serialize semantic retries, including the first insert where no row exists yet."""
    session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": key})


def exception(session: Session, code: str, table: str, entity_id: str, **detail: str) -> None:
    existing = session.scalar(
        select(ExceptionCase).where(
            ExceptionCase.kind == code,
            ExceptionCase.entity_table == table,
            ExceptionCase.entity_id == entity_id,
            ExceptionCase.resolved_at.is_(None),
        )
    )
    if existing is None:
        session.add(
            ExceptionCase(
                exception_id=uuid4().hex.upper()[:26],
                kind=code,
                severity="BLOCKING",
                entity_table=table,
                entity_id=entity_id,
                detail=detail,
            )
        )
        session.flush()


@dataclass(frozen=True)
class ObligationInput:
    receivable_id: str
    provider_account_id: str
    obligation_ref: str
    observation_id: str
    asset: AssetRef
    gross: int
    net: int
    paid_amount: int
    revision: int
    kind: RevenueKind
    period_from: datetime
    period_to: datetime
    due_at: datetime
    execution_profile: str


@dataclass(frozen=True)
class ReceivableResult:
    receivable_id: str | None
    created: bool
    applied: bool
    reason: str | None = None


@dataclass(frozen=True)
class EligibilityResult:
    receivable_id: str
    policy_version_id: str
    execution_profile: str
    eligible: bool
    eligible_source_units: int
    observed_unpaid_units: int
    reasons: tuple[str, ...]
    # No FX quote is invented, and no borrowing headroom is implied by this assessment.
    borrowing_base_loan_units: int | None = None


def _source(session: Session, account_id: str, observation_id: str, profile: str):
    account = session.get(ProviderAccount, account_id)
    if account is None:
        raise ReceivableError("unknown provider account")
    provider = session.get(Provider, account.provider_id)
    observation = session.get(RawSourceObservation, observation_id)
    if provider.execution_profile != profile:
        raise ReceivableError("execution profile mismatch")
    if observation is None or observation.provider_id != account.provider_id:
        raise ReceivableError("observation provider mismatch")
    return account, provider


def _trace(session: Session, row: Receivable, observation_id: str, action: str) -> None:
    emit(
        session.connection(),
        aggregate_type="receivable",
        aggregate_id=row.receivable_id,
        event_type=action,
        idempotency_key=f"receivable:{row.receivable_id}:{observation_id}",
        payload={
            "receivableId": row.receivable_id,
            "economicEventId": row.economic_event_id,
            "observationId": observation_id,
            "revision": row.revision,
            "net": str(row.net),
            "paid": str(row.paid_amount),
            "unpaid": str(row.unpaid_amount),
            "executionProfile": row.execution_profile,
            "trust": "ASSERTED",
            "creditApproved": False,
        },
    )


def record_obligation(
    session: Session, command: ObligationInput, *, as_of: datetime
) -> ReceivableResult:
    """Merge API/statement/chain observations by the account's stable obligation ref.

    This records an *observed* business claim, even if the raw source says PROVEN.
    Native verification must be bound separately to decoded semantics before eligibility.
    Higher revisions use apply_revision(), never silently replace the original amounts.
    """
    aware(as_of, "as_of")
    for name in ("period_from", "period_to", "due_at"):
        aware(getattr(command, name), name)
    for name in ("gross", "net", "paid_amount", "revision"):
        units(getattr(command, name), name)
    if command.revision < 1 or not 0 <= command.paid_amount <= command.net <= command.gross:
        raise ReceivableError("invalid revision or gross/net/paid relationship")
    if (
        not command.obligation_ref
        or "/" in command.obligation_ref
        or len(command.obligation_ref) > 128
    ):
        raise ReceivableError("obligation reference must be stable, nonempty and unambiguous")
    if command.period_from >= command.period_to or command.due_at < command.period_to:
        raise ReceivableError("invalid service period or due date")
    account, provider = _source(
        session, command.provider_account_id, command.observation_id, command.execution_profile
    )
    if command.asset.chain_id != provider.source_chain_id:
        raise ReceivableError("source chain does not match provider")
    lock(session, f"receivable-account:{account.provider_account_id}")
    if command.kind != RevenueKind.OPERATING_RECEIVABLE or command.period_to > as_of:
        reason = "FUTURE_REVENUE" if command.period_to > as_of else f"NON_OPERATING:{command.kind}"
        exception(
            session,
            "REVENUE_INELIGIBLE",
            "raw_source_observations",
            command.observation_id,
            reason=reason,
        )
        return ReceivableResult(None, False, False, reason)
    economic_id = (
        f"{provider.provider_id}/{account.external_account_id}/OBLIGATION/{command.obligation_ref}"
    )
    row = session.scalar(
        select(Receivable)
        .where(
            Receivable.provider_account_id == account.provider_account_id,
            Receivable.obligation_ref == command.obligation_ref,
        )
        .with_for_update()
    )
    if row is not None:
        same = (
            row.revision == command.revision
            and int(row.gross) == command.gross
            and int(row.net) == command.net
            and int(row.paid_amount) == command.paid_amount
            and row.asset_chain_id == command.asset.chain_id
            and row.asset_token_address == command.asset.address
            and row.asset_decimals == command.asset.decimals
            and row.period_from == command.period_from
            and row.period_to == command.period_to
            and row.due_at == command.due_at
            and row.execution_profile == command.execution_profile
        )
        if same:
            _trace(session, row, command.observation_id, "RECEIVABLE_OBSERVATION_MERGED")
            return ReceivableResult(row.receivable_id, False, False, "DUPLICATE_OBSERVATION")
        reason = (
            "REVISION_REQUIRES_DELTA"
            if command.revision != row.revision
            else "AMOUNT_OR_BINDING_CONFLICT"
        )
        exception(
            session, reason, "receivables", row.receivable_id, observationId=command.observation_id
        )
        return ReceivableResult(row.receivable_id, False, False, reason)
    row = Receivable(
        receivable_id=command.receivable_id,
        economic_event_id=economic_id,
        provider_account_id=account.provider_account_id,
        obligation_ref=command.obligation_ref,
        asset_chain_id=command.asset.chain_id,
        asset_token_address=command.asset.address,
        asset_decimals=command.asset.decimals,
        gross=command.gross,
        net=command.net,
        paid_amount=command.paid_amount,
        unpaid_amount=command.net - command.paid_amount,
        state="PAID" if command.net == command.paid_amount else "RECOGNIZED",
        revision=command.revision,
        period_from=command.period_from,
        period_to=command.period_to,
        due_at=command.due_at,
        execution_profile=command.execution_profile,
    )
    session.add(row)
    session.flush()
    session.add(
        ReceivableRevision(
            receivable_id=row.receivable_id,
            revision=row.revision,
            kind="RECOGNIZED",
            observation_id=command.observation_id,
            delta=command.net,
            net_after=row.net,
            unpaid_after=row.unpaid_amount,
            out_of_order=False,
        )
    )
    overlaps = list(
        session.scalars(
            select(Receivable).where(
                Receivable.provider_account_id == row.provider_account_id,
                Receivable.receivable_id != row.receivable_id,
                Receivable.period_from < row.period_to,
                Receivable.period_to > row.period_from,
                Receivable.state.notin_(["CANCELLED", "WRITTEN_OFF"]),
            )
        )
    )
    for other in overlaps:
        # Overlap can be legitimate: quarantine for invoice-level reconciliation, never sum blindly.
        exception(
            session,
            "PERIOD_OVERLAP_REVIEW",
            "receivables",
            other.receivable_id,
            otherReceivableId=row.receivable_id,
        )
        exception(
            session,
            "PERIOD_OVERLAP_REVIEW",
            "receivables",
            row.receivable_id,
            otherReceivableId=other.receivable_id,
        )
    _trace(session, row, command.observation_id, "RECEIVABLE_OBSERVED")
    session.flush()
    return ReceivableResult(row.receivable_id, True, True)


def apply_revision(
    session: Session,
    *,
    receivable_id: str,
    observation_id: str,
    revision: int,
    kind: str,
    delta: int,
) -> ReceivableResult:
    """Apply an explicit observed net correction or source payout/cancellation delta.

    Positive PAYOUT reduces unpaid; positive CANCELLATION reverses a prior payout.
    Both invalidate the checkpoint and outstanding credit decisions. A cancellation
    never makes new credit available merely because we no longer observe payment.
    """
    units(revision, "revision")
    units(delta, "delta", signed=kind == "CORRECTION")
    if kind not in {"CORRECTION", "PAYOUT", "CANCELLATION"} or delta == 0:
        raise ReceivableError("explicit nonzero correction/payout/cancellation required")
    row = session.scalar(
        select(Receivable).where(Receivable.receivable_id == receivable_id).with_for_update()
    )
    if row is None:
        raise ReceivableError("unknown receivable")
    _source(session, row.provider_account_id, observation_id, row.execution_profile)
    previous = session.scalar(
        select(ReceivableRevision).where(
            ReceivableRevision.receivable_id == receivable_id,
            ReceivableRevision.revision == revision,
            ReceivableRevision.kind == kind,
        )
    )
    if previous is not None:
        if int(previous.delta) == delta:
            return ReceivableResult(receivable_id, False, False, "DUPLICATE_REVISION")
        exception(
            session, "REVISION_CONFLICT", "receivables", receivable_id, observationId=observation_id
        )
        return ReceivableResult(receivable_id, False, False, "REVISION_CONFLICT")
    reused = session.scalar(
        select(ReceivableRevision.id)
        .where(
            ReceivableRevision.receivable_id == receivable_id,
            ReceivableRevision.observation_id == observation_id,
        )
        .limit(1)
    )
    if reused is not None:
        exception(
            session,
            "OBSERVATION_ALREADY_APPLIED",
            "receivables",
            receivable_id,
            observationId=observation_id,
        )
        return ReceivableResult(receivable_id, False, False, "OBSERVATION_ALREADY_APPLIED")
    if revision != row.revision + 1:
        session.add(
            ReceivableRevision(
                receivable_id=receivable_id,
                revision=revision,
                kind=kind,
                observation_id=observation_id,
                delta=delta,
                net_after=row.net,
                unpaid_after=row.unpaid_amount,
                out_of_order=True,
            )
        )
        exception(
            session,
            "REVISION_OUT_OF_ORDER",
            "receivables",
            receivable_id,
            observationId=observation_id,
        )
        return ReceivableResult(receivable_id, False, False, "REVISION_OUT_OF_ORDER")
    if row.state in {"CANCELLED", "WRITTEN_OFF", "DISPUTED"}:
        raise ReceivableError("inactive/disputed receivable requires reviewed resolution")
    net, paid = int(row.net), int(row.paid_amount)
    if kind == "CORRECTION":
        net += delta
    elif kind == "PAYOUT":
        paid += delta
    else:
        paid -= delta
    if not 0 <= paid <= net <= int(row.gross):
        exception(
            session,
            "REVISION_BALANCE_CONFLICT",
            "receivables",
            receivable_id,
            observationId=observation_id,
        )
        return ReceivableResult(receivable_id, False, False, "REVISION_BALANCE_CONFLICT")
    row.net, row.paid_amount, row.unpaid_amount = net, paid, net - paid
    row.revision = revision
    row.state = (
        "PAID"
        if paid == net
        else "PARTIALLY_PAID" if paid else "ASSIGNED" if row.facility_id else "RECOGNIZED"
    )
    row.checkpoint_seq = None
    row.checkpoint_consumption_id = None
    session.add(
        ReceivableRevision(
            receivable_id=receivable_id,
            revision=revision,
            kind=kind,
            observation_id=observation_id,
            delta=delta,
            net_after=net,
            unpaid_after=net - paid,
            out_of_order=False,
        )
    )
    if row.facility_id:
        for decision in session.scalars(
            select(CreditDecision)
            .where(
                CreditDecision.facility_id == row.facility_id,
                CreditDecision.status.in_(["DRAFT", "APPROVED"]),
            )
            .with_for_update()
        ):
            decision.status = "REVOKED"
    _trace(session, row, observation_id, "RECEIVABLE_REVISED")
    session.flush()
    return ReceivableResult(receivable_id, False, True)


def evaluate_receivable(
    session: Session, receivable_id: str, facility_id: str, *, as_of: datetime
) -> EligibilityResult:
    """Read-only gate report, NOT a draw authorization or a live credit valuation.

    GPU-081 must provide authenticated decoded obligation/assignment/checkpoint binding
    and latest-state protection before the final missing gates can be removed. There is
    deliberately no `verified=True`, admin override or mock-positive production switch.
    """
    aware(as_of, "as_of")
    row, facility = session.get(Receivable, receivable_id), session.get(Facility, facility_id)
    if row is None or facility is None:
        raise ReceivableError("unknown receivable or facility")
    account = session.get(ProviderAccount, row.provider_account_id)
    provider = session.get(Provider, account.provider_id)
    policy = session.get(PolicyVersion, facility.policy_version_id)
    reasons = []
    if (
        row.execution_profile != facility.execution_profile
        or provider.execution_profile != facility.execution_profile
    ):
        reasons.append("PROFILE_MISMATCH")
    if row.facility_id != facility_id or account.borrower_id != facility.borrower_id:
        reasons.append("FACILITY_ASSIGNMENT_MISMATCH")
    if (
        provider.environment_status != "PROBED"
        or provider.capabilities.get("source_support") != "SUPPORTED"
    ):
        reasons.append("SOURCE_SUPPORT_UNCONFIRMED")
    if not policy or (facility.execution_profile == "PRODUCTION" and policy.test_only):
        reasons.append("POLICY_NOT_APPROVED")
    if row.state in {"PAID", "CANCELLED", "WRITTEN_OFF", "DISPUTED"} or row.unpaid_amount <= 0:
        reasons.append("NO_ELIGIBLE_UNPAID_BALANCE")
    if row.period_to is None or row.period_to > as_of:
        reasons.append("SERVICE_NOT_EARNED")
    if (
        row.due_at is None
        or row.due_at <= as_of
        or (facility.maturity_at and row.due_at > facility.maturity_at)
    ):
        reasons.append("MATURITY_INELIGIBLE")
    if session.scalar(
        select(ExceptionCase.exception_id)
        .where(
            ExceptionCase.entity_table == "receivables",
            ExceptionCase.entity_id == receivable_id,
            ExceptionCase.severity == "BLOCKING",
            ExceptionCase.resolved_at.is_(None),
        )
        .limit(1)
    ):
        reasons.append("RECONCILIATION_EXCEPTION")
    control = (
        session.get(ControlAgreement, facility.control_agreement_id)
        if facility.control_agreement_id
        else None
    )
    if (
        not control
        or control.control_grade not in {"E2", "E3"}
        or control.provider_account_id != row.provider_account_id
        or control.borrower_id != facility.borrower_id
        or control.version != facility.funded_agreement_version
        or not control.effective_from
        or control.effective_from > as_of
        or (control.effective_to and control.effective_to <= as_of)
    ):
        reasons.append("E2_CONTROL_NOT_CURRENT")
    checkpoint = (
        session.get(EvidenceConsumption, row.checkpoint_consumption_id)
        if row.checkpoint_consumption_id
        else None
    )
    verification = (
        session.get(NativeVerification, checkpoint.native_verification_id) if checkpoint else None
    )
    if (
        not checkpoint
        or checkpoint.meaning != "CHECKPOINT"
        or checkpoint.trust != "PROVEN"
        or checkpoint.verification_method != "ATTESTCOIN_NATIVE"
        or checkpoint.execution_profile != facility.execution_profile
        or checkpoint.provider_account_id != row.provider_account_id
        or checkpoint.env_id != provider.source_env_id
        or checkpoint.chain_key != provider.source_chain_key
        or checkpoint.manifest_hash != provider.manifest_hash
        or not verification
        or verification.status != "ACCEPTED"
    ):
        reasons.append("NATIVE_CHECKPOINT_MISSING_OR_INVALID")
    elif checkpoint.valid_until <= as_of or checkpoint.proven_at > as_of:
        reasons.append("NATIVE_CHECKPOINT_EXPIRED")
    # An accepted CHECKPOINT row holds only data_hash, not decoded unpaid/revision,
    # assignment, issuer provenance or a source state reservation valid through draw.
    reasons.extend(
        ["DECODED_BUSINESS_BINDING_NOT_IMPLEMENTED", "CURRENT_UNPAID_PROTECTION_NOT_IMPLEMENTED"]
    )
    return EligibilityResult(
        receivable_id,
        facility.policy_version_id,
        facility.execution_profile,
        False,
        0,
        int(row.unpaid_amount),
        tuple(dict.fromkeys(reasons)),
    )
