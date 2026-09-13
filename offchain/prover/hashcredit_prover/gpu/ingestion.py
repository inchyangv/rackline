"""
Thin worker loop for GPU-022 ingestion. All logic lives in `hashcredit_gpu.ingestion`; this module only wires an
adapter, a config and a raw store, and runs the poll on a schedule. It never resets a cursor: a stream without
a cursor needs an explicit `initial_start` from configuration (onboarding date), otherwise the poll is refused
(`MissingCursorError`) and the operator is told so — the legacy watcher's "last 10 blocks on restart" is gone.

RateLimited / transport errors back off and retry from the persisted page token; ExpiredData opens a
SOURCE_RETENTION_GAP exception and stops that stream until an operator resolves it.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime

from hashcredit_gpu.ingestion import (
    Collector,
    CollectResult,
    IngestionConfig,
    MissingCursorError,
    RawStore,
)
from hashcredit_gpu.providers.base import ProviderAdapter
from hashcredit_gpu.providers.errors import ProviderAdapterError, RateLimited
from hashcredit_gpu.providers.types import AccountRef
from sqlalchemy.engine import Engine

log = logging.getLogger("hashcredit_prover.gpu.ingestion")


@dataclass(frozen=True)
class StreamSpec:
    account: AccountRef
    stream: str  # "revenue" | "settlements"
    initial_start: (
        datetime | None
    )  # required the first time; None means "must already have a cursor"


def run_once(collector: Collector, specs: Iterable[StreamSpec]) -> list[CollectResult | Exception]:
    out: list[CollectResult | Exception] = []
    for spec in specs:
        try:
            out.append(collector.poll(spec.account, spec.stream, initial_start=spec.initial_start))
        except MissingCursorError as e:
            log.error("stream refused: %s", e)
            out.append(e)
        except RateLimited as e:
            log.warning(
                "rate limited on %s/%s; will resume from page token",
                spec.account.account_key,
                spec.stream,
            )
            out.append(e)
        except ProviderAdapterError as e:
            log.warning("adapter error on %s/%s: %s", spec.account.account_key, spec.stream, e)
            out.append(e)
    return out


def run_forever(
    engine: Engine,
    adapter: ProviderAdapter,
    config: IngestionConfig,
    raw_store: RawStore,
    specs: list[StreamSpec],
    *,
    interval_seconds: float = 60.0,
    should_stop: Callable[[], bool] = lambda: False,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    collector = Collector(engine, adapter, config, raw_store)
    while not should_stop():
        run_once(collector, specs)
        sleep(interval_seconds)
