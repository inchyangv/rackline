# Railway distribution (monorepo, FE=Vercel / rest=Railway)

This document outlines the procedures for distributing the HashCredit monorepo to Railway in a “clean” manner by separating off-chain components into service units.

- Frontend: Vercel (`apps/web`)
- Backend/API: Railway (`offchain/api`)
- Worker(Prover): Railway (`offchain/prover`)
- DB: Railway Postgres plugin (recommended)

Operating domain (fixed):

- FE: `https://hashcredit.studioliq.com`
- API: `https://api-hashcredit.studioliq.com`

## 0) Pre-check

1. You must have a Railway account/workspace ready.
2. You must have permission to link this repo to Railway on GitHub.
3. API private key, API_TOKEN, CLAIM_SECRET, etc. **Secrets are never committed to git.**

## 0.5) Why does it appear as `ctc-hashcredit` in Railway?

- When you connect a GitHub repo in Railway with "Deploy from GitHub", a **single service** is created based on the repo name.
- This repo is an **isolated monorepo** consisting of Python (API/Worker) + Vite (Frontend), so it is not in the form of “the service is automatically divided into multiple parts just by connecting the repo.”
- Therefore, if your goal is to distribute `API`/`Worker` separately, you must **create two services** in one of the ways below.
- (Recommended) Create two services by dragging and dropping Compose, and then set up GitHub connection (autodeploy) for each service.
- (Alternative) Create a GitHub repo connection twice for each service and specify the Root Directory respectively.
- (Auto Staging) We have registered `offchain/api` and `offchain/prover` as root `package.json` workspaces to trigger Railway's "automatic detection of JS monorepo".
- When you import a new repo, expect the `hashcredit-api` / `hashcredit-prover` services to be automatically staged separately.
- Each service defaults to **Dockerfile build** and does not run with the Node runtime.

## 0.6) `start.sh not found` / Reason for Railpack build failure and solution

If you connect the repo route as is in Railway, Railpack will try to auto-detect the language/entrypoint. This repo doesn't have a single app signal like `package.json`/`requirements.txt` in the root, which can cause Railpack to fall to `shell` and fail looking for `start.sh`.

Solve (one of two):

1. (Recommended) Set the service root directory to `offchain/api` or `offchain/prover` and deploy with a Dockerfile build.
2. (Quick bypass) I added the Dockerfile to the root.
- API Basics: Repo root `Dockerfile`
- Worker: Repo root `Dockerfile.prover` (replace Dockerfile path with this in service settings)

## 1) (Recommended) Create two services separately at once with Compose

Railway creates services at once by dragging and dropping a Compose file.

1. Create a new project in Railway.
2. Drag and drop `railway-compose.yml` from the repo root onto the project canvas.
3. Verify that the two services below are created.
   - `hashcredit-api`
   - `hashcredit-prover`

importance:

- Compose drag and drop is for “creating/detaching services” purpose.
- If you want GitHub autodeploy (automatic deployment when a commit is pushed), you must additionally set up a GitHub repo connection for each service.
- Actual operating variables/secrets are set to Railway Variables/Secrets.

## 2) Add and connect Postgres

Worker (Prover) needs DB for dedupe/state storage. For operations, we recommend the Railway Postgres plugin.

1. Add the Postgres plugin in the Railway project.
2. Connect the `DATABASE_URL` provided by the plugin to the service below.
- `hashcredit-prover` (required)
- (Optional) If the API is expanded to use DB, it can be connected to `hashcredit-api`

reference:

- Railway Postgres can be in the format `postgres://...`.
- The prover/relayer code automatically converts the Railway format to `postgresql://...` for processing.

## 3) Build/run settings for each service

In this repo, each off-chain service has its own `Dockerfile`.

- `offchain/api/Dockerfile`
- `offchain/prover/Dockerfile`

The Root Directory of each service in Railway uses:

- `hashcredit-api` -> `offchain/api`
- `hashcredit-prover` -> `offchain/prover`

If you created it with Compose, it is normal to already have this structure.

### (optional, recommended) Use Railway Config as Code

This repo contains a service-specific `railway.toml`.

- API: `offchain/api/railway.toml`
- Worker: `offchain/prover/railway.toml`

purpose:

- Limit `watchPatterns` to reduce unnecessary redistribution being triggered by "changes to other folders", such as FE changes.
- The API specifies to use `/health` as healthcheck.

caution:

- In Railway's isolated monorepo, the Config file path may not follow the Root Directory.
- You may need to specify the Config file path in Service Settings as shown below.
  - API: `/offchain/api/railway.toml`
  - Worker: `/offchain/prover/railway.toml`

## 4) API service (`hashcredit-api`) Variables/Secrets

Set the following in Railway -> `hashcredit-api` service -> Variables/Secrets.

Required/Recommended:

- `API_TOKEN` (Secrets): For protecting the entire API. Creation example:
  - `python -c "import secrets; print(secrets.token_urlsafe(32))"`
- `ALLOWED_ORIGINS` (Variables): CORS allowed origin (JSON array string)
- Example: `["https://hashcredit.studioliq.com","http://localhost:5173","http://127.0.0.1:5173"]`
- `BITCOIN_RPC_URL` (Variables)
- Demo (testnet): `https://bitcoin-testnet-rpc.publicnode.com`
- `BITCOIN_RPC_USER` (Secrets, optional)
- `BITCOIN_RPC_PASSWORD` (Secrets, optional)
- `EVM_RPC_URL` (Variables)
- Example: `https://rpc.cc3-testnet.creditcoin.network`
- `CHAIN_ID` (Variables)
- Example: `102031`
- `PRIVATE_KEY` (Secrets): Contract call/registration/submission transaction signing key (operation key)

Contract Address (Variables):

- `HASH_CREDIT_MANAGER`
- `CHECKPOINT_MANAGER`
- `BTC_SPV_VERIFIER`

Borrower mapping modes:

- Testnet/Demo: `BORROWER_MAPPING_MODE=demo`
- Operator directly registers borrower(EVM) <-> BTC address mapping.
- Mainnet: `BORROWER_MAPPING_MODE=claim` (recommended)
- When the borrower proves (claims) ownership with a BTC/EVM signature, the server registers it on-chain.
- This mode requires the following secrets:
    - `CLAIM_SECRET` (Secrets)
- (Optional) `CLAIM_REQUIRE_API_TOKEN=true`

Port/Binding:

- Railway automatically injects `PORT`.
- `HOST=0.0.0.0` is set as the Dockerfile default.

## 5) Worker service (`hashcredit-prover`) Variables/Secrets

Set the following in Railway -> `hashcredit-prover` service -> Variables/Secrets.

essential:

- `DATABASE_URL` (Variables/Reference): Refer to `DATABASE_URL` of Railway Postgres.
- `BITCOIN_RPC_URL` (Variables)
- Demo: `https://bitcoin-testnet-rpc.publicnode.com`
- `EVM_RPC_URL` (Variables)
- `CHAIN_ID` (Variables)
- `PRIVATE_KEY` (Secrets): proof submission transaction signing key (operation key)
- `HASH_CREDIT_MANAGER` (Variables)
- `CHECKPOINT_MANAGER` (Variables)

Watched addresses (required, only one of the three below):

- `ADDRESSES_JSON_B64` (Recommended, Secrets): base64(JSON)
- `ADDRESSES_JSON` (Secrets): JSON string
- `ADDRESSES_FILE` (not recommended): File path inside container (volume dependent)

Example of creating `ADDRESSES_JSON_B64`:

```bash
cat <<'JSON' | base64
[
  { "btc_address": "tb1q...", "borrower": "0x..." }
]
JSON
```

Tuning (optional):

- `SPV_CONFIRMATIONS` (default 6)
- `SPV_POLL_INTERVAL` (default 60 seconds)
- `SPV_RUN_ONCE` (default false)
- `RELAYER_ARGS` (start-worker.sh is passed as a CLI argument)

Networking:

- `hashcredit-prover` does not require external HTTP.
- It is recommended to turn off Public Networking in Railway.

## 6) Custom domain connection (API)

The API uses `api-hashcredit.studioliq.com`.

1. In Railway, add a custom domain in `hashcredit-api` service -> Networking/Domain.
2. Register the DNS record (CNAME/A) guided by Railway.
3. Once HTTPS issuance is complete, FE calls `VITE_API_URL=https://api-hashcredit.studioliq.com`.

## 7) Post-deployment verification (checklist)

API:

1. Verify that `GET /health` returns 200.
2. Verify that the API URL is correct in FE.
3. `X-API-Key: <API_TOKEN>` is required when calling the operational endpoint.

Worker:

1. Check whether `Loaded N watched addresses` is displayed in the log.
2. Make sure there are no Postgres connection errors.
3. (Demo) Detect testnet payout coming to the watched address and check whether proof submission is in progress.

## 8) Monorepo precautions (Railway)

1. If the service root directory in Railway is incorrectly set (repo root, etc.), the build may be messed up.
2. When using Railway Config as Code (`railway.toml`):
- **Config file path does not follow the Root Directory.**
- If set, it must be specified as an “absolute path” such as `/offchain/api/railway.toml`.
- This project is basically Dockerfile-based deployment, so it can be deployed without a separate `railway.toml`.
