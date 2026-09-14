"""Atomic block/log/cursor ingestion, pending reorg rollback and deterministic replay."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from ..db.projections_models import (
    ChainBlock,
    ChainCursor,
    ChainDeployment,
    ChainLog,
    ProjectedEntity,
    ProjectedEvidence,
    ProjectedFacility,
    ProjectedFacilityCredit,
    ProjectedReceivable,
    ProjectedRepayment,
    ReorgJournal,
)
from ..domain.enums import ExecutionProfile, FacilityState
from ..receivables.service import lock
from ..reconciliation.chain_reader import pair_repayment_events
from .decoders import Decoder

CORRECTION_REASON_CANCEL = 3  # ISourceEscrow.CorrectionReason.CANCEL, mirrored by ReceivableBook


class FinalizedReorg(RuntimeError):
    """Operator reconciliation required; no automatic rewrite of finalized financial facts."""


class TransientChainChange(ValueError):
    """The chain moved (or the RPC answered inconsistently) while a chunk was being read; the transaction was
    rolled back and the persistent cursor is untouched, so the caller simply retries the chunk."""


class ChainIndexer:
    def __init__(self, engine, rpc):
        self.engine, self.rpc = engine, rpc

    def sync(self, deployment_id: str, chunk_size: int = 250) -> dict:
        if not 1 <= chunk_size <= 5000:
            raise ValueError("chunk_size must be between 1 and 5000")
        with Session(self.engine) as s, s.begin():
            lock(s, f"chain-indexer:{deployment_id}")
            d = s.get(ChainDeployment, deployment_id)
            if d is None:
                raise ValueError("unknown deployment")
            if self.rpc.chain_id() != d.chain_id:
                raise ValueError("RPC chain differs from deployment")
            decoder = Decoder(d.contracts)
            cursor = s.get(ChainCursor, deployment_id)
            head = self.rpc.block_number()
            last = cursor.last_block_number if cursor else d.deployment_block - 1
            finalized = cursor.finalized_block_number if cursor else d.deployment_block - 1
            if cursor:
                ancestor = last
                while ancestor >= d.deployment_block:
                    known = s.get(ChainBlock, (deployment_id, ancestor))
                    actual = self.rpc.get_block(ancestor)
                    if known and actual and known.hash == actual["hash"].lower():
                        break
                    if ancestor <= finalized:
                        raise FinalizedReorg(
                            f"canonical chain changed at finalized block {ancestor}"
                        )
                    ancestor -= 1
                if ancestor < last:
                    old_hash = cursor.last_block_hash
                    new_tip = self.rpc.get_block(min(last, head))
                    count = s.execute(
                        delete(ChainLog).where(
                            ChainLog.deployment_id == deployment_id,
                            ChainLog.block_number > ancestor,
                        )
                    ).rowcount
                    s.execute(
                        delete(ChainBlock).where(
                            ChainBlock.deployment_id == deployment_id, ChainBlock.number > ancestor
                        )
                    )
                    s.add(
                        ReorgJournal(
                            deployment_id=deployment_id,
                            fork_block=ancestor,
                            old_hash=old_hash,
                            new_hash=new_tip["hash"].lower(),
                            logs_rolled_back=count,
                        )
                    )
                    last = ancestor
            end = min(head, last + chunk_size)
            target_final = max(d.deployment_block - 1, min(end, head - d.finality_depth))
            parent = s.get(ChainBlock, (deployment_id, last))
            parent_hash = parent.hash if parent else None
            for number in range(last + 1, end + 1):
                block = self.rpc.get_block(number)
                if not block or int(block["number"], 16) != number:
                    raise TransientChainChange("canonical block unavailable")
                if parent_hash and block["parentHash"].lower() != parent_hash:
                    raise TransientChainChange("chain changed while indexing; retry atomically")
                parent_hash = block["hash"].lower()
                s.add(
                    ChainBlock(
                        deployment_id=deployment_id,
                        number=number,
                        hash=parent_hash,
                        parent_hash=block["parentHash"].lower(),
                        timestamp=int(block["timestamp"], 16),
                        tier="FINALIZED" if number <= target_final else "PENDING",
                    )
                )
            s.flush()
            if end > last:
                seen = set()
                receipts = {}
                for raw in sorted(
                    self.rpc.get_logs(decoder.addresses, last + 1, end),
                    key=lambda x: (
                        int(x["blockNumber"], 16),
                        int(x["transactionIndex"], 16),
                        int(x["logIndex"], 16),
                    ),
                ):
                    number = int(raw["blockNumber"], 16)
                    if number <= last or number > end or raw.get("removed"):
                        raise TransientChainChange("RPC returned log outside canonical requested range")
                    block = s.get(ChainBlock, (deployment_id, number))
                    if raw["blockHash"].lower() != block.hash:
                        raise TransientChainChange("log belongs to another block hash")
                    position = (raw["blockHash"], raw["transactionHash"], raw["logIndex"])
                    if position in seen:
                        continue
                    seen.add(position)
                    tx_key = raw["transactionHash"].lower()
                    if tx_key not in receipts:
                        receipts[tx_key] = self.rpc.get_receipt(tx_key)
                    receipt = receipts[tx_key]
                    if (
                        not receipt
                        or receipt["blockHash"].lower() != block.hash
                        or int(receipt["status"], 16) != 1
                    ):
                        raise TransientChainChange("log lacks canonical successful receipt")
                    decoded = decoder.decode(raw["address"], raw["topics"], raw["data"])
                    if decoder.contract_of(raw["address"]) is None:
                        raise ValueError("RPC returned unregistered contract")
                    s.add(
                        ChainLog(
                            deployment_id=deployment_id,
                            block_number=number,
                            block_hash=block.hash,
                            tx_hash=raw["transactionHash"].lower(),
                            tx_index=int(raw["transactionIndex"], 16),
                            log_index=int(raw["logIndex"], 16),
                            tx_status=1,
                            address=raw["address"].lower(),
                            contract_name=decoder.contract_of(raw["address"]),
                            event_name=decoded.event if decoded else "UNKNOWN",
                            topics=raw["topics"],
                            data=raw["data"],
                            decoded=decoded.args if decoded else {},
                            tier="FINALIZED" if number <= target_final else "PENDING",
                        )
                    )
                # Detect a moving chain after fetching logs, before committing the cursor.
                if (
                    self.rpc.get_block(end)["hash"].lower()
                    != s.get(ChainBlock, (deployment_id, end)).hash
                ):
                    raise TransientChainChange("chain changed before index commit")
            if end < d.deployment_block:
                return {
                    "deploymentId": deployment_id,
                    "lastBlock": last,
                    "head": head,
                    "lag": max(0, head - last),
                }
            for model, field in (
                (ChainBlock, ChainBlock.number),
                (ChainLog, ChainLog.block_number),
            ):
                s.execute(
                    update(model)
                    .where(model.deployment_id == deployment_id, field <= target_final)
                    .values(tier="FINALIZED")
                )
            s.flush()
            replay(s, d)
            # Resolve the block before adding a new cursor: get() can autoflush and
            # an incomplete cursor would violate NOT NULL at a log-free chain tip.
            end_hash = s.get(ChainBlock, (deployment_id, end)).hash
            if cursor is None:
                cursor = ChainCursor(
                    deployment_id=deployment_id,
                    last_block_number=end,
                    last_block_hash=end_hash,
                    finalized_block_number=target_final,
                    updated_at=datetime.now(UTC),
                )
                s.add(cursor)
            cursor.last_block_number = end
            cursor.last_block_hash = end_hash
            cursor.finalized_block_number = target_final
            cursor.updated_at = datetime.now(UTC)
            return {
                "deploymentId": deployment_id,
                "lastBlock": end,
                "finalizedBlock": target_final,
                "head": head,
                "lag": head - end,
            }


def replay(s: Session, d: ChainDeployment) -> None:
    """Rebuild small pilot read models solely from canonical raw logs, never API commands."""
    for model in (
        ProjectedEntity,
        ProjectedEvidence,
        ProjectedFacility,
        ProjectedFacilityCredit,
        ProjectedReceivable,
        ProjectedRepayment,
    ):
        s.execute(delete(model).where(model.deployment_id == d.deployment_id))
    logs = list(
        s.scalars(
            select(ChainLog)
            .where(ChainLog.deployment_id == d.deployment_id)
            .order_by(ChainLog.block_number, ChainLog.tx_index, ChainLog.log_index)
        )
    )
    verified = {
        (log.tx_hash, log.decoded.get("id")): log.decoded
        for log in logs
        if log.contract_name == "AttestcoinRevenueVerifier"
        and log.event_name == "SourceEventVerified"
    }
    # Block timestamps are needed for repayment legs and for the credit-status timeline.
    timed_blocks = {
        log.block_number
        for log in logs
        if log.event_name == "Repaid" or (log.contract_name, log.event_name) in CREDIT_EVENTS
    }
    blocks = {
        b.number: b
        for b in s.scalars(
            select(ChainBlock).where(
                ChainBlock.deployment_id == d.deployment_id, ChainBlock.number.in_(timed_blocks)
            )
        )
    } if timed_blocks else {}
    for tier in ("FINALIZED", "PENDING"):
        facilities, entities, receivables, credits = {}, {}, {}, {}
        tier_logs = [log for log in logs if tier == "PENDING" or log.tier == tier]
        _project_repayments(s, d, tier, tier_logs, blocks)
        for log in logs:
            if tier == "FINALIZED" and log.tier != tier:
                continue
            a, ev, contract = log.decoded, log.event_name, log.contract_name
            if ev == "UNKNOWN":
                continue
            key = a.get("facilityId")
            if key and contract in {"DebtLedger", "CreditFacilityManager"}:
                if key not in facilities:
                    facilities[key] = ProjectedFacility(
                        deployment_id=d.deployment_id,
                        tier=tier,
                        facility_key=key,
                        execution_profile=d.execution_profile,
                        state="DRAFT",
                        principal=0,
                        fees=0,
                        unpaid_interest_recorded=0,
                        rate_bps=0,
                        accrual_frozen=False,
                        last_block=log.block_number,
                    )
                    s.add(facilities[key])
                f = facilities[key]
                f.last_block = log.block_number
                if ev == "FacilityOpened":
                    if (
                        "profile" in a
                        and list(ExecutionProfile)[int(a["profile"])].value != d.execution_profile
                    ):
                        raise ValueError("event execution profile differs from deployment")
                    f.borrower_key = a.get("borrowerId", f.borrower_key)
                    f.rate_bps = int(a.get("rateBps", f.rate_bps))
                    f.last_accrual_at = int(a["openedAt"]) if "openedAt" in a else f.last_accrual_at
                elif ev in {"Drawn", "Capitalized"}:
                    f.principal = int(a["newPrincipal"])
                    if ev == "Capitalized":
                        f.unpaid_interest_recorded -= int(a["interestUnits"])
                elif ev == "Accrued":
                    f.unpaid_interest_recorded += int(a["interestUnits"])
                    f.last_accrual_at, f.rate_bps = int(a["to"]), int(a["rateBps"])
                elif ev == "FeeCharged":
                    f.fees += int(a["amount"])
                elif ev == "Allocated":
                    f.fees -= int(a["feePaid"])
                    f.unpaid_interest_recorded -= int(a["interestPaid"])
                    f.principal -= int(a["principalPaid"])
                    if f.fees + f.unpaid_interest_recorded + f.principal != int(a["newDebt"]):
                        raise ValueError("debt event conservation discrepancy")
                elif ev == "AccrualFrozen":
                    f.accrual_frozen = True
                elif ev in {"StateSet", "StateChanged"}:
                    f.state = list(FacilityState)[int(a.get("state", a.get("to")))].value
                elif ev == "FacilityFrozen":
                    f.state = "DRAW_FROZEN"
                elif ev == "AuthorizationAnchored":
                    f.last_decision_hash, f.authorization_valid_until = (
                        a["decisionHash"],
                        int(a["validUntil"]),
                    )
            if contract == "EvidenceBook" and ev == "SourceEventConsumed":
                proof = verified.get((log.tx_hash, a["id"]))
                if not proof:
                    raise ValueError(
                        "app consumption lacks native verifier event in same transaction"
                    )
                s.add(
                    ProjectedEvidence(
                        deployment_id=d.deployment_id,
                        tier=tier,
                        source_event_id=a["id"],
                        economic_event_key=a["economicEventId"],
                        consumer_address=a["consumer"],
                        meaning=a["meaning"],
                        manifest_hash=a["manifestHash"],
                        verification_method="LOCAL_MOCK"
                        if d.execution_profile == "LOCAL_MOCK"
                        else "ATTESTCOIN_NATIVE",
                        execution_profile=d.execution_profile,
                        verified_in_same_tx=True,
                        proven_height=int(proof["height"]),
                        proven_tx_index=int(proof["txIndex"]),
                        proven_log_ordinal=int(proof["logOrdinal"]),
                        consumption_tx_hash=log.tx_hash,
                        block_number=log.block_number,
                        block_hash=log.block_hash,
                        log_index=log.log_index,
                    )
                )
            if contract == "ReceivableBook":
                _project_receivable(s, d, tier, log, receivables)
            if (contract, ev) in CREDIT_EVENTS:
                _project_credit(s, d, tier, log, credits, blocks)
            kind = {
                "LendingVaultV2": "VAULT",
                "ProviderRegistry": "PROVIDER",
                "ControlRegistry": "CONTROL_AGREEMENT",
                "ReceivableBook": "RECEIVABLE",
                "ExposureController": "RESERVATION",
                "GpuRiskPolicy": "POLICY",
                "ProtocolRoles": "ROLE",
                "RevenueEscrow": "ESCROW",
                "SourceEscrow": "ESCROW",
                "EvidenceBook": "VERIFIER_BINDING",
            }.get(contract, "ADMIN")
            entity_key = next(
                (
                    a[k]
                    for k in (
                        "receivableId",
                        "reservationId",
                        "agreementId",
                        "providerId",
                        "accountKey",
                    )
                    if k in a
                ),
                log.address,
            )
            identity = (kind, entity_key)
            if identity not in entities:
                entities[identity] = ProjectedEntity(
                    deployment_id=d.deployment_id,
                    tier=tier,
                    kind=kind,
                    entity_key=entity_key,
                    state={},
                    last_block=log.block_number,
                )
                s.add(entities[identity])
            entity = entities[identity]
            entity.state = {**entity.state, ev: a, "lastEvent": ev, "lastTxHash": log.tx_hash}
            if contract == "LendingVaultV2" and ev == "Transfer":
                balances = dict(entity.state.get("shareBalances", {}))
                total = int(entity.state.get("totalShares", "0"))
                amount, zero = int(a["value"]), "0x" + "00" * 20
                if a["from"] == zero:
                    total += amount
                else:
                    balances[a["from"]] = str(int(balances.get(a["from"], "0")) - amount)
                if a["to"] == zero:
                    total -= amount
                else:
                    balances[a["to"]] = str(int(balances.get(a["to"], "0")) + amount)
                if total < 0 or any(int(v) < 0 for v in balances.values()):
                    raise ValueError(
                        "share event conservation discrepancy; deployment history incomplete"
                    )
                entity.state = {
                    **entity.state,
                    "shareBalances": balances,
                    "totalShares": str(total),
                }
            entity.last_block = log.block_number
        s.flush()


#: (contract, event) pairs folded into the credit-status read model.
CREDIT_EVENTS = {
    ("CreditFacilityManager", "StateChanged"),
    ("RecoveryManager", "ScheduleSet"),
    ("RecoveryManager", "DisputeSet"),
    ("RecoveryManager", "DefaultApproved"),
    ("RecoveryManager", "ReserveFunded"),
    ("RecoveryManager", "ReserveApplied"),
    ("RecoveryManager", "LossApplied"),
    ("LendingVaultV2", "ImpairmentRecognized"),
    ("LendingVaultV2", "ImpairmentReversed"),
    ("LendingVaultV2", "WrittenOff"),
}


def _project_credit(
    s: Session, d: ChainDeployment, tier: str, log: ChainLog, credits: dict, blocks: dict
) -> None:
    """Fold a manager / recovery / vault event into why-is-it-in-this-state (event-carried values only)."""
    a, ev = log.decoded, log.event_name
    key = a["facilityId"]
    block = blocks.get(log.block_number)
    if block is None:
        raise ValueError("credit event lacks its canonical block journal row")
    at = block.timestamp
    c = credits.get(key)
    if c is None:
        c = credits[key] = ProjectedFacilityCredit(
            deployment_id=d.deployment_id,
            tier=tier,
            facility_key=key,
            state="DRAFT",
            disputed=False,
            reserve_pledged=0,
            reserve_applied=0,
            impairment=0,
            transitions=[],
            last_block=log.block_number,
        )
        s.add(c)
    c.last_block = log.block_number
    if ev == "StateChanged":
        states = list(FacilityState)
        c.state = states[int(a["to"])].value
        c.state_trigger, c.state_authority = a["trigger"], a["authority"]
        c.state_changed_at, c.state_tx_hash = at, log.tx_hash
        c.transitions = [
            *c.transitions,
            {
                "from": states[int(a["from"])].value,
                "to": c.state,
                "trigger": a["trigger"],
                "authority": a["authority"],
                "txHash": log.tx_hash,
                "blockNumber": log.block_number,
                "at": at,
            },
        ]
    elif ev == "ScheduleSet":
        c.schedule_due_at = int(a["dueAt"])
        c.schedule_grace_seconds = int(a["graceSeconds"])
        c.schedule_due_amount = int(a["dueAmount"])
        c.schedule_set_at = at
        c.disputed = False
    elif ev == "DisputeSet":
        c.disputed = bool(a["disputed"])
        if c.disputed:
            c.default_reason, c.default_approved_at = None, None
    elif ev == "DefaultApproved":
        c.default_reason, c.default_approved_at = a["reason"], at
    elif ev == "ReserveFunded":
        c.reserve_owner = a["owner"]
        c.reserve_pledged += int(a["amount"])
    elif ev == "ReserveApplied":
        amount = int(a["amount"])
        if amount > c.reserve_pledged:
            raise ValueError("reserve application exceeds the pledged reserve")
        c.reserve_pledged -= amount
        c.reserve_applied += amount
    elif ev == "ImpairmentRecognized":
        c.impairment += int(a["amount"])
    elif ev == "ImpairmentReversed":
        amount = int(a["amount"])
        if amount > c.impairment:
            raise ValueError("impairment reversal exceeds the recognised impairment")
        c.impairment -= amount
    elif ev == "WrittenOff":
        c.impairment = 0  # the vault releases the book impairment when the facility leaves the performing book
    elif ev == "LossApplied" and bool(a["writeOff"]):
        c.loss_id, c.loss_amount, c.written_off_at = a["lossId"], int(a["amount"]), at


def _project_receivable(s: Session, d: ChainDeployment, tier: str, log: ChainLog, receivables: dict) -> None:
    """Fold one ReceivableBook event into the receivable read model (event-carried amounts only)."""
    a, ev = log.decoded, log.event_name
    key = a.get("receivableId")
    if not key:
        return  # CheckpointRecorded / FacilityRegistered / UnattributedPayoutRecorded carry no receivable
    r = receivables.get(key)
    if ev == "ReceivableRecognized":
        if r is not None:
            raise ValueError("receivable recognised twice in the canonical journal")
        r = ProjectedReceivable(
            deployment_id=d.deployment_id,
            tier=tier,
            receivable_key=key,
            account_key=a["accountKey"],
            obligation_ref=a["obligationRef"],
            state="OPEN",
            net=int(a["net"]),
            paid=0,
            revision=1,
            disputed=False,
            recognition_tx_hash=log.tx_hash,
            last_tx_hash=log.tx_hash,
            first_block=log.block_number,
            last_block=log.block_number,
            history=[],
        )
        receivables[key] = r
        s.add(r)
    elif r is None:
        raise ValueError("receivable event before its recognition in the canonical journal")
    elif ev == "ReceivableAssigned":
        r.facility_key = a["facilityId"]
        r.state = "ASSIGNED"
        r.revision = int(a["revision"])
    elif ev == "ReceivableCorrected":
        r.net += int(a["delta"])
        r.revision = int(a["revision"])
        if int(a["reason"]) == CORRECTION_REASON_CANCEL:
            r.state = "CANCELLED"
    elif ev == "ReceivablePaid":
        r.paid += int(a["amount"])
        r.revision += 1  # the book bumps the revision on an attributed payout (no revision in the log)
        if r.net - r.paid != int(a["unpaidAfter"]):
            raise ValueError("receivable payout conservation discrepancy")
        if r.paid == r.net:
            r.state = "PAID"
    elif ev == "ReceivablePayoutCancelled":
        r.paid -= int(a["amount"])
        r.revision += 1
        if r.state == "PAID":
            r.state = "ASSIGNED" if r.facility_key else "OPEN"
    elif ev == "ReceivableDisputed":
        r.disputed = bool(a["disputed"])
    else:
        return
    if r.net < 0 or r.paid < 0 or r.paid > r.net:
        raise ValueError("receivable amount conservation discrepancy")
    r.last_tx_hash, r.last_block = log.tx_hash, log.block_number
    r.history = [
        *r.history,
        {
            "event": ev,
            "txHash": log.tx_hash,
            "blockNumber": log.block_number,
            "logIndex": log.log_index,
            "args": a,
        },
    ]


def _project_repayments(s: Session, d: ChainDeployment, tier: str, logs: list, blocks: dict) -> None:
    """One row per paired manager/router Repaid leg; unpaired Repaid logs are not history."""
    by_tx: dict[str, list] = {}
    for log in logs:
        by_tx.setdefault(log.tx_hash, []).append(log)
    for log in logs:
        if log.event_name != "Repaid" or log.contract_name not in {"RepaymentRouter", "CreditFacilityManager"}:
            continue
        facility_key = log.decoded.get("facilityId")
        if not facility_key:
            continue
        paired = pair_repayment_events(
            by_tx[log.tx_hash], d.contracts, log.log_index, facility_key, allow_settlement_ref=True
        )
        if paired is None:
            continue
        repaid, allocated, vault_receipt = paired
        allocation, cash, repayment = allocated.decoded, vault_receipt.decoded, repaid.decoded
        fee, interest, principal = (int(allocation[k]) for k in ("feePaid", "interestPaid", "principalPaid"))
        received, excess, new_debt = int(repayment["received"]), int(repayment["excess"]), int(repayment["newDebt"])
        if (
            fee + interest + principal + excess != received
            or int(cash["received"]) != received
            or int(cash["excess"]) != excess
            or int(allocation["newDebt"]) != new_debt
        ):
            raise ValueError("repayment event conservation discrepancy")
        block = blocks.get(repaid.block_number)
        if block is None or block.hash != repaid.block_hash:
            raise ValueError("repayment log is not anchored in the canonical block journal")
        s.add(
            ProjectedRepayment(
                deployment_id=d.deployment_id,
                tier=tier,
                tx_hash=repaid.tx_hash,
                log_index=repaid.log_index,
                facility_key=facility_key,
                repaid_contract=repaid.contract_name,
                payer=repayment["payer"],
                settlement_ref=repayment.get("settlementRef"),
                requested=int(repayment["requested"]),
                received=received,
                fee_paid=fee,
                interest_paid=interest,
                principal_paid=principal,
                excess=excess,
                new_debt=new_debt,
                block_number=repaid.block_number,
                block_hash=repaid.block_hash,
                block_timestamp=block.timestamp,
            )
        )
