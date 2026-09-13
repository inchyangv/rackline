"""Persist settlement leg intents and receipts; source sends or bridge acknowledgements are not repayment."""

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.ledgers import EvidenceConsumption, NativeVerification, Outbox, Settlement
from ..domain import AssetRef
from ..jobs import JobQueue, TerminalError, TransientError
from ..jobs.outbox import emit
from ..receivables.service import exception, lock
from ..reconciliation.engine import (
    DestinationRoute,
    record_confirmed_allocation,
    record_destination_receipt,
)


@dataclass(frozen=True)
class RailBinding:
    rail_id: str
    execution_profile: str
    status: str
    partner_binding: str
    source_asset: AssetRef
    destination_asset: AssetRef
    destination_receiver: str
    vault_id: str
    source_cap: int
    max_fee_destination: int
    max_slippage_bps: int
    approval_ref: str
    refund_address: str


@dataclass(frozen=True)
class Quote:
    leg_id: str
    settlement_id: str
    rail_id: str
    source_amount: int
    expected_destination: int
    minimum_destination: int
    fee_destination: int
    expires_at: int
    destination_receiver: str
    refund_address: str


@dataclass(frozen=True)
class LegObservation:
    state: str
    reference: str
    receipt_reference: str | None = None


class SettlementAdapter(Protocol):
    is_mock: bool
    idempotent_requests: bool

    def lookup(self, idempotency_key: str) -> str | None: ...
    def send(self, quote: Quote, idempotency_key: str) -> str: ...
    def observe(self, reference: str) -> LegObservation: ...


def validate_quote(quote: Quote, binding: RailBinding, *, now: int):
    if not binding.approval_ref or binding.status not in {"APPROVED", "TEST_ONLY"}:
        raise ValueError("settlement rail is not approved")
    if binding.execution_profile == "PRODUCTION" and (
        binding.status != "APPROVED" or binding.partner_binding != "LIVE_VERIFIED"
    ):
        raise ValueError("production settlement requires a verified live rail")
    if (
        quote.rail_id != binding.rail_id
        or quote.destination_receiver != binding.destination_receiver
        or quote.refund_address != binding.refund_address
    ):
        raise ValueError("quote destination/refund route mismatch")
    values = (
        quote.source_amount,
        quote.expected_destination,
        quote.minimum_destination,
        quote.fee_destination,
        quote.expires_at,
    )
    if any(type(v) is not int or v < 0 for v in values):
        raise ValueError("quote uses nonnegative exact integer units")
    if not 0 <= binding.max_slippage_bps <= 10000 or quote.expires_at <= now:
        raise ValueError("expired quote or invalid slippage policy")
    if not 0 < quote.source_amount <= binding.source_cap:
        raise ValueError("source leg cap exceeded")
    if quote.fee_destination > binding.max_fee_destination:
        raise ValueError("settlement fee cap exceeded")
    if not 0 < quote.minimum_destination <= quote.expected_destination:
        raise ValueError("invalid minimum destination amount")
    if quote.minimum_destination * 10000 < quote.expected_destination * (
        10000 - binding.max_slippage_bps
    ):
        raise ValueError("minimum destination violates slippage bound")


class SettlementLegExecutor:
    def __init__(self, engine, binding: RailBinding, adapter: SettlementAdapter, cash_reader):
        self.engine, self.binding, self.adapter, self.cash_reader = (
            engine,
            binding,
            adapter,
            cash_reader,
        )
        self.queue = JobQueue(engine)

    def enqueue(self, session, quote: Quote, *, now: int):
        validate_quote(quote, self.binding, now=now)
        if self.adapter.is_mock and self.binding.execution_profile == "PRODUCTION":
            raise ValueError("mock settlement adapter cannot run in production")
        if not self.adapter.idempotent_requests:
            raise ValueError("durable settlement requires an idempotent external interface")
        lock(session, f"settlement-leg:{quote.settlement_id}")
        settlement = session.get(Settlement, quote.settlement_id)
        evidence = (
            session.get(EvidenceConsumption, settlement.payout_consumption_id)
            if settlement and settlement.payout_consumption_id
            else None
        )
        verified = (
            session.get(NativeVerification, evidence.native_verification_id) if evidence else None
        )
        if (
            not settlement
            or settlement.execution_profile != self.binding.execution_profile
            or settlement.state in {"ANNOUNCED", "REVERSED"}
            or (
                settlement.asset_chain_id,
                settlement.asset_token_address or "",
                settlement.asset_decimals,
            )
            != self.binding.source_asset.key
            or not evidence
            or evidence.meaning != "PAYOUT"
            or evidence.trust != "PROVEN"
            or evidence.provider_account_id != settlement.provider_account_id
            or not verified
            or verified.status != "ACCEPTED"
            or (
                self.binding.execution_profile != "LOCAL_MOCK"
                and evidence.verification_method != "ATTESTCOIN_NATIVE"
            )
        ):
            raise ValueError("source settlement requires matching native payout evidence")
        key = f"settlement-plan:{self.binding.rail_id}:{quote.leg_id}"
        prior = session.scalar(select(Outbox).where(Outbox.idempotency_key == key))
        payload = asdict(quote)
        if prior and prior.payload != payload:
            raise ValueError("legId already bound to another quote")
        if not prior:
            reserved = sum(
                int(row.payload["source_amount"])
                for row in session.scalars(
                    select(Outbox).where(
                        Outbox.aggregate_type == "settlement",
                        Outbox.aggregate_id == quote.settlement_id,
                        Outbox.event_type == "SETTLEMENT_LEG_PLANNED",
                    )
                )
            )
            if reserved + quote.source_amount > settlement.source_amount:
                raise ValueError("settlement legs exceed source receipt")
            emit(
                session.connection(),
                aggregate_type="settlement",
                aggregate_id=quote.settlement_id,
                event_type="SETTLEMENT_LEG_PLANNED",
                idempotency_key=key,
                payload=payload,
            )
        return self.queue.enqueue(
            "SETTLEMENT_LEG",
            payload,
            f"settlement-leg:{self.binding.rail_id}:{quote.leg_id}",
            max_attempts=100,
            cx=session.connection(),
        )

    def handle(self, cx, job):
        quote = Quote(**job.payload)
        with Session(bind=cx) as session:
            settlement = session.get(Settlement, quote.settlement_id)
            if not settlement:
                raise TerminalError("unknown source settlement")
            ack_key = f"settlement-ack:{self.binding.rail_id}:{quote.leg_id}"
            ack = session.scalar(select(Outbox).where(Outbox.idempotency_key == ack_key))
            if not ack:
                # A timeout may have happened after sending. Resolve the existing request even
                # after its quote expires; never infer that a lost acknowledgement was a failed send.
                reference = self.adapter.lookup(quote.leg_id)
                if reference is None:
                    try:
                        self.enqueue(session, quote, now=int(datetime.now(UTC).timestamp()))
                    except ValueError as exc:
                        raise TerminalError(str(exc)) from exc
                    reference = self.adapter.send(quote, quote.leg_id)
                if not reference:
                    raise TransientError("settlement submission outcome unknown")
                with self.engine.begin() as own:
                    emit(
                        own,
                        aggregate_type="settlement",
                        aggregate_id=quote.settlement_id,
                        event_type="SETTLEMENT_LEG_ACKNOWLEDGED",
                        idempotency_key=ack_key,
                        payload={
                            "reference": reference,
                            "legId": quote.leg_id,
                            "cashState": "IN_FLIGHT",
                            "debtApplied": False,
                        },
                    )
            else:
                reference = ack.payload["reference"]
            observation = self.adapter.observe(reference)
            if observation.reference != reference:
                raise TerminalError("settlement observation reference mismatch")
            if observation.state in {"PENDING", "SOURCE_SENT", "IN_FLIGHT"}:
                raise TransientError("destination receipt pending; source send is not repayment")
            if observation.state == "REFUNDED":
                emit(
                    cx,
                    aggregate_type="settlement",
                    aggregate_id=quote.settlement_id,
                    event_type="SETTLEMENT_LEG_REFUNDED",
                    idempotency_key=f"settlement-refund:{self.binding.rail_id}:{quote.leg_id}",
                    payload={
                        "reference": reference,
                        "refundAddress": quote.refund_address,
                        "debtApplied": False,
                    },
                )
                return
            if observation.state != "DESTINATION_RECEIVED" or not observation.receipt_reference:
                raise TransientError("settlement outcome unresolved")
            if self.cash_reader is None:
                raise TransientError("destination canonical cash reader unavailable")
            fact = self.cash_reader.receipt(observation.receipt_reference)
            if fact is None:
                raise TransientError("destination receipt not yet indexed")
            if fact.source_kind != "SETTLEMENT" or fact.settlement_id != quote.settlement_id:
                raise TerminalError("destination receipt does not belong to this settlement")
            route = DestinationRoute(
                self.binding.vault_id,
                self.binding.destination_receiver,
                self.binding.destination_asset,
                self.binding.execution_profile,
            )
            # Measured destination cash is durable even if allocation is still pending or
            # actual execution breached a quoted minimum. Never erase real cash on a retry.
            with Session(self.engine) as own, own.begin():
                result = record_destination_receipt(
                    own,
                    reference=observation.receipt_reference,
                    route=route,
                    reader=self.cash_reader,
                )
                if result.entity_id is not None and fact.amount < quote.minimum_destination:
                    exception(own, "SETTLEMENT_MINIMUM_BREACH", "settlements", quote.settlement_id)
                    emit(
                        own.connection(),
                        aggregate_type="settlement",
                        aggregate_id=quote.settlement_id,
                        event_type="SETTLEMENT_LEG_SLIPPAGE_BREACH",
                        idempotency_key=f"settlement-slippage:{self.binding.rail_id}:{quote.leg_id}",
                        payload={
                            "actualDestination": str(fact.amount),
                            "minimumDestination": str(quote.minimum_destination),
                            "requiresReview": True,
                        },
                    )
            if result.entity_id is None:
                raise TransientError(result.reason or "destination receipt not reconciled")
            allocated = record_confirmed_allocation(
                session, reference=observation.receipt_reference, reader=self.cash_reader
            )
            if allocated.entity_id is None:
                raise TransientError(allocated.reason or "destination allocation pending")
            emit(
                cx,
                aggregate_type="settlement",
                aggregate_id=quote.settlement_id,
                event_type="SETTLEMENT_LEG_ALLOCATED",
                idempotency_key=f"settlement-allocated:{self.binding.rail_id}:{quote.leg_id}",
                payload={
                    "reference": reference,
                    "allocationId": allocated.entity_id,
                    "cashState": "ALLOCATED",
                },
            )
