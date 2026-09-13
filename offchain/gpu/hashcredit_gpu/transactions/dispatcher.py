"""Persist signed bytes before sending; reconcile every replacement hash at finality."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.engine import Engine

from . import intents
from .abi import keccak_hex, resolve_purpose
from .nonce import allocate_nonce, lock_signer
from .rpc import JsonRpcClient, RpcError, RpcTransportError


class Signer(Protocol):
    address: str

    def sign_transaction(self, transaction: dict) -> bytes: ...


class AccountSigner:
    """Private key stays in the dedicated worker process; never stored in the database."""

    def __init__(self, key: str):
        from eth_account import Account

        self._account = Account.from_key(key)
        self.address = self._account.address.lower()

    def sign_transaction(self, transaction: dict) -> bytes:
        from eth_utils import to_checksum_address

        transaction = dict(transaction, to=to_checksum_address(transaction["to"]))
        return bytes(self._account.sign_transaction(transaction).raw_transaction)


@dataclass(frozen=True)
class DispatcherConfig:
    chain_id: int
    signer_role: str
    contracts: dict[str, str]
    max_gas: int = 3_000_000
    max_fee_per_gas: int = 100_000_000_000
    finality_depth: int = 12


class Dispatcher:
    def __init__(
        self, engine: Engine, rpc: JsonRpcClient, signer: Signer, config: DispatcherConfig
    ):
        self.engine, self.rpc, self.signer, self.config = engine, rpc, signer, config
        if config.finality_depth < 1 or config.max_gas < 21000 or config.max_fee_per_gas <= 0:
            raise ValueError("positive gas/fee bounds and finality depth required")
        if rpc.chain_id() != config.chain_id:
            raise ValueError("RPC chain differs from pinned deployment")

    def prepare(self, job_id: str, purpose: str, calldata: bytes) -> intents.Intent:
        """Idempotent semantic action. Simulation and signing happen before any broadcast."""
        p = resolve_purpose(purpose, self.config.signer_role, calldata)
        to = self.config.contracts.get(p.contract_role)
        if not to:
            raise ValueError(f"missing deployment contract {p.contract_role}")
        to = to.lower()
        with self.engine.begin() as cx:
            lock_signer(cx, self.config.chain_id, self.signer.address)
            previous = cx.execute(
                text(
                    "SELECT tx_intent_id FROM tx_intents WHERE job_id = :j ORDER BY created_at DESC LIMIT 1"
                ),
                {"j": job_id},
            ).scalar()
            if previous:
                existing = intents.get(cx, previous)
                if (existing.purpose, existing.to_address, existing.calldata_hash) != (
                    purpose,
                    to,
                    keccak_hex(calldata),
                ):
                    raise ValueError(
                        "semantic action already bound to different calldata or destination"
                    )
                return existing
            unsigned = {
                "from": self.signer.address,
                "to": to,
                "data": "0x" + calldata.hex(),
                "value": "0x0",
            }
            self.rpc.eth_call(unsigned)
            gas = (self.rpc.estimate_gas(unsigned) * 120 + 99) // 100
            price = self.rpc.gas_price()
            if gas > self.config.max_gas or price > self.config.max_fee_per_gas:
                raise ValueError("simulation exceeds configured gas or fee bound")
            nonce = allocate_nonce(
                cx,
                self.config.chain_id,
                self.signer.address,
                self.rpc.transaction_count(self.signer.address),
            )
            intent = intents.create(
                cx,
                job_id=job_id,
                chain_id=self.config.chain_id,
                signer_address=self.signer.address,
                nonce=nonce,
                purpose=purpose,
                to_address=to,
                calldata_hash=keccak_hex(calldata),
            )
            raw = self.signer.sign_transaction(
                {
                    "chainId": self.config.chain_id,
                    "nonce": nonce,
                    "to": to,
                    "data": calldata,
                    "value": 0,
                    "gas": gas,
                    "gasPrice": price,
                }
            )
            return intents.record_signed(
                cx,
                intent.tx_intent_id,
                tx_hash=keccak_hex(raw),
                raw_tx="0x" + raw.hex(),
                max_fee_per_gas=price,
                max_priority_fee_per_gas=0,
                gas_limit=gas,
                actor="dispatcher",
            )

    def broadcast(self, intent_id: str) -> intents.Intent:
        with self.engine.connect() as cx:
            current = intents.get(cx, intent_id)
            params = intents.signed_params(cx, intent_id)
        self._owns(current)
        if current.state not in (
            intents.IntentState.PENDING,
            intents.IntentState.SENT,
            intents.IntentState.ORPHANED,
        ):
            return current
        if not params or keccak_hex(bytes.fromhex(params["rawTx"][2:])) != current.tx_hash:
            raise ValueError("persisted signed bytes/hash missing or inconsistent")
        try:
            sent_hash = self.rpc.send_raw_transaction(params["rawTx"])
            if sent_hash.lower() != current.tx_hash:
                raise RpcTransportError("RPC returned a different transaction hash")
        except (RpcTransportError, RpcError):
            # No RPC error establishes non-delivery; keep watching the original signed hash.
            return current
        with self.engine.begin() as cx:
            current = intents.get(cx, intent_id, lock=True)
            if current.state in (intents.IntentState.PENDING, intents.IntentState.SENT):
                return intents.mark_sent(cx, intent_id)
            return current

    def _owns(self, current: intents.Intent) -> None:
        if (
            current.chain_id != self.config.chain_id
            or current.signer_address != self.signer.address.lower()
        ):
            raise PermissionError("intent belongs to another dispatcher credential")

    def reconcile(self, intent_id: str) -> intents.Intent:
        with self.engine.begin() as cx:
            current = intents.get(cx, intent_id, lock=True)
            self._owns(current)
            if current.state not in intents.LIVE_STATES:
                return current
            receipt = None
            for tx_hash in intents.all_hashes(cx, intent_id):
                candidate = self.rpc.get_receipt(tx_hash)
                if not candidate:
                    continue
                block = self.rpc.get_block(int(candidate["blockNumber"], 16))
                if block and block["hash"].lower() == candidate["blockHash"].lower():
                    receipt = candidate
                    break
            if receipt is None:
                if current.state == intents.IntentState.PENDING_MINED:
                    return intents.mark_orphaned(
                        cx, intent_id, reason="receipt no longer canonical"
                    )
                return current
            number, status = int(receipt["blockNumber"], 16), int(receipt["status"], 16)
            head = self.rpc.block_number()
            if status == 0 and head - number + 1 < self.config.finality_depth:
                return current
            if current.state != intents.IntentState.PENDING_MINED:
                current = intents.mark_mined(cx, intent_id, block=number, receipt_status=status)
            if status == 0:
                return current
            if head - number + 1 >= self.config.finality_depth:
                # Receipt finality is distinct from accepted native/app evidence.
                return intents.mark_final(cx, intent_id, finality_block=head)
            return current
