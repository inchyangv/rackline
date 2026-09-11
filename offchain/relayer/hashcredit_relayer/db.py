"""
Database for payout deduplication.
"""

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import structlog

logger = structlog.get_logger()


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


class PayoutDatabase:
    """SQLite database for tracking processed payouts."""

    def __init__(self, db_path: str = "relayer.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database schema."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS processed_payouts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                txid TEXT NOT NULL,
                vout INTEGER NOT NULL,
                borrower TEXT NOT NULL,
                amount_sats INTEGER NOT NULL,
                block_height INTEGER NOT NULL,
                submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                tx_hash TEXT,
                status TEXT DEFAULT 'pending',
                UNIQUE(txid, vout)
            )
        """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_txid_vout
            ON processed_payouts (txid, vout)
        """
        )

        conn.commit()
        conn.close()

        logger.info("database_initialized", path=self.db_path)

    def is_processed(self, txid: str, vout: int) -> bool:
        """Check if a payout has been processed."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            "SELECT 1 FROM processed_payouts WHERE txid = ? AND vout = ?",
            (txid, vout),
        )
        result = cursor.fetchone() is not None

        conn.close()
        return result

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
        """Mark a payout as processed."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT OR REPLACE INTO processed_payouts
            (txid, vout, borrower, amount_sats, block_height, tx_hash, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
            (txid, vout, borrower, amount_sats, block_height, tx_hash, status),
        )

        conn.commit()
        conn.close()

        logger.info(
            "payout_marked_processed",
            txid=txid,
            vout=vout,
            borrower=borrower,
            status=status,
        )

    def update_status(self, txid: str, vout: int, status: str, tx_hash: Optional[str] = None) -> None:
        """Update payout status."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        if tx_hash:
            cursor.execute(
                "UPDATE processed_payouts SET status = ?, tx_hash = ? WHERE txid = ? AND vout = ?",
                (status, tx_hash, txid, vout),
            )
        else:
            cursor.execute(
                "UPDATE processed_payouts SET status = ? WHERE txid = ? AND vout = ?",
                (status, txid, vout),
            )

        conn.commit()
        conn.close()

    def get_pending_payouts(self) -> list[ProcessedPayout]:
        """Get payouts pending confirmation."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            "SELECT txid, vout, borrower, amount_sats, block_height, submitted_at, tx_hash, status "
            "FROM processed_payouts WHERE status = 'pending'"
        )

        payouts = []
        for row in cursor.fetchall():
            payouts.append(
                ProcessedPayout(
                    txid=row[0],
                    vout=row[1],
                    borrower=row[2],
                    amount_sats=row[3],
                    block_height=row[4],
                    submitted_at=datetime.fromisoformat(row[5]) if row[5] else datetime.now(),
                    tx_hash=row[6],
                    status=row[7],
                )
            )

        conn.close()
        return payouts
