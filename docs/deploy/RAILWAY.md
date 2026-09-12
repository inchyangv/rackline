# Railway Deployment Guide

This document describes how to deploy the HashCredit off-chain services to Railway.

## Service Layout

| Component | Platform | Source |
|-----------|----------|--------|
| Frontend | Vercel | `apps/web` |
| API | Railway | `offchain/api` |
| Prover (Worker) | Railway | `offchain/prover` |
| Database | Railway Postgres | — |

Production domains:
- Frontend: `https://hashcredit.studioliq.com`
- API: `https://api-hash.credit`

## Prerequisites

1. A Railway account and workspace.
2. Permission to link this GitHub repo to Railway.
3. Secrets (`PRIVATE_KEY`, `CLAIM_SECRET`, etc.) — never commit these to git.

## Why Two Services?

This is a monorepo with Python (API + Worker) and Vite (Frontend). Railway does not auto-split it into multiple services from a single repo connection. You must create two services explicitly:

- **(Recommended)** Drag-and-drop the Compose file to create both services at once.
- **(Alternative)** Create two GitHub repo connections, each with a different Root Directory.
- **(Auto-staging)** The `offchain/api` and `offchain/prover` directories are registered as workspaces in the root `package.json`, so Railway may auto-detect `hashcredit-api` and `hashcredit-prover` as separate services on import.

Each service uses **Dockerfile-based builds**, not the Node runtime.

## Fixing `start.sh not found` / Railpack Build Failures

If Railway's auto-detection (Railpack) fails because the repo root has no single `package.json` or `requirements.txt`, it may fall back to `shell` mode and look for `start.sh`.

**Solutions (pick one):**

1. **(Recommended)** Set each service's Root Directory to `offchain/api` or `offchain/prover` and use Dockerfile builds.
2. **(Quick bypass)** Use the Dockerfiles at the repo root:
   - API: `Dockerfile`
   - Worker: `Dockerfile.prover` (set this as the Dockerfile path in service settings)

## 1. Create Services via Compose

1. Create a new project in Railway.
2. Drag-and-drop `railway-compose.yml` from the repo root onto the project canvas.
3. Verify two services appear: `hashcredit-api` and `hashcredit-prover`.

**Note:** Compose drag-and-drop creates the service structure only. To enable auto-deploy on push, connect each service to the GitHub repo separately.

## 2. Add Postgres

The prover worker requires a database for deduplication and state storage.

1. Add the Postgres plugin in the Railway project.
2. Connect the `DATABASE_URL` reference to:
   - `hashcredit-prover` (required)
   - `hashcredit-api` (optional, if the API needs DB access later)

The prover code automatically converts Railway's `postgres://` format to `postgresql://`.

## 3. Build Settings

Each service has its own Dockerfile:
- `offchain/api/Dockerfile`
- `offchain/prover/Dockerfile`

Set Root Directories in Railway:
- `hashcredit-api` → `offchain/api`
- `hashcredit-prover` → `offchain/prover`

### (Optional) Config as Code

Service-specific `railway.toml` files are included:
- API: `offchain/api/railway.toml`
- Worker: `offchain/prover/railway.toml`

These limit `watchPatterns` to avoid unnecessary redeployments when unrelated files change (e.g., frontend changes should not redeploy the API).

**Important:** Railway Config file paths do not follow the Root Directory. You may need to set the absolute path in Service Settings:
- API: `/offchain/api/railway.toml`
- Worker: `/offchain/prover/railway.toml`

## 4. API Service Variables (`hashcredit-api`)

Set these in Railway → `hashcredit-api` → Variables/Secrets.

### Required

| Variable | Type | Description |
|----------|------|-------------|
| `ALLOWED_ORIGINS` | Variable | CORS origins as JSON array |
| `BITCOIN_RPC_URL` | Variable | Bitcoin RPC endpoint |
| `BITCOIN_RPC_USER` | Secret | Optional — for authenticated RPC |
| `BITCOIN_RPC_PASSWORD` | Secret | Optional — for authenticated RPC |
| `EVM_RPC_URL` | Variable | HashKey Chain RPC |
| `CHAIN_ID` | Variable | e.g., `133` |

### Contract Addresses

| Variable | Type |
|----------|------|
| `HASH_CREDIT_MANAGER` | Variable |
| `CHECKPOINT_MANAGER` | Variable |
| `BTC_SPV_VERIFIER` | Variable |

### Borrower Mapping Mode

| Mode | `BORROWER_MAPPING_MODE` | Description |
|------|------------------------|-------------|
| Testnet/Demo | `demo` | Operator registers borrower ↔ BTC mappings directly |
| Production | `claim` | Borrower proves ownership via BTC + EVM signatures |

For `claim` mode, also set:
- `CLAIM_SECRET` (Secret)

### Port

Railway injects `PORT` automatically. `HOST=0.0.0.0` is the Dockerfile default.

## 5. Worker Service Variables (`hashcredit-prover`)

Set these in Railway → `hashcredit-prover` → Variables/Secrets.

### Required

| Variable | Type | Description |
|----------|------|-------------|
| `DATABASE_URL` | Reference | Reference Railway Postgres `DATABASE_URL` |
| `BITCOIN_RPC_URL` | Variable | Bitcoin RPC endpoint |
| `EVM_RPC_URL` | Variable | HashKey Chain RPC |
| `CHAIN_ID` | Variable | e.g., `133` |
| `PRIVATE_KEY` | Secret | Operator key for proof submission |
| `HASH_CREDIT_MANAGER` | Variable | Contract address |
| `CHECKPOINT_MANAGER` | Variable | Contract address |

### Watched Addresses (one of three — pick one)

| Variable | Type | Notes |
|----------|------|-------|
| `ADDRESSES_JSON_B64` | Secret | Base64-encoded JSON (recommended) |
| `ADDRESSES_JSON` | Secret | Raw JSON string |
| `ADDRESSES_FILE` | Variable | File path inside container (volume-dependent, not recommended) |

Example — generating `ADDRESSES_JSON_B64`:

```bash
cat <<'JSON' | base64
[
  { "btc_address": "tb1q...", "borrower": "0x..." }
]
JSON
```

### Tuning (Optional)

| Variable | Default | Description |
|----------|---------|-------------|
| `SPV_CONFIRMATIONS` | `6` | Required confirmations |
| `SPV_POLL_INTERVAL` | `60` | Poll interval in seconds |
| `SPV_RUN_ONCE` | `false` | Run one cycle and exit |

### Networking

The prover does not expose HTTP endpoints. Disable Public Networking in Railway for this service.

## 6. Custom Domain (API)

1. In Railway, add a custom domain under `hashcredit-api` → Networking/Domain.
2. Create the DNS record (CNAME or A) as guided by Railway.
3. Once HTTPS is provisioned, configure the frontend with `VITE_API_URL=https://api-hash.credit`.

## 7. Post-Deployment Checklist

### API

- [ ] `GET /health` returns 200
- [ ] Frontend calls the correct API URL
- [ ] API is in wallet-only mode (no server-side transaction submission)

### Worker

- [ ] Logs show `Loaded N watched addresses`
- [ ] No Postgres connection errors
- [ ] (Demo) Detects testnet payouts and submits proofs

## 8. Monorepo Considerations

1. Incorrect Root Directory settings (e.g., pointing to repo root) will cause build failures.
2. Railway `railway.toml` Config file paths are **absolute from repo root**, not relative to the service Root Directory. Specify them explicitly:
   - API: `/offchain/api/railway.toml`
   - Worker: `/offchain/prover/railway.toml`
3. Dockerfile-based deployment works without `railway.toml` — the config files are optional optimizations.
