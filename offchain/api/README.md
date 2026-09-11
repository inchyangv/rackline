# HashCredit API

HTTP API bridge for the HashCredit frontend to interact with Bitcoin Core and the prover.

## Features

- **SPV Proof Building**: Build SPV proofs from Bitcoin transaction IDs
- **Checkpoint Management**: Register Bitcoin block checkpoints on-chain
- **Borrower Management**: Set borrower Bitcoin pubkey hashes
- **Proof Submission**: Submit proofs to HashCreditManager contract

## Installation

```bash
cd offchain/api
pip install -e .
```

For development:
```bash
pip install -e ".[dev]"
```

## Configuration

Copy the example environment file:
```bash
cp .env.example .env
```

Edit `.env` with your configuration:

| Variable | Description | Default |
|----------|-------------|---------|
| `HOST` | API bind address | `127.0.0.1` |
| `PORT` | API port | `8000` |
| `DEBUG` | Enable debug mode | `false` |
| `API_TOKEN` | Authentication token (optional) | - |
| `BITCOIN_RPC_URL` | Bitcoin Core RPC URL | `http://127.0.0.1:18332` |
| `BITCOIN_RPC_USER` | Bitcoin RPC username | - |
| `BITCOIN_RPC_PASSWORD` | Bitcoin RPC password | - |
| `EVM_RPC_URL` | Creditcoin RPC URL | `http://localhost:8545` |
| `CHAIN_ID` | EVM chain ID | `102031` |
| `PRIVATE_KEY` | Private key for signing | - |
| `HASH_CREDIT_MANAGER` | Contract address | - |
| `CHECKPOINT_MANAGER` | Contract address | - |
| `BTC_SPV_VERIFIER` | Contract address | - |

## Usage

### Start the API Server

```bash
hashcredit-api
```

Or with uvicorn directly:
```bash
uvicorn hashcredit_api.main:app --host 127.0.0.1 --port 8000
```

### API Documentation

Once running, visit:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## Endpoints

### Health Check

```bash
GET /health
```

Returns service status and RPC connectivity.

### Build SPV Proof

```bash
POST /spv/build-proof
Content-Type: application/json

{
  "txid": "abc123...",
  "output_index": 0,
  "checkpoint_height": 2500000,
  "target_height": 2500006,
  "borrower": "0x1234..."
}
```

Returns ABI-encoded proof hex for contract submission.

### Submit Proof

```bash
POST /spv/submit
Content-Type: application/json

{
  "proof_hex": "0x...",
  "dry_run": false
}
```

Submits proof to HashCreditManager.submitPayout().

### Set Checkpoint

```bash
POST /checkpoint/set
Content-Type: application/json

{
  "height": 2500000,
  "dry_run": false
}
```

Registers a Bitcoin block checkpoint on CheckpointManager.

### Set Borrower Pubkey Hash

```bash
POST /borrower/set-pubkey-hash
Content-Type: application/json

{
  "borrower": "0x1234...",
  "btc_address": "tb1q...",
  "dry_run": false
}
```

Registers borrower's Bitcoin pubkey hash on BtcSpvVerifier.

## Authentication

By default, authentication is disabled for local development (127.0.0.1).

To enable authentication:
1. Set `API_TOKEN` in `.env`
2. Include token in requests via:
   - Header: `X-API-Key: your-token`
   - Query param: `?api_key=your-token`

## Security Notes

1. **Local Only by Default**: The API binds to `127.0.0.1` by default
2. **Private Key**: Never commit your private key; use environment variables
3. **CORS**: Configure `ALLOWED_ORIGINS` for your frontend domain
4. **Token Auth**: Enable `API_TOKEN` for production deployments

## Development

Run with auto-reload:
```bash
DEBUG=true hashcredit-api
```

Run tests:
```bash
pytest
```

## Integration with Frontend

The frontend can call this API to:

1. **Build proofs** without needing Bitcoin Core access:
   ```javascript
   const response = await fetch('http://localhost:8000/spv/build-proof', {
     method: 'POST',
     headers: { 'Content-Type': 'application/json' },
     body: JSON.stringify({
       txid: 'abc123...',
       output_index: 0,
       checkpoint_height: 2500000,
       target_height: 2500006,
       borrower: '0x1234...'
     })
   });
   const { proof_hex } = await response.json();
   ```

2. **Submit the proof** (or copy hex for manual submission):
   ```javascript
   // Option A: Submit via API (requires private key on server)
   await fetch('http://localhost:8000/spv/submit', {
     method: 'POST',
     body: JSON.stringify({ proof_hex })
   });

   // Option B: Copy proof_hex and submit via MetaMask in frontend
   ```
