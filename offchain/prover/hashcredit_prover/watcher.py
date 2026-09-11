"""
Bitcoin address watcher for SPV relayer.

Monitors Bitcoin addresses for incoming transactions and
triggers proof generation/submission when confirmations are met.

Supports both SQLite (local) and PostgreSQL (production) via DATABASE_URL.
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import List, Optional, Union
from urllib.parse import urlparse

import structlog
from sqlalchemy import (
    Column,
    DateTime,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    select,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Engine

from .rpc import BitcoinRPC, BitcoinRPCConfig

logger = structlog.get_logger()

# Constants for BTC to satoshis conversion
SATS_PER_BTC = Decimal("100000000")

# SQLAlchemy metadata
metadata = MetaData()

# Table definitions
pending_payouts_table = Table(
    "pending_payouts",
    metadata,
    Column("txid", String(64), nullable=False, primary_key=True),
    Column("output_index", Integer, nullable=False, primary_key=True),
    Column("borrower", String(42), nullable=False),
    Column("btc_address", String(100), nullable=False),
    Column("amount_sats", Integer, nullable=False),
    Column("block_height", Integer, nullable=False),
    Column("block_hash", String(64), nullable=False),
    Column("first_seen", DateTime, nullable=False),
    Index("idx_pending_borrower", "borrower"),
)

submitted_payouts_table = Table(
    "submitted_payouts",
    metadata,
    Column("txid", String(64), nullable=False, primary_key=True),
    Column("output_index", Integer, nullable=False, primary_key=True),
    Column("borrower", String(42), nullable=False),
    Column("amount_sats", Integer, nullable=False),
    Column("block_height", Integer, nullable=False),
    Column("submitted_at", DateTime, nullable=False),
    Column("evm_tx_hash", String(66), nullable=False),
    Index("idx_submitted_borrower", "borrower"),
)


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


def parse_database_url(url: str) -> str:
    """
    Parse and normalize database URL.

    Handles:
    - sqlite:///path/to/db.db (or just file path)
    - postgresql://user:pass@host:port/db
    - postgres://... (Railway format, converted to postgresql://)
    """
    # Handle plain file paths for backwards compatibility
    if not url.startswith(("sqlite://", "postgresql://", "postgres://")):
        return f"sqlite:///{url}"

    if url.startswith("postgres://"):
        # Railway uses postgres:// but SQLAlchemy requires postgresql://
        url = url.replace("postgres://", "postgresql://", 1)
    return url


class PayoutStore:
    """
    Store for tracking payout transactions.

    Supports SQLite (local) and PostgreSQL (production) via database URL.

    Tracks:
    - Pending payouts waiting for confirmations
    - Submitted payouts (to prevent double-submission)
    """

    def __init__(self, database_url: str = "sqlite:///./spv_relayer.db"):
        """
        Initialize database connection.

        Args:
            database_url: SQLAlchemy database URL or file path (backwards compatible)
        """
        self.database_url = parse_database_url(database_url)
        self._engine: Optional[Engine] = None
        self._is_postgres = self.database_url.startswith("postgresql://")
        self._init_db()

    def _get_engine(self) -> Engine:
        """Get or create database engine."""
        if self._engine is None:
            connect_args = {}
            if self.database_url.startswith("sqlite://"):
                connect_args["check_same_thread"] = False

            self._engine = create_engine(
                self.database_url,
                connect_args=connect_args,
                pool_pre_ping=True,
            )
        return self._engine

    def _mask_url(self, url: str) -> str:
        """Mask password in URL for logging."""
        parsed = urlparse(url)
        if parsed.password:
            return url.replace(parsed.password, "***")
        return url

    def _init_db(self) -> None:
        """Initialize database schema."""
        engine = self._get_engine()
        metadata.create_all(engine)
        logger.info(
            "payout_store_initialized",
            url=self._mask_url(self.database_url),
            backend="postgresql" if self._is_postgres else "sqlite",
        )

    def close(self) -> None:
        """Close database connection."""
        if self._engine:
            self._engine.dispose()
            self._engine = None

    def add_pending(self, payout: PendingPayout) -> bool:
        """
        Add a pending payout. Returns False if already exists.
        """
        engine = self._get_engine()
        with engine.begin() as conn:
            if self._is_postgres:
                # PostgreSQL: use ON CONFLICT DO NOTHING
                stmt = pg_insert(pending_payouts_table).values(
                    txid=payout.txid,
                    output_index=payout.output_index,
                    borrower=payout.borrower,
                    btc_address=payout.btc_address,
                    amount_sats=payout.amount_sats,
                    block_height=payout.block_height,
                    block_hash=payout.block_hash,
                    first_seen=payout.first_seen,
                ).on_conflict_do_nothing()
                result = conn.execute(stmt)
                return result.rowcount > 0
            else:
                # SQLite: use INSERT OR IGNORE
                stmt = pending_payouts_table.insert().prefix_with("OR IGNORE").values(
                    txid=payout.txid,
                    output_index=payout.output_index,
                    borrower=payout.borrower,
                    btc_address=payout.btc_address,
                    amount_sats=payout.amount_sats,
                    block_height=payout.block_height,
                    block_hash=payout.block_hash,
                    first_seen=payout.first_seen,
                )
                result = conn.execute(stmt)
                return result.rowcount > 0

    def get_pending(self) -> List[PendingPayout]:
        """Get all pending payouts."""
        engine = self._get_engine()
        with engine.connect() as conn:
            result = conn.execute(select(pending_payouts_table)).fetchall()
            return [
                PendingPayout(
                    txid=row.txid,
                    output_index=row.output_index,
                    borrower=row.borrower,
                    btc_address=row.btc_address,
                    amount_sats=row.amount_sats,
                    block_height=row.block_height,
                    block_hash=row.block_hash,
                    first_seen=row.first_seen,
                )
                for row in result
            ]

    def mark_submitted(
        self, txid: str, output_index: int, evm_tx_hash: str
    ) -> None:
        """Move payout from pending to submitted."""
        engine = self._get_engine()
        with engine.begin() as conn:
            # Get pending payout
            stmt = select(pending_payouts_table).where(
                pending_payouts_table.c.txid == txid,
                pending_payouts_table.c.output_index == output_index,
            )
            row = conn.execute(stmt).fetchone()

            if row:
                # Insert into submitted
                insert_stmt = submitted_payouts_table.insert().values(
                    txid=txid,
                    output_index=output_index,
                    borrower=row.borrower,
                    amount_sats=row.amount_sats,
                    block_height=row.block_height,
                    submitted_at=datetime.utcnow(),
                    evm_tx_hash=evm_tx_hash,
                )
                conn.execute(insert_stmt)

                # Remove from pending
                delete_stmt = pending_payouts_table.delete().where(
                    pending_payouts_table.c.txid == txid,
                    pending_payouts_table.c.output_index == output_index,
                )
                conn.execute(delete_stmt)

    def is_submitted(self, txid: str, output_index: int) -> bool:
        """Check if payout was already submitted."""
        engine = self._get_engine()
        with engine.connect() as conn:
            stmt = select(submitted_payouts_table.c.txid).where(
                submitted_payouts_table.c.txid == txid,
                submitted_payouts_table.c.output_index == output_index,
            )
            return conn.execute(stmt).fetchone() is not None

    def remove_pending(self, txid: str, output_index: int) -> None:
        """Remove a pending payout (e.g., if block was orphaned)."""
        engine = self._get_engine()
        with engine.begin() as conn:
            stmt = pending_payouts_table.delete().where(
                pending_payouts_table.c.txid == txid,
                pending_payouts_table.c.output_index == output_index,
            )
            conn.execute(stmt)


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
