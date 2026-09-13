"""GPU-024 destination reconciliation checkpoint; never a second debt ledger.

Inputs come from an injected trusted, deployment-pinned canonical chain reader, not
an HTTP caller. No live reader is implemented here. A missing reader fails closed.
Its receipt amount must be actual custody balance delta, not a Transfer's nominal
amount or bridge acknowledgement. Allocation facts are already-final repayFor
results from GPU-039/073; storing them does not execute repayment or mutate Facility.

The caller owns the transaction. Receipt-level locks and database constraints cap
aggregate allocations and retries. Source assets are never compared/summed with
destination loan units. Unknown cash stays segregated and unallocated.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db.ledgers import Allocation, CashReceipt, ExceptionCase, Settlement
from ..db.models import Facility, ProviderAccount
from ..domain import AssetRef
from ..jobs.outbox import emit
from ..receivables.service import aware, exception, lock, units


@dataclass(frozen=True)
class DestinationRoute:
    vault_id: str
    receiver_address: str
    asset: AssetRef
    execution_profile: str


@dataclass(frozen=True)
class ReceiptFact:
    cash_receipt_id: str
    asset: AssetRef
    amount: int
    tx_hash: str
    log_index: int
    block_hash: str
    block_number: int
    payer_address: str | None
    payee_address: str
    source_kind: str
    execution_profile: str
    received_at: datetime
    canonical: bool
    finalized: bool
    receipt_status: int
    settlement_id: str | None = None


@dataclass(frozen=True)
class AllocationFact:
    allocation_id: str
    cash_receipt_id: str
    facility_id: str
    received: int
    fee_paid: int
    interest_paid: int
    principal_paid: int
    excess: int
    new_debt: int
    tx_hash: str
    chain_id: int
    execution_profile: str
    canonical: bool
    finalized: bool
    receipt_status: int


class CashEvidenceReader(Protocol):
    """Internal integration boundary for GPU-073/040, never user-controlled DTOs.

    Implementations authenticate receiver/token/deployment, source ownership or
    explicit direct-repayFor facility intent, canonical finality and event-to-cash
    binding. ReceiptFact.source_kind is business classification, not proof validity.
    """

    def receipt(self, reference: str) -> ReceiptFact | None: ...

    def allocation(self, reference: str) -> AllocationFact | None: ...


@dataclass(frozen=True)
class ReconciliationResult:
    entity_id: str | None
    created: bool
    reason: str | None = None


def _hash(value: str) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"0x[0-9a-f]{64}", value))


def _address(value: str | None) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"0x[0-9a-f]{40}", value))


def _block(session: Session, code: str, table: str, entity_id: str) -> ReconciliationResult:
    exception(session, code, table, entity_id)
    return ReconciliationResult(None, False, code)


def record_destination_receipt(
    session: Session,
    *,
    reference: str,
    route: DestinationRoute,
    reader: CashEvidenceReader | None = None,
) -> ReconciliationResult:
    """Persist finalized measured loan-currency custody, without applying debt.

    Trusted reader must also revalidate canonicality on retries. A detected reorg
    quarantines the record; this function never deletes an allocation or rewrites debt.
    """
    if reader is None:
        return ReconciliationResult(None, False, "DESTINATION_READER_NOT_CONFIGURED")
    fact = reader.receipt(reference)
    if fact is None:
        return ReconciliationResult(None, False, "DESTINATION_RECEIPT_NOT_FOUND")
    units(fact.amount, "amount")
    units(fact.log_index, "log_index")
    units(fact.block_number, "block_number")
    aware(fact.received_at, "received_at")
    if fact.amount == 0 or not _hash(fact.tx_hash) or not _hash(fact.block_hash):
        raise ValueError("positive measured amount and canonical transaction/block hashes required")
    if not _address(fact.payee_address) or not _address(route.receiver_address):
        raise ValueError("normalized receiver address required")
    key = f"destination-cash:{fact.asset.chain_id}:{fact.tx_hash}:{fact.log_index}"
    lock(session, key)
    existing = session.scalar(
        select(CashReceipt)
        .where(
            CashReceipt.chain_id == fact.asset.chain_id,
            CashReceipt.tx_hash == fact.tx_hash,
            CashReceipt.log_index == fact.log_index,
        )
        .with_for_update()
    )
    entity_id = existing.cash_receipt_id if existing else fact.cash_receipt_id
    if (
        fact.canonical is not True
        or type(fact.receipt_status) is not int
        or fact.receipt_status != 1
    ):
        return _block(session, "DESTINATION_NOT_CANONICAL_FINAL", "cash_receipts", entity_id)
    if fact.finalized is not True:
        # Expected finality lag is retryable, not a permanent reconciliation dispute.
        return ReconciliationResult(None, False, "DESTINATION_NOT_CANONICAL_FINAL")
    if (
        fact.asset.key != route.asset.key
        or fact.payee_address != route.receiver_address
        or fact.execution_profile != route.execution_profile
    ):
        return _block(session, "DESTINATION_ROUTE_MISMATCH", "cash_receipts", entity_id)
    if fact.source_kind not in {"SETTLEMENT", "DIRECT_REPAYMENT", "RECOVERY", "UNKNOWN"}:
        return _block(session, "NOT_DESTINATION_CASH", "cash_receipts", entity_id)
    if fact.payer_address is not None and not _address(fact.payer_address):
        raise ValueError("normalized payer address required")
    if fact.source_kind == "SETTLEMENT":
        settlement = session.get(Settlement, fact.settlement_id) if fact.settlement_id else None
        if (
            not settlement
            or settlement.execution_profile != route.execution_profile
            or settlement.state in {"ANNOUNCED", "REVERSED"}
        ):
            return _block(session, "SOURCE_SETTLEMENT_UNRECONCILED", "cash_receipts", entity_id)
    elif fact.settlement_id is not None:
        return _block(session, "CASH_CLASSIFICATION_CONFLICT", "cash_receipts", entity_id)
    source_kind = fact.source_kind if fact.payer_address else "UNKNOWN"
    if existing:
        same = (
            existing.vault_id == route.vault_id
            and existing.token_address == fact.asset.address
            and existing.decimals == fact.asset.decimals
            and int(existing.amount) == fact.amount
            and existing.payer_address == fact.payer_address
            and existing.source_kind == source_kind
            and existing.execution_profile == fact.execution_profile
            and existing.settlement_id == fact.settlement_id
        )
        if not same:
            return _block(session, "DESTINATION_RECEIPT_CONFLICT", "cash_receipts", entity_id)
        return ReconciliationResult(entity_id, False, "DUPLICATE_RECEIPT")
    row = CashReceipt(
        cash_receipt_id=fact.cash_receipt_id,
        vault_id=route.vault_id,
        chain_id=fact.asset.chain_id,
        token_address=fact.asset.address,
        decimals=fact.asset.decimals,
        amount=fact.amount,
        tx_hash=fact.tx_hash,
        log_index=fact.log_index,
        payer_address=fact.payer_address,
        source_kind=source_kind,
        settlement_id=fact.settlement_id,
        cash_state="DESTINATION_RECEIVED",
        execution_profile=fact.execution_profile,
        received_at=fact.received_at,
    )
    session.add(row)
    session.flush()
    emit(
        session.connection(),
        aggregate_type="cash_receipt",
        aggregate_id=row.cash_receipt_id,
        event_type="DESTINATION_CASH_RECONCILED",
        idempotency_key=key,
        payload={
            "cashReceiptId": row.cash_receipt_id,
            "reference": reference,
            "chainId": fact.asset.chain_id,
            "txHash": fact.tx_hash,
            "logIndex": fact.log_index,
            "blockHash": fact.block_hash,
            "blockNumber": str(fact.block_number),
            "payee": fact.payee_address,
            "amount": str(fact.amount),
            "executionProfile": fact.execution_profile,
            "debtApplied": False,
        },
    )
    if source_kind == "UNKNOWN":
        exception(session, "UNCLASSIFIED_DESTINATION_CASH", "cash_receipts", row.cash_receipt_id)
    return ReconciliationResult(
        row.cash_receipt_id,
        True,
        "UNCLASSIFIED_DESTINATION_CASH" if source_kind == "UNKNOWN" else None,
    )


def record_confirmed_allocation(
    session: Session, *, reference: str, reader: CashEvidenceReader | None = None
) -> ReconciliationResult:
    """Mirror a finalized repayFor result, never calculate or broadcast a repayment.

    Fee/interest/principal/new-debt are canonical event outputs. Facility projection
    can lag, so it is neither treated as an accrual oracle nor mutated here. Borrower
    refundable excess is stored independently from LP-applied components.
    """
    if reader is None:
        return ReconciliationResult(None, False, "DESTINATION_READER_NOT_CONFIGURED")
    fact = reader.allocation(reference)
    if fact is None:
        return ReconciliationResult(None, False, "FINAL_REPAYMENT_EVENT_NOT_FOUND")
    for name in ("received", "fee_paid", "interest_paid", "principal_paid", "excess", "new_debt"):
        units(getattr(fact, name), name)
    if (
        fact.received <= 0
        or fact.received != fact.fee_paid + fact.interest_paid + fact.principal_paid + fact.excess
    ):
        raise ValueError("repayment split must exactly equal measured allocated cash")
    if not _hash(fact.tx_hash):
        raise ValueError("normalized repayment transaction hash required")
    receipt = session.scalar(
        select(CashReceipt)
        .where(
            CashReceipt.cash_receipt_id == fact.cash_receipt_id,
        )
        .with_for_update()
    )
    if receipt is None:
        return _block(session, "DESTINATION_RECEIPT_MISSING", "allocations", fact.allocation_id)
    facility = session.get(Facility, fact.facility_id)
    if (
        fact.canonical is not True
        or type(fact.receipt_status) is not int
        or fact.receipt_status != 1
    ):
        return _block(
            session, "REPAYMENT_NOT_CANONICAL_FINAL", "cash_receipts", receipt.cash_receipt_id
        )
    if fact.finalized is not True:
        return ReconciliationResult(None, False, "REPAYMENT_NOT_CANONICAL_FINAL")
    if (
        not facility
        or (facility.loan_chain_id, facility.loan_token_address, facility.loan_decimals)
        != (receipt.chain_id, receipt.token_address, receipt.decimals)
        or facility.vault_id != receipt.vault_id
        or fact.chain_id != receipt.chain_id
    ):
        return _block(session, "FACILITY_CASH_ROUTE_MISMATCH", "allocations", fact.allocation_id)
    if (
        facility.execution_profile != receipt.execution_profile
        or fact.execution_profile != receipt.execution_profile
    ):
        return _block(session, "CASH_PROFILE_MISMATCH", "allocations", fact.allocation_id)
    if receipt.cash_state == "RETURNED" or receipt.source_kind == "UNKNOWN":
        return _block(session, "CASH_NOT_ALLOCATABLE", "allocations", fact.allocation_id)
    if session.scalar(
        select(ExceptionCase.exception_id)
        .where(
            ExceptionCase.entity_table == "cash_receipts",
            ExceptionCase.entity_id == receipt.cash_receipt_id,
            ExceptionCase.severity == "BLOCKING",
            ExceptionCase.resolved_at.is_(None),
        )
        .limit(1)
    ):
        return ReconciliationResult(None, False, "CASH_RECONCILIATION_EXCEPTION")
    if receipt.source_kind == "SETTLEMENT":
        settlement = session.get(Settlement, receipt.settlement_id)
        account = session.get(ProviderAccount, settlement.provider_account_id)
        if account.borrower_id != facility.borrower_id:
            return _block(session, "OTHER_BORROWER_CASH", "allocations", fact.allocation_id)
    existing = session.scalar(
        select(Allocation).where(
            Allocation.cash_receipt_id == receipt.cash_receipt_id,
            Allocation.facility_id == facility.facility_id,
        )
    )
    if existing:
        if (
            all(
                int(getattr(existing, name)) == getattr(fact, name)
                for name in (
                    "received",
                    "fee_paid",
                    "interest_paid",
                    "principal_paid",
                    "excess",
                    "new_debt",
                )
            )
            and existing.onchain_tx_hash == fact.tx_hash
        ):
            return ReconciliationResult(existing.allocation_id, False, "DUPLICATE_ALLOCATION")
        return _block(session, "ALLOCATION_CONFLICT", "allocations", fact.allocation_id)
    allocated = int(
        session.scalar(
            select(func.coalesce(func.sum(Allocation.received), 0)).where(
                Allocation.cash_receipt_id == receipt.cash_receipt_id,
            )
        )
    )
    if allocated + fact.received > int(receipt.amount):
        return _block(session, "ALLOCATION_EXCEEDS_RECEIPT", "allocations", fact.allocation_id)
    allocation = Allocation(
        allocation_id=fact.allocation_id,
        cash_receipt_id=receipt.cash_receipt_id,
        facility_id=facility.facility_id,
        received=fact.received,
        fee_paid=fact.fee_paid,
        interest_paid=fact.interest_paid,
        principal_paid=fact.principal_paid,
        excess=fact.excess,
        new_debt=fact.new_debt,
        onchain_tx_hash=fact.tx_hash,
    )
    session.add(allocation)
    if allocated + fact.received == int(receipt.amount):
        receipt.cash_state = "ALLOCATED"
    session.flush()
    emit(
        session.connection(),
        aggregate_type="allocation",
        aggregate_id=allocation.allocation_id,
        event_type="CONFIRMED_REPAYMENT_RECONCILED",
        idempotency_key=f"cash-allocation:{receipt.cash_receipt_id}:{facility.facility_id}",
        payload={
            "allocationId": allocation.allocation_id,
            "reference": reference,
            "cashReceiptId": receipt.cash_receipt_id,
            "facilityId": facility.facility_id,
            "received": str(fact.received),
            "excess": str(fact.excess),
            "txHash": fact.tx_hash,
            "executionProfile": fact.execution_profile,
        },
    )
    return ReconciliationResult(allocation.allocation_id, True)
