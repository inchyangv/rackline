"""
Overlapping backfill and correction re-fetch on top of the transactional collector.

Backfill splits [start, end] into chunks that overlap by `overlap_seconds` so a boundary row seen twice is
deduplicated by the raw payload hash and a row that moved between pages is not lost. Each chunk runs on its
own cursor stream (`backfill:<range>:...`), so a normal poll cursor is never rewound or reset by a backfill.
A correction re-fetch re-reads a bounded window around a provider ref: a revised statement is a *new* raw
observation (different payload hash → different row); the receivable-level revision rule (GPU-035/081) decides
what it means. Ingestion itself never applies corrections to balances.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from ..providers.types import AccountRef
from .collector import Collector, CollectResult


def backfill_account(
    collector: Collector,
    account: AccountRef,
    stream: str,
    start: datetime,
    end: datetime,
    *,
    chunk_seconds: int,
    overlap_seconds: int,
) -> list[CollectResult]:
    if end <= start:
        raise ValueError("backfill end must be after start")
    if chunk_seconds <= overlap_seconds:
        raise ValueError("chunk must be longer than the overlap")
    results: list[CollectResult] = []
    cursor = start
    while cursor < end:
        chunk_end = min(end, cursor + timedelta(seconds=chunk_seconds))
        chunk_start = max(start, cursor - timedelta(seconds=overlap_seconds))
        tag = f"backfill:{int(chunk_start.timestamp())}-{int(chunk_end.timestamp())}"
        results.append(collector.collect_window(account, stream, chunk_start, chunk_end, tag=tag))
        cursor = chunk_end
    return results


def refetch_corrections(
    collector: Collector,
    account: AccountRef,
    stream: str,
    around: datetime,
    *,
    radius_seconds: int,
    tag_suffix: str,
) -> CollectResult:
    """Re-read [around - radius, around + radius] for late corrections. Idempotent: unchanged rows dedupe."""
    start = around - timedelta(seconds=radius_seconds)
    end = around + timedelta(seconds=radius_seconds)
    return collector.collect_window(account, stream, start, end, tag=f"refetch:{tag_suffix}")
