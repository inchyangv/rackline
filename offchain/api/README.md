# Rackline API (`offchain/api`)

FastAPI API for read/verification tasks used by the frontend.  
On-chain transactions are wallet-side only.

> Package, service and signed-message identifiers keep their legacy `hashcredit*` / `HashCredit*` names; the product is Rackline (formerly HashCredit).

## Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Service/RPC health |
| `GET` | `/btc/address-history` | BTC address history (indexer) |
| `POST` | `/spv/build-proof` | Build SPV proof bytes (read-only) |
| `POST` | `/checkpoint/build` | Build checkpoint payload for wallet tx |
| `POST` | `/claim/start` | Create claim message/token |
| `POST` | `/claim/complete` | Verify signatures and return derived hashes (no tx) |
| `POST` | `/claim/extract-sig-params` | Extract on-chain params (pubKeyX/Y, btcMsgHash, v, r, s) from BIP-137 signature for `BtcSpvVerifier.claimBtcAddress()` |

## Wallet-only policy (production profile)

- Removed server-side write flow:
  - no server-side `submitPayout`
  - no server-side `setCheckpoint`
  - no server-side `setBorrowerPubkeyHash`
  - no server-side `registerBorrower` / `grantTestnetCredit`
- The production API process holds **no** signing key. `ADMIN_PRIVATE_KEY` is rejected at startup in
  every profile; `DEMO_ADMIN_PRIVATE_KEY` is rejected in production.
- `/claim/register-and-grant` does not exist in production (404).

## Testnet demo profile (`API_PROFILE=testnet_demo`, TEST_ONLY)

A separate profile mounts `hashcredit_api/demo.py`:

| Method | Path | Description |
|---|---|---|
| `POST` | `/claim/demo-auth-message` | Message the borrower signs to authorize its own demo registration |
| `POST` | `/claim/register-and-grant` | Guarded `registerBorrower` + capped `grantTestnetCredit` with `DEMO_ADMIN_PRIVATE_KEY` |

Guards before anything is signed: borrower EVM signature over a message bound to (borrower, BTC
address, chain id, manager, expiry); the BTC address must already be linked on-chain
(`BtcSpvVerifier.borrowerPubkeyHash`); RPC chain id must equal `CHAIN_ID` and be in
`DEMO_ALLOWED_CHAIN_IDS` (mainnet ids 102030/1 are always refused); the manager's stablecoin must be in
`DEMO_ALLOWED_STABLECOINS` (external stablecoins refused); amount ≤ `DEMO_GRANT_CAP`.
This path is a v1 testnet convenience only and is not part of the GPU production design (TICKET.md GPU-001).

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
- `API_PROFILE` (`production` default | `testnet_demo`)
- Demo profile only: `DEMO_ADMIN_PRIVATE_KEY`, `DEMO_ALLOWED_CHAIN_IDS` (JSON list, default `[102031, 31337]`),
  `DEMO_ALLOWED_STABLECOINS` (JSON list of TEST_ONLY token addresses; empty = demo grants refused),
  `DEMO_GRANT_CAP` (base units, default 1000e6), `DEMO_AUTH_TTL_SECONDS` (default 300)

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

Extract on-chain BTC signature params (for `claimBtcAddress`):

```bash
curl -H "Content-Type: application/json" \
  -X POST http://localhost:8000/claim/extract-sig-params \
  -d '{
    "message": "HashCredit: Link BTC to 0x...",
    "signature_b64": "<base64 BIP-137 signature>"
  }'
```
