# Rackline GPU API

A GPU-only FastAPI application (`hashcredit_api.gpu.app`). It serves deployment-bound product views, wallet authentication, onboarding and provider review requests, proof requests, operations workflows, and canonical chain reads. It does not import the legacy Bitcoin write routes and never holds a browser-facing signing key. The package name keeps the legacy `hashcredit` identifier.

## Run

```bash
python -m pip install -e "offchain/gpu[dev]" -e "offchain/api[dev]"
npm ci --prefix offchain/attestcoin
npm --prefix offchain/attestcoin run build
python -m hashcredit_api.gpu.server --initialize
python -m hashcredit_api.gpu.server
```

Settings are read from the process environment with the `GPU_` prefix (`.env` files are not loaded; copy values from the repository `.env.example`). Required:

| Variable | Meaning |
| --- | --- |
| `HASHCREDIT_GPU_DATABASE_URL` | PostgreSQL URL |
| `GPU_EXECUTION_PROFILE`, `GPU_CHAIN_ID`, `GPU_DEPLOYMENT_ID` | Profile and deployment identity; profile/chain pairs are validated (`LOCAL_MOCK` cannot use a public Creditcoin chain, `PRODUCTION` requires 102030) |
| `GPU_MANIFEST_HASH`, `GPU_DEPLOYMENT_MANIFEST`, `GPU_ATTESTCOIN_MANIFEST` | Deployment and Attestcoin manifests the API binds every read to |
| `GPU_APP_DOMAIN`, `GPU_SESSION_SECRET` (≥ 32 chars), `GPU_CORS_ORIGINS` (explicit origins, no wildcards) | Wallet login domain, session signing, browser origins |
| `GPU_RPC_URL`, `GPU_ABI_DIRECTORY` | Canonical chain reads and ABI snapshots |

`--initialize` applies migrations, rejects schema drift, validates the deployment manifest, and registers its immutable identity (a differing existing registration is refused). Startup seeds no financial records and makes no external RPC request.

## Endpoints and boundaries

| Endpoint | Behavior |
| --- | --- |
| `GET /health` | Liveness only; not deployment readiness |
| `GET /ready` | Indexer freshness against the canonical block |
| `GET /v1/config` | Browser-safe deployment identity, contract addresses, capabilities |
| `POST /v1/auth/challenge`, `POST /v1/auth/session` | Expiring EIP-712 login for EOAs; ERC-1271 for contract wallets |
| `GET /v1/*` | Borrower-scoped or role-scoped projections bound to a canonical finalized block |
| `POST /v1/onboarding`, `POST /v1/connections` | Review requests; never approval, E2, or native acceptance |
| `POST /v1/proofs` | Enqueues evidence work; cannot mark native verification accepted |
| Operations commands | Require explicit roles, idempotency keys, expected versions, reasons, row locks, and audit entries |

Financial transactions are prepared from a fresh facility context and signed in the user's wallet. Every response identifies its execution profile, chain, deployment, and manifest. Production rejects test-only assets and non-mainnet chain IDs. Secrets, raw credentials, and cross-borrower data never appear in DTOs. Staff roles are never inferred from deployment keys.

## Tests

```bash
python -m pytest offchain/api/tests -q
```

The legacy `hashcredit_api.main` module belongs to the archived Bitcoin-SPV prototype and is not the container or Railway entrypoint.
