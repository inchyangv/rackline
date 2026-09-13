"""GPU-only deploy entrypoint; legacy BTC code and credentials are never imported."""

import argparse
import os
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from hashcredit_gpu.db.cli import upgrade, schema_diff
from hashcredit_gpu.db.projections_models import ChainDeployment

from .product.settings import ProductSettings
from .product.chain import deployment


def initialize(settings):
    if settings.database_url is None:
        raise RuntimeError("HASHCREDIT_GPU_DATABASE_URL is required")
    url = settings.database_url.get_secret_value()
    upgrade(url)
    if schema_diff(url):
        raise RuntimeError("GPU schema drift detected")
    manifest = deployment(settings)
    if manifest is None:
        raise RuntimeError("GPU deployment manifest is required")
    engine = create_engine(url, hide_parameters=True)
    try:
        with Session(engine) as session, session.begin():
            existing = session.get(ChainDeployment, settings.deployment_id)
            fields = dict(chain_id=settings.chain_id, execution_profile=settings.execution_profile,
                env_id=manifest.get("envId", "cc3-testnet"), manifest_hash=settings.manifest_hash,
                deployment_block=manifest["deploymentBlock"], contracts=manifest["contracts"],
                finality_depth=manifest.get("finalityDepth", 6))
            if existing:
                if any(getattr(existing, key) != value for key, value in fields.items()):
                    raise RuntimeError("existing deployment registration differs; refuse overwrite")
            else:
                session.add(ChainDeployment(deployment_id=settings.deployment_id, **fields))
    finally:
        engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--initialize", action="store_true")
    args = parser.parse_args()
    settings = ProductSettings()
    if args.initialize:
        initialize(settings)
        print("GPU schema and deployment initialized")
        return
    service = os.environ.get("GPU_SERVICE", "api")
    if service != "api":
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from threading import Thread
        class Health(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200 if self.path == "/health" else 404)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"status":"alive","worker":true}')
            def log_message(self, *_):
                pass
        server = ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT", "8000"))), Health)
        Thread(target=server.serve_forever, daemon=True).start()
    if service == "api":
        import uvicorn
        from .app import create_app
        uvicorn.run(create_app(settings), host="0.0.0.0", port=int(os.environ.get("PORT", "8000")), access_log=False)
    elif service == "indexer":
        from hashcredit_prover.gpu.chain_indexer import main as run
        sys.argv = ["gpu-indexer", "--manifest", os.environ["GPU_ATTESTCOIN_MANIFEST"],
                    "--deployment-id", settings.deployment_id, "--reconcile"]
        run()
    elif service == "proof":
        from hashcredit_prover.gpu.attestcoin_worker import main as run
        sys.argv = ["gpu-proof", "--manifest", os.environ["GPU_ATTESTCOIN_MANIFEST"],
                    "--deployment-id", settings.deployment_id, "--sdk-cli", os.environ["ATTESTCOIN_CLI"],
                    "--artifact-dir", os.environ.get("GPU_ARTIFACT_DIR", "/data/proofs")]
        if os.environ.get("GPU_SUBMISSION_PLANS"):
            sys.argv.extend(["--plans", os.environ["GPU_SUBMISSION_PLANS"]])
        run()
    elif service == "monitor":
        from hashcredit_prover.gpu.control_monitor import main as run
        sys.argv = ["gpu-monitor", "--deployment-id", settings.deployment_id]
        run()
    else:
        raise RuntimeError("unknown GPU_SERVICE")


if __name__ == "__main__":
    main()
