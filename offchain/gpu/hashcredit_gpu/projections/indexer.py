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
    ReorgJournal,
)
from ..domain.enums import ExecutionProfile, FacilityState
from ..receivables.service import lock
from .decoders import Decoder


class FinalizedReorg(RuntimeError):
    """Operator reconciliation required; no automatic rewrite of finalized financial facts."""


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
                    raise ValueError("canonical block unavailable")
                if parent_hash and block["parentHash"].lower() != parent_hash:
                    raise ValueError("chain changed while indexing; retry atomically")
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
                        raise ValueError("RPC returned log outside canonical requested range")
                    block = s.get(ChainBlock, (deployment_id, number))
                    if raw["blockHash"].lower() != block.hash:
                        raise ValueError("log belongs to another block hash")
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
                        raise ValueError("log lacks canonical successful receipt")
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
                    raise ValueError("chain changed before index commit")
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
    for model in (ProjectedEntity, ProjectedEvidence, ProjectedFacility):
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
    for tier in ("FINALIZED", "PENDING"):
        facilities, entities = {}, {}
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
