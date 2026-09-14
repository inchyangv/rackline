"""Measured direct repayments from final manager/router, vault and ledger events."""

import hashlib
from datetime import UTC, datetime

from eth_abi import decode
from eth_utils import keccak
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import Facility
from ..db.product_models import FacilityBinding
from ..db.projections_models import ChainBlock, ChainDeployment, ChainLog
from ..domain import AssetRef
from ..projections.views import ContractViews
from .engine import AllocationFact, ReceiptFact


def stable_id(reference: str) -> str:
    value = int.from_bytes(hashlib.sha256(reference.encode()).digest()[:16], "big")
    alphabet = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
    return "".join(alphabet[(value >> (5 * i)) & 31] for i in reversed(range(26)))


_REPAYMENT_CONTRACTS = {"CreditFacilityManager", "RepaymentRouter"}
_ZERO_REF = "0x" + "00" * 32


def _uint(value):
    if type(value) is int:
        result = value
    elif isinstance(value, str) and value.isascii() and value.isdecimal():
        result = int(value)
    else:
        raise ValueError("invalid canonical uint")
    if not 0 <= result < 2**256:
        raise ValueError("canonical uint out of range")
    return result


def pair_repayment_events(logs, contract_addresses, target_index, facility_key, allow_settlement_ref=False):
    """Pair one direct accounting leg; malformed or unsupported evidence fails closed.

    `allow_settlement_ref` admits a router Repaid that carries a caller-supplied settlement reference
    (third-party `repayFor`); cash reconciliation keeps the default and treats it as unsupported.

    Every configured manager/router Repaid is a boundary, including unsupported
    settlement repayments. AllocationApplied is never an alternative cash anchor.
    Callers must first scope logs to their deployment and canonical finalized blocks.
    """
    try:
        configured = [
            event for event in logs
            if event.address.lower() == contract_addresses.get(event.contract_name, "").lower()
            and event.decoded.get("facilityId", "").lower() == facility_key.lower()
        ]
        targets = [event for event in configured if event.log_index == target_index
                   and event.contract_name in _REPAYMENT_CONTRACTS
                   and event.event_name == "Repaid"]
        if len(targets) != 1:
            return None
        repaid = targets[0]
        identity = (repaid.tx_hash, repaid.block_number, repaid.block_hash, repaid.tx_index)
        same_tx = [event for event in configured
                   if (event.tx_hash, event.block_number, event.block_hash, event.tx_index) == identity]
        previous = max((event.log_index for event in same_tx
                        if event.contract_name in _REPAYMENT_CONTRACTS
                        and event.event_name == "Repaid" and event.log_index < target_index), default=-1)
        leg = [event for event in same_tx if previous < event.log_index < target_index]
        allocations = [event for event in leg
                       if event.contract_name == "DebtLedger" and event.event_name == "Allocated"]
        receipts = [event for event in leg
                    if event.contract_name == "LendingVaultV2" and event.event_name == "RepaymentReceived"]
        if len(allocations) != 1 or len(receipts) != 1:
            return None
        allocated, vault = allocations[0], receipts[0]
        if allocated.log_index >= vault.log_index:
            return None
        # A settlement allocation marker belongs to the preceding repayment, not
        # a second receipt. Do not classify even a zero-ID settlement as direct.
        next_leg = min((event.log_index for event in same_tx
                        if event.log_index > target_index and (
                            event.contract_name in _REPAYMENT_CONTRACTS and event.event_name == "Repaid"
                            or event.contract_name == "DebtLedger" and event.event_name == "Allocated"
                        )), default=float("inf"))
        if any(event.contract_name == "RepaymentRouter" and event.event_name == "AllocationApplied"
               and allocated.log_index < event.log_index < next_leg for event in same_tx):
            return None
        a, v, r = allocated.decoded, vault.decoded, repaid.decoded
        if (repaid.contract_name == "RepaymentRouter" and not allow_settlement_ref
                and r["settlementRef"].lower() != _ZERO_REF):
            return None
        amounts = [_uint(a[key]) for key in ("feePaid", "interestPaid", "principalPaid", "excess", "newDebt")]
        received, applied, excess = (_uint(v[key]) for key in ("received", "applied", "excess"))
        _uint(r["requested"])
        if (received <= 0 or received != applied + excess or applied != sum(amounts[:3])
                or excess != amounts[3] or _uint(r["newDebt"]) != amounts[4]
                or any(_uint(v[key]) != _uint(r[key]) for key in ("received", "applied", "excess"))):
            return None
        if repaid.contract_name == "RepaymentRouter" and any(
            _uint(r[key]) != _uint(a[key]) for key in ("feePaid", "interestPaid", "principalPaid")
        ):
            return None
        return repaid, allocated, vault
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
        return None


def _is_direct_router_transaction(transaction, repaid, contracts):
    """Only known top-level direct selectors can enter the direct-cash importer."""
    try:
        if not transaction or (
            transaction["hash"].lower() != repaid.tx_hash
            or transaction["blockHash"].lower() != repaid.block_hash
            or int(transaction["blockNumber"], 16) != repaid.block_number
            or transaction["to"].lower() != contracts["RepaymentRouter"].lower()
            or transaction["from"].lower() != repaid.decoded["payer"].lower()
        ):
            return False
        data = bytes.fromhex(transaction["input"].removeprefix("0x"))
        selectors = {
            keccak(text="repayExact(bytes32,uint256)")[:4]: ["bytes32", "uint256"],
            keccak(text="repayFor(bytes32,uint256,bytes32)")[:4]: ["bytes32", "uint256", "bytes32"],
        }
        types = selectors.get(data[:4])
        if not types or len(data) != 4 + 32 * len(types):
            return False
        values = decode(types, data[4:])
        return ("0x" + values[0].hex() == repaid.decoded["facilityId"].lower()
                and int(repaid.decoded["requested"]) <= values[1]
                and (len(values) == 2 or values[2] == bytes(32)))
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
        return False


class CanonicalRepaymentReader:
    """Reference = 'txHash:RepaidLogIndex'; raw ERC20 Transfer is never sufficient.

    Manager/router boundaries pair measured vault receipts to preceding allocations,
    including repeated repayments for the same facility within one transaction.
    """

    def __init__(self, engine, rpc, deployment_id: str):
        self.engine, self.rpc, self.deployment_id = engine, rpc, deployment_id

    def _facts(self, reference):
        tx_hash, index = reference.rsplit(":", 1)
        with Session(self.engine) as s:
            deployment = s.get(ChainDeployment, self.deployment_id)
            if not deployment or self.rpc.chain_id() != deployment.chain_id:
                raise ValueError("cash reader deployment chain mismatch")
            logs = list(
                s.scalars(
                    select(ChainLog).join(ChainBlock, (
                        (ChainBlock.deployment_id == ChainLog.deployment_id)
                        & (ChainBlock.number == ChainLog.block_number)
                        & (ChainBlock.hash == ChainLog.block_hash)
                    )).where(
                        ChainLog.deployment_id == self.deployment_id,
                        ChainLog.tx_hash == tx_hash.lower(),
                        ChainLog.tier == "FINALIZED",
                        ChainLog.tx_status == 1,
                        ChainBlock.tier == "FINALIZED",
                    )
                )
            )
            repaid = next(
                (
                    l
                    for l in logs
                    if l.contract_name in _REPAYMENT_CONTRACTS
                    and l.event_name == "Repaid"
                    and l.log_index == int(index)
                ),
                None,
            )
            if not repaid:
                return None
            facility_key = repaid.decoded["facilityId"]
            binding = s.scalar(
                select(FacilityBinding).where(
                    FacilityBinding.deployment_id == self.deployment_id,
                    FacilityBinding.onchain_id == facility_key,
                )
            )
            if not binding:
                return None
            facility = s.get(Facility, binding.facility_id)
            if (
                not facility
                or facility.execution_profile != deployment.execution_profile
                or facility.loan_chain_id != deployment.chain_id
            ):
                raise ValueError("facility binding profile/chain mismatch")
            paired = pair_repayment_events(logs, deployment.contracts, repaid.log_index, facility_key)
            if paired is None:
                return None
            repaid, allocated_log, vault_log = paired
            if repaid.contract_name == "RepaymentRouter" and not _is_direct_router_transaction(
                self.rpc.get_transaction(repaid.tx_hash), repaid, deployment.contracts
            ):
                return None
            allocation, cash, repayment = (
                allocated_log.decoded,
                vault_log.decoded,
                repaid.decoded,
            )
            views = ContractViews(self.rpc, deployment.contracts)
            if (
                views.read("LendingVaultV2", "asset", [], repaid.block_number)
                != facility.loan_token_address
            ):
                raise ValueError("facility loan token differs from actual vault asset")
            if (
                cash["received"] != repayment["received"]
                or cash["applied"] != repayment["applied"]
                or cash["excess"] != repayment["excess"]
                or allocation["newDebt"] != repayment["newDebt"]
            ):
                raise ValueError("canonical repayment events disagree")
            block = s.get(ChainBlock, (deployment.deployment_id, repaid.block_number))
            actual = self.rpc.get_block(repaid.block_number)
            receipt = self.rpc.get_receipt(repaid.tx_hash)
            canonical = bool(
                actual
                and actual["hash"].lower() == repaid.block_hash
                and receipt
                and receipt["blockHash"].lower() == repaid.block_hash
                and int(receipt["status"], 16) == 1
            )
            # These amounts are explicitly emitted after measured vault custody, net of token transfer fees.
            canonical_reference = f"{repaid.tx_hash}:{repaid.log_index}"
            cash_id = stable_id(f"cash:{deployment.chain_id}:{canonical_reference}")
            asset = AssetRef(
                chain_id=facility.loan_chain_id,
                address=facility.loan_token_address,
                decimals=facility.loan_decimals,
                symbol="LOAN",
            )
            receipt_fact = ReceiptFact(
                cash_receipt_id=cash_id,
                asset=asset,
                amount=int(cash["received"]),
                tx_hash=repaid.tx_hash,
                log_index=repaid.log_index,
                block_hash=repaid.block_hash,
                block_number=repaid.block_number,
                payer_address=repayment["payer"],
                payee_address=deployment.contracts["LendingVaultV2"].lower(),
                source_kind="DIRECT_REPAYMENT",
                execution_profile=deployment.execution_profile,
                received_at=datetime.fromtimestamp(block.timestamp, UTC),
                canonical=canonical,
                finalized=True,
                receipt_status=1 if canonical else 0,
            )
            allocation_fact = AllocationFact(
                allocation_id=stable_id(f"allocation:{deployment.chain_id}:{canonical_reference}"),
                cash_receipt_id=cash_id,
                facility_id=facility.facility_id,
                received=int(cash["received"]),
                fee_paid=int(allocation["feePaid"]),
                interest_paid=int(allocation["interestPaid"]),
                principal_paid=int(allocation["principalPaid"]),
                excess=int(allocation["excess"]),
                new_debt=int(allocation["newDebt"]),
                tx_hash=repaid.tx_hash,
                chain_id=deployment.chain_id,
                execution_profile=deployment.execution_profile,
                canonical=canonical,
                finalized=True,
                receipt_status=1 if canonical else 0,
            )
            return receipt_fact, allocation_fact

    def receipt(self, reference):
        facts = self._facts(reference)
        return facts[0] if facts else None

    def allocation(self, reference):
        facts = self._facts(reference)
        return facts[1] if facts else None
