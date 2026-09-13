# Railway Deployment Guide

This document describes how to deploy the Rackline (formerly HashCredit) off-chain services to Railway.

> **Naming (2026-09-14).** Repo: `github.com/inchyangv/rackline`. Deployment / service / project / domain
> identifiers are **Rackline** (`rackline-api`, `rackline-prover-legacy`, Vercel project `rackline`).
> Python package, CLI, contract and env-variable identifiers keep their legacy names (`hashcredit_api`,
> `hashcredit-prover`, `HashCreditManager`, `HASH_CREDIT_MANAGER`, `VITE_HASH_CREDIT_MANAGER`).
>
> **Status.** The previous deployment (`hashcredit.studioliq.com`, `api-hashcredit.studioliq.com`) was taken
> down by the owner on 2026-09-14. Nothing is deployed until a Rackline domain is chosen (see §6 and §9).
> The v2 GPU services (proof worker, connectors) are not part of this guide yet — GPU-053 adds them.

## Service Layout

| Component | Platform | Source |
|-----------|----------|--------|
| Frontend | Vercel | `apps/web` |
| API | Railway | `offchain/api` |
| Prover (Worker) | Railway | `offchain/prover` |
| Database | Railway Postgres | — |

Production domains (to be created — see §9):
- Frontend: `https://<rackline-domain>` (Vercel, project `rackline`)
- API: `https://api.<rackline-domain>` (Railway, service `rackline-api`)

## Prerequisites

1. A Railway account and workspace.
2. Permission to link this GitHub repo to Railway.
3. Secrets (`PRIVATE_KEY`, `CLAIM_SECRET`, etc.) — never commit these to git.

## Why Two Services?

This is a monorepo with Python (API + Worker) and Vite (Frontend). Railway does not auto-split it into multiple services from a single repo connection. You must create two services explicitly:

- **(Recommended)** Drag-and-drop the Compose file to create both services at once.
- **(Alternative)** Create two GitHub repo connections, each with a different Root Directory.
- **(Auto-staging)** The `offchain/api` and `offchain/prover` directories are registered as workspaces in the root `package.json`, so Railway may auto-detect the two packages as separate services on import — rename them to `rackline-api` and `rackline-prover-legacy`.

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
3. Verify two services appear: `rackline-api` and `rackline-prover-legacy`. Deploy the prover only if legacy v1 borrowers still need payout submission; the v2 product does not use it.

**Note:** Compose drag-and-drop creates the service structure only. To enable auto-deploy on push, connect each service to the GitHub repo separately.

## 2. Add Postgres

The prover worker requires a database for deduplication and state storage.

1. Add the Postgres plugin in the Railway project.
2. Connect the `DATABASE_URL` reference to:
   - `rackline-prover-legacy` (required only if that service is deployed)
   - `rackline-api` (optional today; the v2 GPU package `hashcredit_gpu` will require it — GPU-015/053)

The prover code automatically converts Railway's `postgres://` format to `postgresql://`.

## 3. Build Settings

Each service has its own Dockerfile:
- `offchain/api/Dockerfile`
- `offchain/prover/Dockerfile`

Set Root Directories in Railway:
- `rackline-api` → **repo root** (the root `Dockerfile` installs the local `hashcredit-gpu` package from `offchain/gpu` before the API; `offchain/api/Dockerfile` alone no longer builds since GPU-015)
- `rackline-prover-legacy` → `offchain/prover`

### (Optional) Config as Code

Service-specific `railway.toml` files are included:
- API: `offchain/api/railway.toml`
- Worker: `offchain/prover/railway.toml`

These limit `watchPatterns` to avoid unnecessary redeployments when unrelated files change (e.g., frontend changes should not redeploy the API).

**Important:** Railway Config file paths do not follow the Root Directory. You may need to set the absolute path in Service Settings:
- API: `/offchain/api/railway.toml`
- Worker: `/offchain/prover/railway.toml`

## 4. API Service Variables (`rackline-api`)

Set these in Railway → `rackline-api` → Variables/Secrets. Run the `production` profile: `API_PROFILE=production` (default) and **no** `ADMIN_PRIVATE_KEY` / `DEMO_ADMIN_PRIVATE_KEY` — the API refuses to start with either in production (GPU-001).

### Required

| Variable | Type | Description |
|----------|------|-------------|
| `ALLOWED_ORIGINS` | Variable | CORS origins as JSON array, e.g. `["https://<rackline-domain>"]` |
| `BITCOIN_RPC_URL` | Variable | Bitcoin RPC endpoint |
| `BITCOIN_RPC_USER` | Secret | Optional — for authenticated RPC |
| `BITCOIN_RPC_PASSWORD` | Secret | Optional — for authenticated RPC |
| `EVM_RPC_URL` | Variable | Creditcoin EVM RPC |
| `CHAIN_ID` | Variable | e.g., `102031` |

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

## 5. Worker Service Variables (`rackline-prover-legacy`)

Set these in Railway → `rackline-prover-legacy` → Variables/Secrets. Legacy v1 only.

### Required

| Variable | Type | Description |
|----------|------|-------------|
| `DATABASE_URL` | Reference | Reference Railway Postgres `DATABASE_URL` |
| `BITCOIN_RPC_URL` | Variable | Bitcoin RPC endpoint |
| `EVM_RPC_URL` | Variable | Creditcoin EVM RPC |
| `CHAIN_ID` | Variable | e.g., `102031` |
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

1. In Railway, add a custom domain `api.<rackline-domain>` under `rackline-api` → Networking/Domain.
2. Create the DNS record (CNAME to the Railway target) at the registrar.
3. Once HTTPS is provisioned, configure the frontend with `VITE_API_URL=https://api.<rackline-domain>` and add
   `https://<rackline-domain>` to the API's `ALLOWED_ORIGINS`.

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

## 9. Rackline domain and fresh deployment (2026-09-14 — executed)

Decision (owner, 2026-09-14): reuse the `studioliq.com` zone (GoDaddy DNS, `ns23/ns24.domaincontrol.com`).

| Surface | Domain | Platform | State (2026-09-14) |
| --- | --- | --- | --- |
| Web | `rackline.studioliq.com` | Vercel team `elouanics-projects`, project `rackline`, root `apps/web`, framework Vite, GitHub `inchyangv/rackline` connected (production branch `main`) | **Live** (2026-09-14 08:56 KST): DNS A record set, Let's Encrypt cert issued (`vercel certs issue` forced it), HTTP 200, title `Rackline` |
| API | `api-rackline.studioliq.com` | Railway workspace "Incheol Yang's Projects", project `rackline`, service `rackline-api` (root `railway.toml` → root `Dockerfile`, `API_PROFILE=production`, no admin key) | **Live** (2026-09-14 08:50 KST): CNAME + TXT set, cert issued, `GET /health` → `api_profile: production`, CORS allows `https://rackline.studioliq.com`, `/claim/register-and-grant` → 404. Deployed from the local checkout (`railway up`); GitHub auto-deploy not connected (Railway app could not see the renamed repo — attach in the Railway UI) |

DNS records to create at GoDaddy (zone `studioliq.com`):

| Type | Name | Value |
| --- | --- | --- |
| A | `rackline` | `76.76.21.21` (Vercel; a CNAME to `cname.vercel-dns.com` also works) |
| CNAME | `api-rackline` | `820l5mzl.up.railway.app` |
| TXT | `_railway-verify.api-rackline` | `railway-verify=a8aeb3d9dc65dbe7a56cb87e319da04b1fce041c19683566da5b3e7d592a70f1` |

Keep the old records. `hashcredit.studioliq.com` is attached to the Vercel project `rackline` as a **308 redirect** to `rackline.studioliq.com` (its existing CNAME already pointed at Vercel; verified 2026-09-14 09:00 KST), so links in the Spring submission, DoraHacks, Discord and CEIP mail keep working. `api-hashcredit.studioliq.com` still points at the retired Railway service and is dead; it was never a user-facing link. To revive it, re-point its CNAME to `820l5mzl.up.railway.app` and add it as a second domain on `rackline-api`.

Vercel `VITE_API_URL` (production + preview) = `https://api-rackline.studioliq.com`. Railway `ALLOWED_ORIGINS` includes `https://rackline.studioliq.com`. `CLAIM_SECRET` was generated with `openssl rand -hex 32` and stored only in Railway (never in the repo). The old `apps/web/.vercel` link (project `ctc-hashcredit`) was replaced by a repo-root `.vercel` link to `rackline` (gitignored).

Original checklist (kept for the next environment):

1. **Domain.** Register `rackline.<tld>` (on 2026-09-14 `.com`, `.io`, `.xyz` were already registered; `.co`
   was free; check `.finance` / `.credit` / `.capital` at the registrar). One apex for the web app, `api.` for
   the API. Keep the registrar's DNS or move to Vercel DNS — either works.
2. **Vercel.** `vercel login` → in `apps/web`: remove the old link (`rm -rf apps/web/.vercel`, it points at the
   retired `ctc-hashcredit` project) → `vercel link` → project name `rackline`, framework Vite, root
   `apps/web`. Environment (Production): `VITE_API_URL=https://api.<rackline-domain>`, contract addresses as in
   `apps/web/.env.example`, `VITE_API_PROFILE` unset (production). Add the apex domain and `www` redirect in
   Vercel → Domains and create the records Vercel prints (A `76.76.21.21` for the apex or CNAME
   `cname.vercel-dns.com` for `www`).
3. **Railway.** `railway login` → new project `rackline` → services from `railway-compose.yml` → root
   directories and variables per §3–§5 (`API_PROFILE=production`, no admin keys) → custom domain per §6.
4. **GitHub.** The repo is `inchyangv/rackline` (renamed 2026-09-14; old URLs redirect). Reconnect Vercel and
   Railway to the renamed repo so auto-deploys resume.
5. **Smoke test.** `GET https://api.<rackline-domain>/health` → `api_profile: production`; web loads on
   `https://<rackline-domain>`, every number is an on-chain read, the setup panel shows "Verify payout address"
   (no register step), footer commit matches `main`.
6. **Record.** Add the live URLs to `README.md` (Status) and `docs/gpu/execution/GPU-066.md`; update
   `docs/gpu/execution/ATTESTCOIN_GAP.md` C18 from UNVERIFIED_EXTERNAL to the checked state.
