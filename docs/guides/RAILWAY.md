# HashCredit Railway Deployment Guide

This guide covers deploying HashCredit offchain components to [Railway](https://railway.app).

## Architecture Overview

Railway deployment consists of three services:

1. **API Service** (`offchain/api`) - FastAPI server for frontend integration
2. **Worker Service** (`offchain/prover`) - SPV relayer that watches Bitcoin and submits proofs (**recommended**)
3. **PostgreSQL** - Railway managed database for worker deduplication (recommended)

### Choose One Worker Mode (Do Not Run Both)

HashCredit supports two mutually exclusive verification modes at the contract level:

- **SPV mode (production)**: `HashCreditManager.verifier` points to `BtcSpvVerifier`
- **MVP mode (demo)**: `HashCreditManager.verifier` points to `RelayerSigVerifier`

On Railway, run **exactly one** worker for a given `HashCreditManager` deployment:

- If your manager uses **SPV**, run `hashcredit-prover run-relayer`
- If your manager uses **MVP**, run `hashcredit-relayer run`

Running both against the same manager wastes gas and produces noisy failures (only one proof format will be accepted).

```
┌─────────────────┐     ┌─────────────────┐
│    Frontend     │────▶│   API Service   │
│   (Vercel)      │     │  (hashcredit-   │
└─────────────────┘     │     api)        │
                        └────────┬────────┘
                                 │
                        ┌────────▼────────┐
                        │   PostgreSQL    │
                        │   (Railway)     │
                        └────────┬────────┘
                                 │
┌─────────────────┐     ┌────────▼────────┐
│  Bitcoin Core   │◀───▶│ Worker Service  │
│     (RPC)       │     │ (hashcredit-    │
└─────────────────┘     │    prover)      │
                        └─────────────────┘
```

---

## Prerequisites

- Railway account (https://railway.app)
- Bitcoin Core RPC access (testnet or mainnet)
- Deployed HashCredit contracts (see DEPLOY.md)
- Private key for transaction signing

---

## Step 1: Create Railway Project

1. Go to https://railway.app/new
2. Create a new empty project
3. Name it (e.g., "hashcredit-offchain")

---

## Step 2: Add PostgreSQL

1. Click "New" → "Database" → "Add PostgreSQL"
2. Railway automatically creates `DATABASE_URL` variable
3. Note: The URL format is `postgres://...` (Railway converts this automatically)

Why Postgres?
- The SPV worker uses it to persist deduplication state across restarts.
- Without it, you risk re-submitting already-processed payouts after redeploys/crashes.

---

## Step 3: Deploy API Service

### 3.1 Create Service

1. Click "New" → "GitHub Repo" or "Empty Service"
2. If using GitHub:
   - Connect your repo
   - Set root directory to `offchain/api`
3. If using empty service:
   - Deploy manually via Railway CLI

### 3.2 Configure Environment Variables

Add these variables in Railway service settings:

```bash
# Server (Railway sets PORT automatically)
HOST=0.0.0.0

# Authentication (REQUIRED for production)
API_TOKEN=<generate-secure-random-token>

# CORS (add your frontend domain)
ALLOWED_ORIGINS=["https://your-app.vercel.app","http://localhost:3000"]

# Bitcoin RPC
BITCOIN_RPC_URL=http://your-bitcoin-node:18332
BITCOIN_RPC_USER=rpcuser
BITCOIN_RPC_PASSWORD=<your-rpc-password>

# EVM (Creditcoin testnet)
EVM_RPC_URL=https://rpc.cc3-testnet.creditcoin.network
CHAIN_ID=102031
PRIVATE_KEY=<your-private-key>

# Contracts
HASH_CREDIT_MANAGER=0x...
CHECKPOINT_MANAGER=0x...
BTC_SPV_VERIFIER=0x...
```

### 3.3 Build Configuration

Railway auto-detects Python. Ensure `pyproject.toml` exists.

This repo also includes a `Dockerfile` in `offchain/api` for more deterministic builds.

Build command (if needed):
```bash
pip install -e .
```

Start command:
```bash
python -m hashcredit_api.main
```

### 3.4 Verify Deployment

Check health endpoint:
```bash
curl https://your-api.railway.app/health
```

Expected response:
```json
{
  "status": "ok",
  "version": "0.1.0",
  "bitcoin_rpc": true,
  "evm_rpc": true,
  "contracts": {
    "hash_credit_manager": "0x...",
    "checkpoint_manager": "0x...",
    "btc_spv_verifier": "0x..."
  }
}
```

---

## Step 4: Deploy Worker Service

### 4.0 Pick the Worker Type

Use **SPV worker** unless you are intentionally running the MVP demo stack.

To confirm which mode your deployed manager is using, read the on-chain `verifier()` address:

```bash
cast call $HASH_CREDIT_MANAGER "verifier()(address)" --rpc-url $EVM_RPC_URL
```

### 4.1 Create Service

1. Click "New" → "GitHub Repo" or "Empty Service"
2. Set root directory based on the mode you chose:
   - **SPV**: `offchain/prover`
   - **MVP**: `offchain/relayer`

Note: `offchain/prover` and `offchain/relayer` both include a `Dockerfile` for deterministic builds. If you use Dockerfile-based deploys, you typically don't need to set a custom build/start command in Railway.

### 4.2 Prepare Addresses File

The SPV worker needs a JSON array of watched addresses.

You can provide it via **one** of these options:

1) **Environment variable** (recommended for small lists)
   - `ADDRESSES_JSON='[{"btc_address":"tb1q...","borrower":"0x...","enabled":true}]'`
   - or `ADDRESSES_JSON_B64=<base64 JSON>` (recommended if you hit quoting issues)

2) **File** mounted into the service
   - Set `ADDRESSES_FILE=/app/addresses.json` and mount/provide the file

Example `addresses.json`:

```json
[
  {
    "btc_address": "tb1q...",
    "borrower": "0x1234567890123456789012345678901234567890",
    "enabled": true
  }
]
```

Options:
- **Volume mount**: Store in Railway volume
- **Config file**: Include in repo (not recommended for sensitive data)
- **Environment variable**: Store as JSON or base64 encoded JSON

### 4.3 Configure Environment Variables

#### SPV Worker (Recommended)

```bash
# Database (shared with API via Railway reference)
DATABASE_URL=${{Postgres.DATABASE_URL}}

# Bitcoin RPC
BITCOIN_RPC_URL=http://your-bitcoin-node:18332
BITCOIN_RPC_USER=rpcuser
BITCOIN_RPC_PASSWORD=<your-rpc-password>

# EVM
EVM_RPC_URL=https://rpc.cc3-testnet.creditcoin.network
CHAIN_ID=102031
PRIVATE_KEY=<your-private-key>

# Contracts
HASH_CREDIT_MANAGER=0x...
CHECKPOINT_MANAGER=0x...

# Addresses input (pick ONE)
ADDRESSES_FILE=/app/addresses.json
# ADDRESSES_JSON='[{"btc_address":"tb1q...","borrower":"0x...","enabled":true}]'
# ADDRESSES_JSON_B64=<base64>

# Optional tuning (you can also use RELAYER_ARGS instead)
SPV_CONFIRMATIONS=6
SPV_POLL_INTERVAL=60
# SPV_RUN_ONCE=true
```

### 4.4 Start Command

#### SPV Worker (Recommended)

```bash
sh ./start-worker.sh
```

Or (legacy) run the CLI directly:
```bash
python -m hashcredit_prover.cli run-relayer ${ADDRESSES_FILE}
```

#### MVP Worker (Demo Only)

If you deployed the MVP verifier (`RelayerSigVerifier`), run the legacy relayer instead:

```bash
python -m hashcredit_relayer.cli run
```

Minimum environment (MVP relayer uses a Bitcoin API source rather than Bitcoin Core RPC):

```bash
BITCOIN_API_URL=https://mempool.space/testnet/api
RPC_URL=https://rpc.cc3-testnet.creditcoin.network
CHAIN_ID=102031
PRIVATE_KEY=<evm-tx-signer-key>
RELAYER_PRIVATE_KEY=<relayer-signing-key>
HASH_CREDIT_MANAGER=0x...
VERIFIER=0x...   # RelayerSigVerifier address (must match manager.verifier)
```

---

## Step 5: Database Migration

The database schema is auto-created on first connection. No migration needed.

To verify tables exist, connect via Railway CLI:

```bash
railway connect postgres
\dt
```

Expected tables:
- `pending_payouts`
- `submitted_payouts`
- `processed_payouts` (relayer dedupe)

---

## Environment Variables Reference

### API Service

| Variable | Required | Description |
|----------|----------|-------------|
| `PORT` | Auto | Railway sets automatically |
| `HOST` | Yes | Set to `0.0.0.0` for Railway |
| `API_TOKEN` | Yes | Authentication token |
| `ALLOWED_ORIGINS` | Recommended | CORS origins (JSON array) |
| `BITCOIN_RPC_URL` | Yes | Bitcoin Core RPC endpoint |
| `BITCOIN_RPC_USER` | Depends | RPC username |
| `BITCOIN_RPC_PASSWORD` | Depends | RPC password |
| `EVM_RPC_URL` | Yes | EVM RPC endpoint |
| `CHAIN_ID` | Yes | EVM chain ID |
| `PRIVATE_KEY` | Yes | Transaction signing key |
| `HASH_CREDIT_MANAGER` | Yes | Manager contract address |
| `CHECKPOINT_MANAGER` | Yes | Checkpoint contract address |
| `BTC_SPV_VERIFIER` | Yes | SPV verifier contract address |

### Worker Service

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes | PostgreSQL connection URL |
| `BITCOIN_RPC_URL` | Yes | Bitcoin Core RPC endpoint |
| `BITCOIN_RPC_USER` | Depends | RPC username |
| `BITCOIN_RPC_PASSWORD` | Depends | RPC password |
| `EVM_RPC_URL` | Yes | EVM RPC endpoint |
| `CHAIN_ID` | Yes | EVM chain ID |
| `PRIVATE_KEY` | Yes | Transaction signing key |
| `HASH_CREDIT_MANAGER` | Yes | Manager contract address |
| `CHECKPOINT_MANAGER` | Yes | Checkpoint contract address |
| `ADDRESSES_FILE` | Recommended | Path to watched addresses JSON (default: `/app/addresses.json`) |
| `ADDRESSES_JSON` | Optional | Watched addresses JSON array (string) |
| `ADDRESSES_JSON_B64` | Optional | Base64-encoded watched addresses JSON array |
| `SPV_CONFIRMATIONS` | Optional | Required confirmations (default: 6) |
| `SPV_POLL_INTERVAL` | Optional | Poll interval in seconds (default: 60) |
| `SPV_RUN_ONCE` | Optional | Run once and exit (default: false) |
| `RELAYER_ARGS` | Optional | Extra CLI args appended to `run-relayer` |

---

## Security Checklist

Before deploying to production:

- [ ] `API_TOKEN` is set to a strong random value (32+ chars)
- [ ] `PRIVATE_KEY` is stored in Railway secrets (not in repo)
- [ ] `BITCOIN_RPC_PASSWORD` is stored in Railway secrets
- [ ] `ALLOWED_ORIGINS` only includes your frontend domains
- [ ] API service is not accessible without token (test with curl)
- [ ] Worker logs don't expose sensitive data

### Generating Secure Tokens

```bash
# Generate API token
openssl rand -hex 32

# Output: 64-character hex string
```

---

## Monitoring & Logs

### View Logs

Railway dashboard → Service → Logs

Or via CLI:
```bash
railway logs -s api
railway logs -s worker
```

### Health Monitoring

Set up Railway's built-in health checks:
- **API**: HTTP check on `/health`
- **Worker**: Process liveness (auto)

### Alerts

Configure Railway notifications for:
- Deployment failures
- Service crashes
- High memory usage

---

## Troubleshooting

### API returns 503

Check:
1. Bitcoin RPC connectivity
2. EVM RPC connectivity
3. Environment variables set correctly

### Worker not processing payouts

Check:
1. `addresses.json` file exists and is valid JSON
2. Checkpoint is registered on-chain
3. Bitcoin transactions have enough confirmations

### Database connection errors

Check:
1. `DATABASE_URL` is set (use Railway variable reference `${{Postgres.DATABASE_URL}}`)
2. PostgreSQL service is running

### "No suitable checkpoint" warning

The checkpoint is too old. Register a new checkpoint:
```bash
hashcredit-prover set-checkpoint <recent-height> --checkpoint-manager 0x...
```

---

## Costs

Estimated Railway costs (as of 2024):

| Resource | Estimate |
|----------|----------|
| API Service (Hobby) | ~$5/month |
| Worker Service (Hobby) | ~$5/month |
| PostgreSQL (500MB) | Free tier |
| **Total** | ~$10/month |

Note: Production workloads may require Pro plan ($20/service/month).

---

## Related Docs

- [DEPLOY.md](./DEPLOY.md) - Contract deployment
- [LOCAL.md](./LOCAL.md) - Local development setup
- [../threat-model.md](../threat-model.md) - Security considerations
