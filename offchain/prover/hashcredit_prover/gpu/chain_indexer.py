"""Run the shared deployment projector with a manifest-pinned destination RPC.

Resilience (2026-09-18, after the indexer sat CRASHED for two days on a `chain changed before index commit`):

- transient conditions — chain moved under a chunk, RPC / database unavailable — are retried in-process with
  exponential backoff (1 s → 60 s); the persistent cursor is never touched by a failed chunk;
- an alert (`GPU_ALERT_WEBHOOK_URL`) is raised once the loop has failed for `--alert-after` seconds and a
  resolved alert follows the next successful sync;
- integrity failures (finalized reorg, event conservation breaks) are reported as critical and re-raised: the
  process exits, the platform restart policy brings it back, and the deduplicated alert says why every time.
"""

import argparse
import logging
import os
import time

from hashcredit_gpu.monitoring.alerts import Alerter
from hashcredit_gpu.projections.indexer import ChainIndexer, FinalizedReorg, TransientChainChange
from hashcredit_gpu.projections.reconcile import reconcile_views
from hashcredit_gpu.transactions.rpc import (
    JsonRpcClient,
    RpcError,
    RpcTransportError,
    load_rpc_allowlist,
)
from sqlalchemy import create_engine
from sqlalchemy.exc import DisconnectionError, OperationalError

log = logging.getLogger(__name__)
RETRYABLE = (TransientChainChange, RpcError, RpcTransportError, TimeoutError, OSError, OperationalError, DisconnectionError)


def run_loop(indexer, deployment_id, *, engine=None, reconcile=False, interval=10.0, once=False, alerter=None,
             alert_after=120.0, max_backoff=60.0, sleep=time.sleep, clock=time.monotonic, emit=print):
    """The indexer loop, separated from argument parsing so the retry / alert behaviour is testable."""
    alerter = alerter or Alerter(service="gpu-indexer")
    failing_since = None
    failures = 0
    while True:
        try:
            result = indexer.sync(deployment_id)
            if reconcile and result["lag"] == 0 and engine is not None:
                result["reconciliation"] = reconcile_views(engine, indexer.rpc, deployment_id)
        except RETRYABLE as exc:
            failures += 1
            failing_since = clock() if failing_since is None else failing_since
            log.warning("indexer sync retry %d (%s: %s); persistent cursor preserved", failures, type(exc).__name__, exc)
            if once:
                raise
            if clock() - failing_since >= alert_after:
                alerter.alert("indexer-stalled", f"indexer has not completed a sync for {int(clock() - failing_since)} s "
                              f"({failures} attempts, last {type(exc).__name__}: {exc})", severity="warning")
            sleep(min(max_backoff, max(1.0, interval) * (2 ** min(failures - 1, 6))))
            continue
        except FinalizedReorg as exc:
            alerter.alert("indexer-finalized-reorg", f"finalized reorg detected: {exc}. Operator reconciliation required; "
                          "the indexer stops rather than rewrite finalized history.", severity="critical")
            raise
        except Exception as exc:  # integrity failure inside replay (conservation break, unknown deployment …)
            alerter.alert("indexer-crash", f"indexer stopped on {type(exc).__name__}: {exc}", severity="critical")
            raise
        if failing_since is not None:
            alerter.alert("indexer-stalled", f"indexer recovered after {failures} failed attempts; lag {result['lag']}", resolved=True)
            failing_since, failures = None, 0
        emit(result, flush=True)
        if once:
            return result
        if result["lag"] == 0:
            sleep(max(0.1, interval))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--deployment-id", required=True)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=float, default=10)
    parser.add_argument("--alert-after", type=float, default=float(os.environ.get("GPU_INDEXER_ALERT_AFTER_SECONDS") or 120),
                        help="seconds of consecutive sync failures before an alert is raised")
    parser.add_argument(
        "--reconcile",
        action="store_true",
        help="compare final projected debt/shares with canonical contract views",
    )
    args = parser.parse_args()
    _, urls = load_rpc_allowlist(args.manifest)
    engine = create_engine(
        os.environ.get("HASHCREDIT_GPU_DATABASE_URL") or os.environ["GPU_DATABASE_URL"]
    )
    indexer = ChainIndexer(engine, JsonRpcClient(urls[0], urls))
    alerter = Alerter.from_env("gpu-indexer")
    log.info("indexer alerts %s", "webhook configured" if alerter.configured else "log-only (GPU_ALERT_WEBHOOK_URL unset)")
    try:
        run_loop(indexer, args.deployment_id, engine=engine, reconcile=args.reconcile, interval=args.interval,
                 once=args.once, alerter=alerter, alert_after=args.alert_after)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
