"""
Database for payout deduplication.

Supports both SQLite (local development) and PostgreSQL (production/Railway).
Use DATABASE_URL environment variable to configure:
- SQLite: sqlite:///./relayer.db
- PostgreSQL: postgresql://user:pass@host:5432/dbname
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional
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
    UniqueConstraint,
    create_engine,
    select,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Engine

logger = structlog.get_logger()

# SQLAlchemy metadata
metadata = MetaData()

# Table definition - compatible with both SQLite and PostgreSQL
processed_payouts = Table(
    "processed_payouts",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("txid", String(64), nullable=False),
    Column("vout", Integer, nullable=False),
    Column("borrower", String(42), nullable=False),
    Column("amount_sats", Integer, nullable=False),
    Column("block_height", Integer, nullable=False),
    Column("submitted_at", DateTime, default=datetime.utcnow),
    Column("tx_hash", String(66), nullable=True),
    Column("status", String(20), default="pending"),
    UniqueConstraint("txid", "vout", name="uq_txid_vout"),
    Index("idx_txid_vout", "txid", "vout"),
    Index("idx_status", "status"),
)


@dataclass
class ProcessedPayout:
    """Record of a processed payout."""

    txid: str
    vout: int
    borrower: str
    amount_sats: int
    block_height: int
    submitted_at: datetime
    tx_hash: Optional[str]
    status: str  # "pending", "confirmed", "failed"


def parse_database_url(url: str) -> str:
    """
    Parse and normalize database URL.

    Handles:
    - sqlite:///path/to/db.db
    - postgresql://user:pass@host:port/db
    - postgres://... (Railway format, converted to postgresql://)
    """
    if url.startswith("postgres://"):
        # Railway uses postgres:// but SQLAlchemy requires postgresql://
        url = url.replace("postgres://", "postgresql://", 1)
    return url


class PayoutDatabase:
    """
    Database for tracking processed payouts.

    Supports SQLite (default) and PostgreSQL via DATABASE_URL.
    """

    def __init__(self, database_url: str = "sqlite:///./relayer.db"):
        """
        Initialize database connection.

        Args:
            database_url: SQLAlchemy database URL.
                          Default: sqlite:///./relayer.db
        """
        self.database_url = parse_database_url(database_url)
        self._engine: Optional[Engine] = None
        self._is_postgres = self.database_url.startswith("postgresql://")
        self._init_db()

    def _get_engine(self) -> Engine:
        """Get or create database engine."""
        if self._engine is None:
            # SQLite needs check_same_thread=False for multi-threaded use
            connect_args = {}
            if self.database_url.startswith("sqlite://"):
                connect_args["check_same_thread"] = False

            self._engine = create_engine(
                self.database_url,
                connect_args=connect_args,
                pool_pre_ping=True,  # Test connection health
            )
        return self._engine

    def _init_db(self) -> None:
        """Initialize database schema."""
        engine = self._get_engine()
        metadata.create_all(engine)
        logger.info(
            "database_initialized",
            url=self._mask_url(self.database_url),
            backend="postgresql" if self._is_postgres else "sqlite",
        )

    def _mask_url(self, url: str) -> str:
        """Mask password in URL for logging."""
        parsed = urlparse(url)
        if parsed.password:
            masked = url.replace(parsed.password, "***")
            return masked
        return url

    def close(self) -> None:
        """Close database connection."""
        if self._engine:
            self._engine.dispose()
            self._engine = None

    def is_processed(self, txid: str, vout: int) -> bool:
        """Check if a payout has been processed."""
        engine = self._get_engine()
        with engine.connect() as conn:
            stmt = select(processed_payouts.c.id).where(
                processed_payouts.c.txid == txid,
                processed_payouts.c.vout == vout,
            )
            result = conn.execute(stmt).fetchone()
            return result is not None

    def mark_processed(
        self,
        txid: str,
        vout: int,
        borrower: str,
        amount_sats: int,
        block_height: int,
        tx_hash: Optional[str] = None,
        status: str = "pending",
    ) -> None:
        """
        Mark a payout as processed (upsert).

        Uses INSERT ... ON CONFLICT for idempotent upsert.
        """
        engine = self._get_engine()
        with engine.begin() as conn:
            if self._is_postgres:
                # PostgreSQL: use ON CONFLICT DO UPDATE
                stmt = pg_insert(processed_payouts).values(
                    txid=txid,
                    vout=vout,
                    borrower=borrower,
                    amount_sats=amount_sats,
                    block_height=block_height,
                    tx_hash=tx_hash,
                    status=status,
                    submitted_at=datetime.utcnow(),
                )
                stmt = stmt.on_conflict_do_update(
                    constraint="uq_txid_vout",
                    set_={
                        "tx_hash": stmt.excluded.tx_hash,
                        "status": stmt.excluded.status,
                        "submitted_at": stmt.excluded.submitted_at,
                    },
                )
                conn.execute(stmt)
            else:
                # SQLite: use INSERT OR REPLACE
                stmt = processed_payouts.insert().prefix_with("OR REPLACE").values(
                    txid=txid,
                    vout=vout,
                    borrower=borrower,
                    amount_sats=amount_sats,
                    block_height=block_height,
                    tx_hash=tx_hash,
                    status=status,
                    submitted_at=datetime.utcnow(),
                )
                conn.execute(stmt)

        logger.info(
            "payout_marked_processed",
            txid=txid,
            vout=vout,
            borrower=borrower,
            status=status,
        )

    def update_status(
        self, txid: str, vout: int, status: str, tx_hash: Optional[str] = None
    ) -> None:
        """Update payout status."""
        engine = self._get_engine()
        with engine.begin() as conn:
            values = {"status": status}
            if tx_hash:
                values["tx_hash"] = tx_hash

            stmt = (
                processed_payouts.update()
                .where(
                    processed_payouts.c.txid == txid,
                    processed_payouts.c.vout == vout,
                )
                .values(**values)
            )
            conn.execute(stmt)

    def get_pending_payouts(self) -> list[ProcessedPayout]:
        """Get payouts pending confirmation."""
        engine = self._get_engine()
        with engine.connect() as conn:
            stmt = select(processed_payouts).where(
                processed_payouts.c.status == "pending"
            )
            result = conn.execute(stmt).fetchall()

            return [
                ProcessedPayout(
                    txid=row.txid,
                    vout=row.vout,
                    borrower=row.borrower,
                    amount_sats=row.amount_sats,
                    block_height=row.block_height,
                    submitted_at=row.submitted_at or datetime.utcnow(),
                    tx_hash=row.tx_hash,
                    status=row.status,
                )
                for row in result
            ]
