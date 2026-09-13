"""LOCAL browser/API interoperability harness backed by a disposable real PostgreSQL database.

No RPC, contract deployment, proof service, native verification, signing key or customer funds.
The API uses native-required policy with an unconfigured deployment, so financial actions fail closed.
Run with the repository Python environment; terminate to remove only this process's ephemeral cluster.
"""

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path

import uvicorn
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from hashcredit_api.gpu.app import create_app
from hashcredit_api.gpu.product.settings import ProductSettings
from hashcredit_gpu.db.cli import upgrade
from hashcredit_gpu.db.models import Provider
from hashcredit_gpu.db.projections_models import ChainBlock, ChainCursor, ChainDeployment

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("gpu_pg_harness", ROOT / "offchain/gpu/tests/conftest.py")
support = importlib.util.module_from_spec(spec)
spec.loader.exec_module(support)


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 4182
    cluster = support.EphemeralPostgres(support._find_bindir())
    engine = None
    try:
        url = cluster.start()
        upgrade(url, "head")
        engine = create_engine(url)
        now = datetime.now(timezone.utc)
        deployment_id = "00000000000000000000000001"
        manifest = "sha256:" + "ab" * 32
        block = "0x" + "cd" * 32
        with Session(engine) as session, session.begin():
            session.add(ChainDeployment(deployment_id=deployment_id, chain_id=102031,
                execution_profile="NATIVE_TESTNET", env_id="LOCAL_POLICY_TEST_NO_RPC",
                manifest_hash=manifest, deployment_block=1, contracts={}, finality_depth=0))
            session.add(Provider(provider_id="test-provider", display_name="TEST_ONLY provider review",
                source_env_id="cc3-testnet", source_chain_key=1, source_chain_id=11155111,
                execution_profile="NATIVE_TESTNET", environment_status="UNCONFIRMED",
                manifest_hash=manifest, capabilities={}, test_only=True))
            session.flush()
            session.add(ChainBlock(deployment_id=deployment_id, number=1, hash=block,
                parent_hash="0x" + "00" * 32, timestamp=int(now.timestamp()), tier="FINALIZED"))
            session.add(ChainCursor(deployment_id=deployment_id, last_block_number=1,
                last_block_hash=block, finalized_block_number=1, updated_at=now))
        settings = ProductSettings(database_url=url, execution_profile="NATIVE_TESTNET", chain_id=102031,
            deployment_id=deployment_id, manifest_hash=manifest, app_domain="rackline.local.integration",
            session_secret="local-interoperability-test-session-secret-only", max_projection_age_seconds=86400,
            cors_origins=["http://127.0.0.1:4173", "http://127.0.0.1:4273"])
        app = create_app(settings)
        handler = app.exception_handlers[SQLAlchemyError]
        async def diagnose(request, exc):
            detail = getattr(getattr(exc, "orig", None), "diag", None)
            print("LOCAL_API_DATABASE_ERROR", type(exc).__name__, getattr(detail, "message_primary", ""), getattr(detail, "constraint_name", ""), flush=True)
            return await handler(request, exc)
        app.exception_handlers[SQLAlchemyError] = diagnose
        print(f"LOCAL_API_REVIEW_READY http://127.0.0.1:{port}", flush=True)
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
    finally:
        if engine is not None:
            engine.dispose()
        cluster.stop()


if __name__ == "__main__":
    main()
