# Rackline GPU API

The production entrypoint is a GPU-only FastAPI application. It serves deployment-bound product views, wallet authentication, onboarding and provider review requests, proof requests, operations workflows, and canonical chain reads. It does not import the legacy Bitcoin write routes or hold a browser-facing signing key.

## Run

Install the shared database package first, build the Attestcoin CLI, then start the API:

```bash
python -m pip install -e "offchain/gpu[dev]" -e "offchain/api[dev]"
npm ci --prefix offchain/attestcoin
npm --prefix offchain/attestcoin run build
python -m hashcredit_api.gpu.server --initialize
python -m hashcredit_api.gpu.server
```

Copy the repository `.env.example` values into your process environment. Required deployment settings are:

- `HASHCREDIT_GPU_DATABASE_URL`
- `GPU_EXECUTION_PROFILE`, `GPU_CHAIN_ID`, `GPU_DEPLOYMENT_ID`
- `GPU_MANIFEST_HASH`, `GPU_DEPLOYMENT_MANIFEST`, `GPU_ATTESTCOIN_MANIFEST`
- `GPU_APP_DOMAIN`, `GPU_SESSION_SECRET`, `GPU_CORS_ORIGINS`
- `GPU_RPC_URL`, `GPU_ABI_DIRECTORY`

`--initialize` applies migrations, rejects schema drift, validates the deployment manifest, and registers its immutable identity. Startup does not seed financial records or make an external RPC request.

## API boundaries

- `GET /health` reports liveness; it is not deployment readiness.
- `GET /v1/config` returns the browser-safe deployment identity and capabilities.
- `POST /v1/auth/challenge` and `POST /v1/auth/session` implement expiring EIP-712/EOA or ERC-1271 login.
- `GET /v1/*` returns borrower-scoped or role-scoped projections bound to a canonical finalized block.
- `POST /v1/onboarding` and `POST /v1/connections` create review requests, never approval.
- proof requests enqueue evidence work but cannot mark native verification accepted.
- operational commands require explicit roles, idempotency keys, expected versions, reasons, row locks, and audit entries.
- financial transactions are prepared from a fresh facility context and signed in the user's wallet.

Every response identifies its execution profile, chain, deployment and manifest. Production rejects test-only assets and non-mainnet chain IDs. Secrets, raw credentials and cross-borrower data are excluded from DTOs.

## Tests

```bash
python -m pytest offchain/api/tests -q
```

The legacy `hashcredit_api.main` module remains only for the archived Bitcoin-SPV prototype. It is not the container or Railway entrypoint for Rackline v2.
