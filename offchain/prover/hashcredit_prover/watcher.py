"""
Bitcoin address watcher for SPV relayer.

Monitors Bitcoin addresses for incoming transactions and
triggers proof generation/submission when confirmations are met.
"""

import asyncio
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import List, Optional, Union
import structlog

from .rpc import BitcoinRPC, BitcoinRPCConfig

logger = structlog.get_logger()

# Constants for BTC to satoshis conversion
SATS_PER_BTC = Decimal("100000000")


def btc_to_sats(value: Union[int, float, str, Decimal]) -> int:
    """
    Convert BTC value to satoshis with exact precision.

    Uses Decimal arithmetic to avoid float precision issues.
    Bitcoin Core RPC may return value as float (e.g., 0.1) but
    float(0.1) * 1e8 = 9999999.999999998, not 10000000.

    Args:
        value: BTC amount as int, float, str, or Decimal

    Returns:
        Exact satoshi amount as integer

    Examples:
        >>> btc_to_sats(0.1)
        10000000
        >>> btc_to_sats(0.00000001)
        1
        >>> btc_to_sats("0.12345678")
        12345678
    """
    # Convert to string first to preserve precision from float
    # Then convert to Decimal for exact arithmetic
    if isinstance(value, Decimal):
        dec_value = value
    elif isinstance(value, str):
        dec_value = Decimal(value)
    else:
        # int or float: convert via string to avoid float representation issues
        dec_value = Decimal(str(value))

    sats = dec_value * SATS_PER_BTC

    # Ensure exact integer (no fractional satoshis)
    if sats != sats.to_integral_value():
        raise ValueError(f"BTC value {value} results in fractional satoshis: {sats}")

    return int(sats)


@dataclass
class WatchedAddress:
    """Configuration for a watched Bitcoin address."""

    btc_address: str  # Bitcoin address (display format)
    borrower: str  # EVM borrower address
    enabled: bool = True


@dataclass
class PendingPayout:
    """A payout transaction waiting for confirmations."""

    txid: str  # Transaction ID (display format)
    output_index: int
    borrower: str  # EVM borrower address
    btc_address: str  # Bitcoin address
    amount_sats: int
    block_height: int
    block_hash: str
    first_seen: datetime
    confirmations: int = 0


class PayoutStore:
    """
    SQLite store for tracking payout transactions.

    Tracks:
    - Pending payouts waiting for confirmations
    - Submitted payouts (to prevent double-submission)
    """

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database schema."""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS pending_payouts (
                    txid TEXT NOT NULL,
                    output_index INTEGER NOT NULL,
                    borrower TEXT NOT NULL,
                    btc_address TEXT NOT NULL,
                    amount_sats INTEGER NOT NULL,
                    block_height INTEGER NOT NULL,
                    block_hash TEXT NOT NULL,
                    first_seen TEXT NOT NULL,
                    PRIMARY KEY (txid, output_index)
                );

                CREATE TABLE IF NOT EXISTS submitted_payouts (
                    txid TEXT NOT NULL,
                    output_index INTEGER NOT NULL,
                    borrower TEXT NOT NULL,
                    amount_sats INTEGER NOT NULL,
                    block_height INTEGER NOT NULL,
                    submitted_at TEXT NOT NULL,
                    evm_tx_hash TEXT NOT NULL,
                    PRIMARY KEY (txid, output_index)
                );

                CREATE INDEX IF NOT EXISTS idx_pending_borrower
                ON pending_payouts(borrower);

                CREATE INDEX IF NOT EXISTS idx_submitted_borrower
                ON submitted_payouts(borrower);
            """)
            conn.commit()
        finally:
            conn.close()

    def add_pending(self, payout: PendingPayout) -> bool:
        """
        Add a pending payout. Returns False if already exists.
        """
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                """
                INSERT OR IGNORE INTO pending_payouts
                (txid, output_index, borrower, btc_address, amount_sats,
                 block_height, block_hash, first_seen)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payout.txid,
                    payout.output_index,
                    payout.borrower,
                    payout.btc_address,
                    payout.amount_sats,
                    payout.block_height,
                    payout.block_hash,
                    payout.first_seen.isoformat(),
                ),
            )
            conn.commit()
            return conn.total_changes > 0
        finally:
            conn.close()

    def get_pending(self) -> List[PendingPayout]:
        """Get all pending payouts."""
        conn = sqlite3.connect(self.db_path)
        try:
            rows = conn.execute(
                """
                SELECT txid, output_index, borrower, btc_address, amount_sats,
                       block_height, block_hash, first_seen
                FROM pending_payouts
                """
            ).fetchall()
            return [
                PendingPayout(
                    txid=row[0],
                    output_index=row[1],
                    borrower=row[2],
                    btc_address=row[3],
                    amount_sats=row[4],
                    block_height=row[5],
                    block_hash=row[6],
                    first_seen=datetime.fromisoformat(row[7]),
                )
                for row in rows
            ]
        finally:
            conn.close()

    def mark_submitted(
        self, txid: str, output_index: int, evm_tx_hash: str
    ) -> None:
        """Move payout from pending to submitted."""
        conn = sqlite3.connect(self.db_path)
        try:
            # Get pending payout
            row = conn.execute(
                """
                SELECT borrower, amount_sats, block_height
                FROM pending_payouts
                WHERE txid = ? AND output_index = ?
                """,
                (txid, output_index),
            ).fetchone()

            if row:
                # Insert into submitted
                conn.execute(
                    """
                    INSERT INTO submitted_payouts
                    (txid, output_index, borrower, amount_sats, block_height,
                     submitted_at, evm_tx_hash)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        txid,
                        output_index,
                        row[0],
                        row[1],
                        row[2],
                        datetime.now().isoformat(),
                        evm_tx_hash,
                    ),
                )

                # Remove from pending
                conn.execute(
                    "DELETE FROM pending_payouts WHERE txid = ? AND output_index = ?",
                    (txid, output_index),
                )

                conn.commit()
        finally:
            conn.close()

    def is_submitted(self, txid: str, output_index: int) -> bool:
        """Check if payout was already submitted."""
        conn = sqlite3.connect(self.db_path)
        try:
            row = conn.execute(
                """
                SELECT 1 FROM submitted_payouts
                WHERE txid = ? AND output_index = ?
                """,
                (txid, output_index),
            ).fetchone()
            return row is not None
        finally:
            conn.close()

    def remove_pending(self, txid: str, output_index: int) -> None:
        """Remove a pending payout (e.g., if block was orphaned)."""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                "DELETE FROM pending_payouts WHERE txid = ? AND output_index = ?",
                (txid, output_index),
            )
            conn.commit()
        finally:
            conn.close()


class AddressWatcher:
    """
    Watches Bitcoin addresses for incoming transactions.

    Uses Bitcoin Core RPC to scan recent blocks for transactions
    paying to watched addresses.
    """

    def __init__(
        self,
        rpc: BitcoinRPC,
        addresses: List[WatchedAddress],
        store: PayoutStore,
    ):
        self.rpc = rpc
        self.addresses = {a.btc_address: a for a in addresses if a.enabled}
        self.store = store
        self._last_scanned_height: Optional[int] = None

    async def scan_block(self, height: int) -> List[PendingPayout]:
        """
        Scan a block for transactions to watched addresses.

        Returns list of new pending payouts found.
        """
        from .bitcoin import parse_tx_outputs, extract_pubkey_hash
        from .address import decode_btc_address

        block_hash = await self.rpc.get_block_hash(height)
        block = await self.rpc.get_block(block_hash, verbosity=2)

        new_payouts: List[PendingPayout] = []

        # Build pubkey hash to address mapping
        pubkey_hash_to_addr: dict[bytes, WatchedAddress] = {}
        for addr in self.addresses.values():
            result = decode_btc_address(addr.btc_address)
            if result:
                pubkey_hash, _ = result
                pubkey_hash_to_addr[pubkey_hash] = addr

        for tx in block.get("tx", []):
            txid = tx["txid"]

            # Skip if already processed
            for vout_data in tx.get("vout", []):
                vout_idx = vout_data["n"]

                if self.store.is_submitted(txid, vout_idx):
                    continue

                # Get scriptPubKey
                script_pubkey_hex = vout_data.get("scriptPubKey", {}).get("hex", "")
                if not script_pubkey_hex:
                    continue

                script_pubkey = bytes.fromhex(script_pubkey_hex)
                pubkey_hash, script_type = extract_pubkey_hash(script_pubkey)

                if pubkey_hash is None:
                    continue

                # Check if this is a watched address
                if pubkey_hash not in pubkey_hash_to_addr:
                    continue

                watched = pubkey_hash_to_addr[pubkey_hash]
                amount_sats = btc_to_sats(vout_data["value"])

                payout = PendingPayout(
                    txid=txid,
                    output_index=vout_idx,
                    borrower=watched.borrower,
                    btc_address=watched.btc_address,
                    amount_sats=amount_sats,
                    block_height=height,
                    block_hash=block_hash,
                    first_seen=datetime.now(),
                )

                if self.store.add_pending(payout):
                    new_payouts.append(payout)
                    logger.info(
                        "Found new payout",
                        txid=txid,
                        vout=vout_idx,
                        borrower=watched.borrower,
                        amount_sats=amount_sats,
                    )

        return new_payouts

    async def scan_range(
        self, start_height: int, end_height: int
    ) -> List[PendingPayout]:
        """Scan a range of blocks."""
        all_payouts: List[PendingPayout] = []
        for height in range(start_height, end_height + 1):
            payouts = await self.scan_block(height)
            all_payouts.extend(payouts)
            self._last_scanned_height = height
        return all_payouts

    async def get_current_height(self) -> int:
        """Get current blockchain height."""
        return await self.rpc.get_block_count()
