# HashCredit API (`offchain/api`)

It is a FastAPI-based HTTP API that allows the front-end to easily call **Bitcoin RPC / SPV proof generation / on-chain transaction transmission (operation key)**.

## What I do

- SPV proof creation: `POST /spv/build-proof`
- Checkpoint registration (on-chain): `POST /checkpoint/set`
- Register borrower BTC address (pubkeyHash) (on-chain): `POST /borrower/set-pubkey-hash`
- Borrower registration (on-chain): `POST /manager/register-borrower`
- Proof submission (on-chain): `POST /spv/submit`
- (Mainnet recommended) Registration based on borrower ownership proof: `POST /claim/start`, `POST /claim/complete`
- Health check: `GET /health`

## installation

```bash
cd offchain/api
pip install -e .
```

For development purposes:

```bash
pip install -e ".[dev]"
```

## Environment variables

```bash
cp .env.example .env
```

Important points:

- Setting `API_TOKEN` will cause **endpoints sending on-chain transactions** to require the `X-API-Key` header.
- Use `CLAIM_REQUIRE_API_TOKEN=true` to force a token to the claim endpoint.
- To use mainnet-level mapping, switch to `BORROWER_MAPPING_MODE=claim` and set `CLAIM_SECRET`.
- `ALLOWED_ORIGINS` is a **JSON array string**.
- Example: `["https://hashcredit.studioliq.com","http://localhost:5173"]`
- If Bitcoin RPC is a public endpoint (unauthenticated), `BITCOIN_RPC_USER/PASSWORD` can be left blank.

## execution

```bash
hashcredit-api
```

or:

```bash
uvicorn hashcredit_api.main:app --host 127.0.0.1 --port 8000
```

API documentation:

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## certification

1. Set `API_TOKEN` in `.env` (recommended: always set)
2. Add `X-API-Key: <API_TOKEN>` to all requests

yes:

```bash
curl -H "X-API-Key: <API_TOKEN>" http://localhost:8000/health
```

## Endpoint

### 1) Health check

```bash
curl -H "X-API-Key: <API_TOKEN>" http://localhost:8000/health
```

### 2) Checkpoint registration (on-chain)

```bash
curl -H "X-API-Key: <API_TOKEN>" \
  -H "Content-Type: application/json" \
  -X POST http://localhost:8000/checkpoint/set \
  -d '{"height": 4842343, "dry_run": false}'
```

### 3) Register borrower BTC address (pubkeyHash) (on-chain)

```bash
curl -H "X-API-Key: <API_TOKEN>" \
  -H "Content-Type: application/json" \
  -X POST http://localhost:8000/borrower/set-pubkey-hash \
  -d '{"borrower":"0x...","btc_address":"tb1q...","dry_run": false}'
```

### 4) Borrower registration (on-chain, Manager)

This endpoint calculates `btcPayoutKeyHash = keccak256(utf8(btc_address))`,
Call `HashCreditManager.registerBorrower(borrower, btcPayoutKeyHash)`.

```bash
curl -H "X-API-Key: <API_TOKEN>" \
  -H "Content-Type: application/json" \
  -X POST http://localhost:8000/manager/register-borrower \
  -d '{"borrower":"0x...","btc_address":"tb1q...","dry_run": false}'
```

### 5) SPV proof generation

```bash
curl -H "X-API-Key: <API_TOKEN>" \
  -H "Content-Type: application/json" \
  -X POST http://localhost:8000/spv/build-proof \
  -d '{
    "txid": "e4c6...",
    "output_index": 0,
    "checkpoint_height": 4842333,
    "target_height": 4842343,
    "borrower": "0x..."
  }'
```

### 6) Proof submission (on-chain)

```bash
curl -H "X-API-Key: <API_TOKEN>" \
  -H "Content-Type: application/json" \
  -X POST http://localhost:8000/spv/submit \
  -d '{"proof_hex":"0x...","dry_run": false}'
```

### 7) (Mainnet recommended) Registration based on borrower claim

Only used when `BORROWER_MAPPING_MODE=claim`.

This flow is designed so that the borrower submits the following:
- EVM signature: Sign message with `personal_sign`
- BTC signature: `signmessage` output (base64) signature from wallet
- The current implementation verifies BIP-137 style and operates only for address types (p2pkh/p2wpkh) supported by the repo.

1) Start claim:

```bash
curl -H "Content-Type: application/json" \
  -X POST http://localhost:8000/claim/start \
  -d '{"borrower":"0x...","btc_address":"bc1q..."}'
```

Sign the `message` in the response with **both your EVM wallet and your BTC wallet**.

2) Completion of claim (verification + on-chain registration):

```bash
curl -H "Content-Type: application/json" \
  -X POST http://localhost:8000/claim/complete \
  -d '{
    "claim_token":"...",
    "evm_signature":"0x...",
    "btc_signature":"<base64>",
    "dry_run": false
  }'
```

## Security/Operations Notes (Important)

- This API can transmit on-chain transactions using the operating key (`PRIVATE_KEY`), so when exposed to the outside world, it must:
- Set `API_TOKEN` strongly
- Restrict access with CORS/firewall/rate limit, etc.
- Borrower(EVM) <-> BTC address mapping allows arbitrary mapping attacks on the mainnet, so `BORROWER_MAPPING_MODE=claim` is recommended in production.
- Claim endpoints will not send on-chain transactions without a “valid signature”, but in production environments additional defenses such as ratelimiting/firewall/user authentication are required.
