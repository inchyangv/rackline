"""Run the shared deployment projector with a manifest-pinned destination RPC."""

import argparse
import logging
import os
import time

from hashcredit_gpu.projections.indexer import ChainIndexer
from hashcredit_gpu.projections.reconcile import reconcile_views
from hashcredit_gpu.transactions.rpc import (
    JsonRpcClient,
    RpcError,
    RpcTransportError,
    load_rpc_allowlist,
)
from sqlalchemy import create_engine
from sqlalchemy.exc import DisconnectionError, OperationalError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--deployment-id", required=True)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=float, default=10)
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
    try:
        while True:
            try:
                result = indexer.sync(args.deployment_id)
                if args.reconcile and result["lag"] == 0:
                    result["reconciliation"] = reconcile_views(
                        engine, indexer.rpc, args.deployment_id
                    )
            except (
                RpcError,
                RpcTransportError,
                TimeoutError,
                OSError,
                OperationalError,
                DisconnectionError,
            ) as exc:
                logging.getLogger(__name__).warning(
                    "indexer dependency unavailable (%s); persistent cursor preserved",
                    type(exc).__name__,
                )
                if args.once:
                    raise
                time.sleep(max(1, args.interval))
                continue
            print(result, flush=True)
            if args.once:
                return
            if result["lag"] == 0:
                time.sleep(max(0.1, args.interval))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
