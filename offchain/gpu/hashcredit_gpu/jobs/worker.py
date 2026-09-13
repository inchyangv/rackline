"""
Worker loop: claim → run handler in one transaction → complete in that same transaction.

Crash safety:
- crash *before* the handler transaction commits: the business effect and the completion roll back together;
  the lease expires and another worker re-claims the job (attempt+1);
- crash *after* commit: the job is SUCCEEDED, nothing re-runs;
- handler committed an effect through a separate path and then crashed: the re-run must be idempotent —
  ledgers' unique keys make a second economic effect impossible; the handler treats the unique violation as
  "already done".
A handler raises TransientError (retry with backoff) or TerminalError (dead-letter); any other exception is
recorded as TRANSIENT with the exception text so nothing is silently dropped.
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable, Mapping

from sqlalchemy.engine import Engine

from .queue import (
    ClaimedJob,
    FailureKind,
    Handler,
    JobQueue,
    LeaseLost,
    TerminalError,
    TransientError,
)

log = logging.getLogger(__name__)


class Worker:
    def __init__(
        self,
        engine: Engine,
        queue: JobQueue,
        handlers: Mapping[str, Handler],
        *,
        worker_id: str,
        lease_seconds: int = 60,
        poll_seconds: float = 1.0,
        rng: random.Random | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.engine = engine
        self.queue = queue
        self.handlers = dict(handlers)
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds
        self.poll_seconds = poll_seconds
        self.rng = rng or random.Random()
        self._sleep = sleep

    @property
    def kinds(self) -> tuple[str, ...]:
        return tuple(self.handlers)

    def run_one(self, job: ClaimedJob) -> str:
        """Execute one claimed job. Returns the resulting job state."""
        handler = self.handlers[job.kind]
        try:
            with self.engine.begin() as cx:
                self._before_handler(cx, job)
                handler(cx, job)
                self.queue.complete(job, cx=cx)  # same transaction as the effect
            return "SUCCEEDED"
        except LeaseLost:
            log.warning("job %s: lease lost during handling (attempt %s); not recording outcome", job.job_id, job.attempt)
            return "LEASE_LOST"
        except TerminalError as e:
            return self._fail_exception(job, FailureKind.TERMINAL, e)
        except TransientError as e:
            return self._fail_exception(job, FailureKind.TRANSIENT, e)
        except Exception as e:  # noqa: BLE001 - never drop a failure on the floor
            return self._fail_exception(job, FailureKind.TRANSIENT, e)

    def _before_handler(self, cx, job: ClaimedJob) -> None:
        """Optional domain lock-order/fencing guard, before the handler touches business rows."""

    def _fail_exception(self, job: ClaimedJob, kind: FailureKind, error: Exception) -> str:
        """Allow a domain worker to persist structured failure facts inside its fenced outcome."""
        reason = str(error) if isinstance(error, (TerminalError, TransientError)) else f"{type(error).__name__}: {error}"
        return self._fail(job, kind, reason)

    def _fail(self, job: ClaimedJob, kind: FailureKind, reason: str) -> str:
        try:
            return self.queue.fail(job, kind, reason)
        except LeaseLost:
            log.warning("job %s: lease lost while recording %s", job.job_id, kind)
            return "LEASE_LOST"

    def run_once(self) -> str | None:
        """Claim and run at most one job. Returns the job state or None if nothing was runnable."""
        job = self.queue.claim(self.worker_id, self.kinds, self.lease_seconds)
        if job is None:
            return None
        return self.run_one(job)

    def run_forever(self, *, max_iterations: int | None = None) -> int:
        """Poll loop with jittered idle sleep; `max_iterations` bounds it for tests/CLI."""
        processed = 0
        i = 0
        while max_iterations is None or i < max_iterations:
            i += 1
            if self.run_once() is None:
                self._sleep(self.poll_seconds * (0.5 + self.rng.random()))
            else:
                processed += 1
        return processed
