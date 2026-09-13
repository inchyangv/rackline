"""
Per-(chain, signer) nonce allocation under a PostgreSQL transaction-scoped advisory lock (GPU-026).

The lock is never in-memory: two dispatcher processes serialize on `pg_advisory_xact_lock(hash(chain:signer))`
for the duration of the allocating transaction, so the `UNIQUE (chain_id, signer_address, nonce)` constraint of
`tx_intents` is a backstop, not the mechanism.

next nonce = max(chain `eth_getTransactionCount(signer, "pending")`,
                 1 + highest nonce of any intent that could have consumed its nonce)
An intent that was abandoned before it was ever broadcast (FAILED, tx_hash NULL) does not hold its nonce: the
EVM requires nonces to be sequential, so skipping it would wedge the signer. `intents.create` re-issues such a
row (audited `TX_NONCE_REISSUED`) instead of inserting a second row for the same nonce.
"""

from __future__ import annotations

import hashlib

from sqlalchemy import text
from sqlalchemy.engine import Connection


def lock_key(chain_id: int, signer_address: str) -> int:
    """Stable 63-bit advisory lock key for (chain, signer)."""
    h = hashlib.sha256(f"{chain_id}:{signer_address.lower()}".encode()).digest()
    return int.from_bytes(h[:8], "big") & 0x7FFF_FFFF_FFFF_FFFF


def lock_signer(cx: Connection, chain_id: int, signer_address: str) -> None:
    """Take the transaction-scoped advisory lock; released automatically at commit/rollback."""
    cx.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": lock_key(chain_id, signer_address)})


def highest_holding_nonce(cx: Connection, chain_id: int, signer_address: str) -> int | None:
    """Highest nonce of an intent that holds (or may have consumed) its nonce slot."""
    v = cx.execute(
        text(
            "SELECT max(nonce) FROM tx_intents WHERE chain_id = :c AND signer_address = :s "
            "AND NOT (state = 'FAILED' AND tx_hash IS NULL)"
        ),
        {"c": chain_id, "s": signer_address.lower()},
    ).scalar()
    return None if v is None else int(v)


def allocate_nonce(
    cx: Connection, chain_id: int, signer_address: str, chain_pending_count: int
) -> int:
    """Must be called after `lock_signer` inside the same transaction that inserts the intent."""
    recorded = highest_holding_nonce(cx, chain_id, signer_address)
    db_next = 0 if recorded is None else recorded + 1
    return max(db_next, int(chain_pending_count))
