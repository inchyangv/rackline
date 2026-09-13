"""Local PostgreSQL/API against the actual published testnet contracts; no simulated chain state."""

import importlib.util
import json
import os
import secrets
import subprocess
import sys
import threading
import time
from pathlib import Path

import uvicorn
from sqlalchemy import create_engine

from hashcredit_api.gpu.app import create_app
from hashcredit_api.gpu.product.settings import ProductSettings
from hashcredit_api.gpu.server import initialize
from hashcredit_gpu.projections.indexer import ChainIndexer
from hashcredit_gpu.projections.reconcile import reconcile_views
from hashcredit_gpu.transactions.rpc import JsonRpcClient, load_rpc_allowlist

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("native_pg_support", ROOT / "offchain/gpu/tests/conftest.py")
support = importlib.util.module_from_spec(spec)
spec.loader.exec_module(support)


def main():
    deployment_path = ROOT / "config/gpu/deployments/cc3-testnet.json"
    manifest_path = ROOT / "config/attestcoin/cc3-testnet.sepolia.release.json"
    deployment = json.loads(deployment_path.read_text())
    if deployment["executionProfile"] != "NATIVE_TESTNET" or not deployment["asset"]["testOnly"]:
        raise RuntimeError("Only the approved TEST_ONLY native deployment is permitted")
    cluster = support.EphemeralPostgres(support._find_bindir())
    engine = None
    stopped = threading.Event()
    try:
        url = cluster.start()
        settings = ProductSettings(database_url=url, execution_profile="NATIVE_TESTNET", chain_id=102031,
            deployment_id=deployment["deploymentId"], manifest_hash=deployment["manifestHash"],
            deployment_manifest=str(deployment_path), abi_directory=str(ROOT / "test/fixtures/gpu/abi"),
            app_domain="https://rackline.studioliq.com", session_secret=secrets.token_urlsafe(48), max_projection_age_seconds=180,
            cors_origins=["http://127.0.0.1:4274"])
        initialize(settings)
        os.environ["GPU_ATTESTCOIN_MANIFEST"] = str(manifest_path)
        os.environ["HASHCREDIT_GPU_DATABASE_URL"] = url
        if "--skip-bootstrap" not in sys.argv:
            subprocess.run([sys.executable, "-m", "hashcredit_prover.gpu.bootstrap_native",
                "--deployment", str(deployment_path), "--manifest", str(manifest_path),
                "--setup-receipt", str(ROOT / "broadcast/SetupGpuFacility.s.sol/102031/run-latest.json"),
                "--operator", "0x8B05D473158913a034376D749ECdEbd48040d6Aa"], check=True)
        # Local-only locator lets the reviewed backfill command connect without exposing a service credential.
        locator = ROOT / "keys/gpu-local-runtime.json"
        locator.write_text(json.dumps({"databaseUrl": url, "apiUrl": "http://127.0.0.1:4183"}))
        locator.chmod(0o600)
        engine = create_engine(url)
        _, urls = load_rpc_allowlist(str(manifest_path))
        rpc = JsonRpcClient(urls[0], urls)
        indexer = ChainIndexer(engine, rpc)
        def index():
            while not stopped.is_set():
                try:
                    result = indexer.sync(deployment["deploymentId"])
                    if result["lag"] == 0:
                        result["reconciliation"] = reconcile_views(engine, rpc, deployment["deploymentId"])
                    print("NATIVE_INDEXER", result, flush=True)
                except Exception as exc:
                    print("NATIVE_INDEXER_RETRY", type(exc).__name__, flush=True)
                stopped.wait(10)
        threading.Thread(target=index, daemon=True).start()
        uvicorn.run(create_app(settings), host="127.0.0.1", port=4183, access_log=False, log_level="warning")
    finally:
        stopped.set()
        if engine:
            engine.dispose()
        cluster.stop()


if __name__ == "__main__":
    main()
