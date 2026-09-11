# HashCredit API (`offchain/api`)

FastAPI API for read/verification tasks used by the frontend.  
On-chain transactions are wallet-side only.

## Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Service/RPC health |
| `GET` | `/btc/address-history` | BTC address history (indexer) |
| `POST` | `/spv/build-proof` | Build SPV proof bytes (read-only) |
| `POST` | `/checkpoint/build` | Build checkpoint payload for wallet tx |
| `POST` | `/claim/start` | Create claim message/token |
| `POST` | `/claim/complete` | Verify signatures and return derived hashes (no tx) |

## Wallet-only policy

- Removed server-side write flow:
  - no server-side `submitPayout`
  - no server-side `setCheckpoint`
  - no server-side `setBorrowerPubkeyHash`
  - no server-side `registerBorrower`
- API does not send EVM transactions.

## Configuration

```bash
cp .env.example .env
```

Important variables:

- `BITCOIN_RPC_URL`
- `BITCOIN_RPC_USER` / `BITCOIN_RPC_PASSWORD` (optional)
- `BTC_INDEXER_BASE_URL`
- `EVM_RPC_URL` (health checks / claim context)
- `CHAIN_ID`
- `ALLOWED_ORIGINS`
- `BORROWER_MAPPING_MODE`
- `CLAIM_SECRET` (required for claim mode)

## Run

```bash
cd offchain/api
pip install -e .
hashcredit-api
```

Or:

```bash
uvicorn hashcredit_api.main:app --host 127.0.0.1 --port 8000
```

## Example calls

Build checkpoint payload:

```bash
curl -H "Content-Type: application/json" \
  -X POST http://localhost:8000/checkpoint/build \
  -d '{"height": 4842343}'
```

Build SPV proof:

```bash
curl -H "Content-Type: application/json" \
  -X POST http://localhost:8000/spv/build-proof \
  -d '{
    "txid": "e4c6...",
    "output_index": 0,
    "checkpoint_height": 4842333,
    "target_height": 4842343,
    "borrower": "0x..."
  }'
```

Claim verify flow:

```bash
curl -H "Content-Type: application/json" \
  -X POST http://localhost:8000/claim/start \
  -d '{"borrower":"0x...","btc_address":"bc1q..."}'
```

```bash
curl -H "Content-Type: application/json" \
  -X POST http://localhost:8000/claim/complete \
  -d '{
    "claim_token":"...",
    "evm_signature":"0x...",
    "btc_signature":"<base64>",
    "dry_run": true
  }'
```
