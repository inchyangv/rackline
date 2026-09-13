"""
Transaction intents over `tx_intents` (migration 0002): the *semantic action* (a job with a semantic
idempotency key) is separate from the *transaction hash* (one intent per attempt/replacement).

App state           DB `tx_intents.state`   meaning
PENDING             PREPARED                nonce allocated; may be signed (tx_hash set); broadcast outcome unknown
SENT                SENT                    broadcast acknowledged or seen in the mempool
PENDING_MINED       MINED                   receipt seen (status 1), waiting for finality depth
FINALIZED           FINAL                   finality depth reached; mined_block/finality_block recorded
REPLACED            REPLACED                superseded by a same-nonce replacement intent
REVERTED            FAILED (tx_hash set)    mined with receipt status 0 — a business failure, nonce consumed
ABANDONED           FAILED (tx_hash NULL)   never broadcast; abandoned explicitly with actor + reason (audited)
ORPHANED            ORPHANED                previously mined block reorged away; re-observed, never re-sent
                                            with a new nonce while the old could still mine

A timeout after `eth_sendRawTransaction` never changes the state to FAILED: the intent stays PENDING/SENT with
its hash and the reconciler decides from chain facts (receipt / nonce consumption).

Per-intent signing parameters (raw signed tx, fees, gas) are kept in the append-only `audit_log`
(action `TX_SIGNED`, entity `tx_intents`) because `tx_intents` has no params column (schema gap, GPU-026 record);
they are public data once broadcast and are what makes a *re-broadcast of the same hash* possible.
"""

from __future__ import annotations

import enum
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ..domain import enums as E
from ..jobs.queue import new_ulid, write_audit


class IntentState(enum.StrEnum):
    PENDING = "PREPARED"
    SENT = "SENT"
    PENDING_MINED = "MINED"
    FINALIZED = "FINAL"
    REPLACED = "REPLACED"
    FAILED = "FAILED"  # REVERTED (tx_hash set) or ABANDONED (tx_hash NULL)
    ORPHANED = "ORPHANED"


LIVE_STATES = (
    IntentState.PENDING,
    IntentState.SENT,
    IntentState.PENDING_MINED,
    IntentState.ORPHANED,
)

_TRANSITIONS: dict[IntentState, frozenset[IntentState]] = {
    IntentState.PENDING: frozenset(
        {IntentState.SENT, IntentState.PENDING_MINED, IntentState.REPLACED, IntentState.FAILED}
    ),
    IntentState.SENT: frozenset(
        {IntentState.PENDING_MINED, IntentState.REPLACED, IntentState.FAILED}
    ),
    IntentState.PENDING_MINED: frozenset({IntentState.FINALIZED, IntentState.ORPHANED}),
    IntentState.ORPHANED: frozenset(
        {IntentState.PENDING_MINED, IntentState.REPLACED, IntentState.FAILED}
    ),
    IntentState.FINALIZED: frozenset(),
    IntentState.REPLACED: frozenset(),
    IntentState.FAILED: frozenset(),
}


class IllegalIntentTransition(RuntimeError):
    pass


@dataclass(frozen=True)
class Intent:
    tx_intent_id: str
    job_id: str | None
    chain_id: int
    signer_address: str
    nonce: int
    purpose: str
    to_address: str
    calldata_hash: str
    tx_hash: str | None
    state: IntentState
    replaces_tx_intent_id: str | None
    mined_block: int | None
    finality_block: int | None
    last_error: str | None
    updated_at: datetime

    @property
    def app_state(self) -> str:
        if self.state == IntentState.FAILED:
            return "ABANDONED" if (self.last_error or "").startswith("ABANDONED") else "REVERTED"
        return IntentState(self.state).name


_COLS = (
    "tx_intent_id, job_id, chain_id, signer_address, nonce, purpose, to_address, calldata_hash, tx_hash, state, "
    "replaces_tx_intent_id, mined_block, finality_block, last_error, updated_at"
)


def _row(r: Any) -> Intent:
    return Intent(
        tx_intent_id=r.tx_intent_id,
        job_id=r.job_id,
        chain_id=int(r.chain_id),
        signer_address=r.signer_address,
        nonce=int(r.nonce),
        purpose=r.purpose,
        to_address=r.to_address,
        calldata_hash=r.calldata_hash,
        tx_hash=r.tx_hash,
        state=IntentState(r.state),
        replaces_tx_intent_id=r.replaces_tx_intent_id,
        mined_block=r.mined_block,
        finality_block=r.finality_block,
        last_error=r.last_error,
        updated_at=r.updated_at,
    )


def get(cx: Connection, tx_intent_id: str, *, lock: bool = False) -> Intent:
    r = cx.execute(
        text(
            f"SELECT {_COLS} FROM tx_intents WHERE tx_intent_id = :id"
            + (" FOR UPDATE" if lock else "")
        ),
        {"id": tx_intent_id},
    ).one()
    return _row(r)


def live_for_job(cx: Connection, job_id: str) -> Intent | None:
    """The one intent of a semantic action that can still mine (PENDING/SENT/PENDING_MINED/ORPHANED)."""
    r = cx.execute(
        text(
            f"SELECT {_COLS} FROM tx_intents WHERE job_id = :j AND state = ANY(:live) ORDER BY nonce DESC, created_at DESC LIMIT 1"
        ),
        {"j": job_id, "live": [s.value for s in LIVE_STATES]},
    ).first()
    return _row(r) if r else None


def by_hash(cx: Connection, tx_hash: str) -> Intent | None:
    r = cx.execute(
        text(f"SELECT {_COLS} FROM tx_intents WHERE tx_hash = :h"), {"h": tx_hash}
    ).first()
    return _row(r) if r else None


def list_live(cx: Connection, chain_id: int, signer_address: str) -> list[Intent]:
    rows = cx.execute(
        text(
            f"SELECT {_COLS} FROM tx_intents WHERE chain_id = :c AND signer_address = :s AND state = ANY(:live) ORDER BY nonce"
        ),
        {"c": chain_id, "s": signer_address.lower(), "live": [s.value for s in LIVE_STATES]},
    ).all()
    return [_row(r) for r in rows]


def create(
    cx: Connection,
    *,
    job_id: str | None,
    chain_id: int,
    signer_address: str,
    nonce: int,
    purpose: str,
    to_address: str,
    calldata_hash: str,
    replaces: str | None = None,
) -> Intent:
    # an abandoned, never-broadcast row at this nonce is re-issued (the EVM needs sequential nonces)
    stale = cx.execute(
        text(
            "SELECT tx_intent_id, job_id, purpose, to_address, calldata_hash, last_error FROM tx_intents "
            "WHERE chain_id = :c AND signer_address = :s AND nonce = :n AND state = 'FAILED' AND tx_hash IS NULL FOR UPDATE"
        ),
        {"c": chain_id, "s": signer_address.lower(), "n": nonce},
    ).first()
    if stale is not None:
        cx.execute(
            text(
                "UPDATE tx_intents SET job_id = :job, purpose = :purpose, to_address = :to, calldata_hash = :cd, state = 'PREPARED', "
                "last_error = NULL, replaces_tx_intent_id = :rep, updated_at = now() WHERE tx_intent_id = :id"
            ),
            {
                "job": job_id,
                "purpose": purpose,
                "to": to_address.lower(),
                "cd": calldata_hash,
                "rep": replaces,
                "id": stale.tx_intent_id,
            },
        )
        write_audit(
            cx,
            actor="dispatcher",
            actor_role=E.Role.SYSTEM,
            action="TX_NONCE_REISSUED",
            entity_table="tx_intents",
            entity_id=stale.tx_intent_id,
            before={
                "jobId": stale.job_id,
                "purpose": stale.purpose,
                "to": stale.to_address,
                "calldataHash": stale.calldata_hash,
                "lastError": stale.last_error,
            },
            after={
                "jobId": job_id,
                "purpose": purpose,
                "to": to_address.lower(),
                "calldataHash": calldata_hash,
                "nonce": nonce,
            },
            correlation_id=job_id,
        )
        return get(cx, stale.tx_intent_id)
    tid = new_ulid()
    cx.execute(
        text(
            "INSERT INTO tx_intents (tx_intent_id, job_id, chain_id, signer_address, nonce, purpose, to_address, calldata_hash, state, replaces_tx_intent_id) "
            "VALUES (:id, :job, :chain, :signer, :nonce, :purpose, :to, :cd, 'PREPARED', :rep)"
        ),
        {
            "id": tid,
            "job": job_id,
            "chain": chain_id,
            "signer": signer_address.lower(),
            "nonce": nonce,
            "purpose": purpose,
            "to": to_address.lower(),
            "cd": calldata_hash,
            "rep": replaces,
        },
    )
    return get(cx, tid)


def _transition(
    cx: Connection, tx_intent_id: str, to: IntentState, set_sql: str, params: dict[str, Any]
) -> Intent:
    cur = get(cx, tx_intent_id, lock=True)
    if to != cur.state and to not in _TRANSITIONS[cur.state]:
        raise IllegalIntentTransition(
            f"{cur.app_state} -> {to.name} not allowed for intent {tx_intent_id}"
        )
    cx.execute(
        text(
            f"UPDATE tx_intents SET state = :st, {set_sql}, updated_at = now() WHERE tx_intent_id = :id"
        ),
        {"st": to.value, "id": tx_intent_id, **params},
    )
    return get(cx, tx_intent_id)


def record_signed(
    cx: Connection,
    tx_intent_id: str,
    *,
    tx_hash: str,
    raw_tx: str,
    max_fee_per_gas: int,
    max_priority_fee_per_gas: int,
    gas_limit: int,
    actor: str,
) -> Intent:
    """Persist the hash **before** broadcasting (crash after send can always be reconciled by hash/nonce)."""
    cur = get(cx, tx_intent_id, lock=True)
    if cur.state != IntentState.PENDING:
        raise IllegalIntentTransition(f"cannot sign an intent in state {cur.app_state}")
    if cur.tx_hash is not None and cur.tx_hash != tx_hash:
        raise IllegalIntentTransition("intent already signed with a different hash")
    cx.execute(
        text("UPDATE tx_intents SET tx_hash = :h, updated_at = now() WHERE tx_intent_id = :id"),
        {"h": tx_hash, "id": tx_intent_id},
    )
    write_audit(
        cx,
        actor=actor,
        actor_role=E.Role.SYSTEM,
        action="TX_SIGNED",
        entity_table="tx_intents",
        entity_id=tx_intent_id,
        before=None,
        after={
            "txHash": tx_hash,
            "rawTx": raw_tx,
            "maxFeePerGas": str(max_fee_per_gas),
            "maxPriorityFeePerGas": str(max_priority_fee_per_gas),
            "gasLimit": str(gas_limit),
            "nonce": cur.nonce,
        },
        correlation_id=cur.job_id,
    )
    return get(cx, tx_intent_id)


def record_fee_bump(
    cx: Connection,
    tx_intent_id: str,
    *,
    new_tx_hash: str,
    raw_tx: str,
    max_fee_per_gas: int,
    max_priority_fee_per_gas: int,
    gas_limit: int,
    actor: str,
) -> Intent:
    """Same-nonce replacement with a higher fee. `tx_intents` has one row per nonce (UNIQUE chain/signer/nonce),
    so the row keeps the nonce and takes the new hash; the superseded hash stays in `audit_log` (TX_REPLACED_FEE)
    and the reconciler keeps watching every hash of the nonce because any of them may still mine."""
    cur = get(cx, tx_intent_id, lock=True)
    if cur.state not in (IntentState.PENDING, IntentState.SENT) or cur.tx_hash is None:
        raise IllegalIntentTransition(f"cannot fee-bump an intent in state {cur.app_state}")
    prev = signed_params(cx, tx_intent_id) or {}
    if int(prev.get("maxFeePerGas", "0")) >= max_fee_per_gas:
        raise IllegalIntentTransition("replacement must raise maxFeePerGas")
    cx.execute(
        text(
            "UPDATE tx_intents SET tx_hash = :h, state = 'PREPARED', updated_at = now() WHERE tx_intent_id = :id"
        ),
        {"h": new_tx_hash, "id": tx_intent_id},
    )
    write_audit(
        cx,
        actor=actor,
        actor_role=E.Role.SYSTEM,
        action="TX_REPLACED_FEE",
        entity_table="tx_intents",
        entity_id=tx_intent_id,
        before={"txHash": cur.tx_hash, "maxFeePerGas": prev.get("maxFeePerGas")},
        after={"txHash": new_tx_hash, "replacedHash": cur.tx_hash, "state": "REPLACED_FEE"},
        correlation_id=cur.job_id,
    )
    write_audit(
        cx,
        actor=actor,
        actor_role=E.Role.SYSTEM,
        action="TX_SIGNED",
        entity_table="tx_intents",
        entity_id=tx_intent_id,
        before=None,
        after={
            "txHash": new_tx_hash,
            "rawTx": raw_tx,
            "maxFeePerGas": str(max_fee_per_gas),
            "maxPriorityFeePerGas": str(max_priority_fee_per_gas),
            "gasLimit": str(gas_limit),
            "nonce": cur.nonce,
        },
        correlation_id=cur.job_id,
    )
    return get(cx, tx_intent_id)


def all_hashes(cx: Connection, tx_intent_id: str) -> list[str]:
    """Every hash ever signed for this nonce slot (current + superseded), newest first."""
    rows = cx.execute(
        text(
            "SELECT after->>'txHash' AS h FROM audit_log WHERE entity_table = 'tx_intents' AND entity_id = :id AND action = 'TX_SIGNED' "
            "ORDER BY id DESC"
        ),
        {"id": tx_intent_id},
    ).all()
    seen: list[str] = []
    for r in rows:
        if r.h and r.h not in seen:
            seen.append(r.h)
    return seen


def replaced_hashes(cx: Connection, tx_intent_id: str) -> list[str]:
    cur = get(cx, tx_intent_id)
    return [h for h in all_hashes(cx, tx_intent_id) if h != cur.tx_hash]


def signed_params(cx: Connection, tx_intent_id: str) -> dict[str, Any] | None:
    r = cx.execute(
        text(
            "SELECT after FROM audit_log WHERE entity_table = 'tx_intents' AND entity_id = :id AND action = 'TX_SIGNED' "
            "ORDER BY id DESC LIMIT 1"
        ),
        {"id": tx_intent_id},
    ).first()
    if not r:
        return None
    return dict(r.after) if isinstance(r.after, dict) else json.loads(r.after)


def mark_sent(cx: Connection, tx_intent_id: str) -> Intent:
    return _transition(cx, tx_intent_id, IntentState.SENT, "last_error = NULL", {})


def mark_mined(cx: Connection, tx_intent_id: str, *, block: int, receipt_status: int) -> Intent:
    if receipt_status == 1:
        return _transition(
            cx,
            tx_intent_id,
            IntentState.PENDING_MINED,
            "mined_block = :b, last_error = NULL",
            {"b": block},
        )
    return _transition(
        cx,
        tx_intent_id,
        IntentState.FAILED,
        "mined_block = :b, last_error = :e",
        {"b": block, "e": f"REVERTED: receipt status 0 at block {block}"},
    )


def mark_final(cx: Connection, tx_intent_id: str, *, finality_block: int) -> Intent:
    return _transition(
        cx, tx_intent_id, IntentState.FINALIZED, "finality_block = :f", {"f": finality_block}
    )


def mark_orphaned(cx: Connection, tx_intent_id: str, *, reason: str) -> Intent:
    return _transition(
        cx,
        tx_intent_id,
        IntentState.ORPHANED,
        "mined_block = NULL, last_error = :e",
        {"e": f"ORPHANED: {reason}"},
    )


def mark_replaced(cx: Connection, tx_intent_id: str, *, by_tx_intent_id: str) -> Intent:
    return _transition(
        cx,
        tx_intent_id,
        IntentState.REPLACED,
        "last_error = :e",
        {"e": f"REPLACED by {by_tx_intent_id}"},
    )


def abandon(
    cx: Connection, tx_intent_id: str, *, actor: str, actor_role: E.Role | str, reason: str
) -> Intent:
    """Explicit, audited abandonment of an intent that was never broadcast (tx_hash NULL) or provably cannot mine."""
    if not reason.strip():
        raise ValueError("abandon requires a reason")
    cur = get(cx, tx_intent_id, lock=True)
    if cur.tx_hash is not None:
        raise IllegalIntentTransition(
            "signed transaction cannot be abandoned while it may still mine"
        )
    out = _transition(
        cx, tx_intent_id, IntentState.FAILED, "last_error = :e", {"e": f"ABANDONED: {reason}"}
    )
    write_audit(
        cx,
        actor=actor,
        actor_role=actor_role,
        action="TX_ABANDONED",
        entity_table="tx_intents",
        entity_id=tx_intent_id,
        before={"state": cur.app_state, "txHash": cur.tx_hash},
        after={"state": "ABANDONED", "reason": reason},
        correlation_id=cur.job_id,
    )
    return out
