# HashCredit Prover (`offchain/prover`)

CLI tool and background worker that builds Bitcoin SPV proofs (header chain + Merkle inclusion) and submits them on-chain to the HashCredit protocol.

## Commands

| Command | Description |
|---------|-------------|
| `build-proof` | Generate an SPV proof for a given txid/vout/height |
| `submit-proof` | Build proof and submit to `HashCreditManager.submitPayout` |
| `set-checkpoint` | Register a block header checkpoint in `CheckpointManager` |
| `set-borrower-pubkey-hash` | Register borrower (EVM) ↔ BTC address mapping in `BtcSpvVerifier` |
| `run-relayer` | Poll watched addresses and auto-build/submit proofs (worker mode) |

## Installation

```bash
cd offchain/prover
pip install -e .

# With dev dependencies
pip install -e ".[dev]"
```

## Configuration

```bash
cp .env.example .env
```

For Railway deployment, set the same variables in Railway Variables/Secrets instead of `.env`.

### Required Variables

| Variable | Description |
|----------|-------------|
| `BITCOIN_RPC_URL` | Bitcoin RPC endpoint (e.g., `https://bitcoin-testnet-rpc.publicnode.com`) |
| `EVM_RPC_URL` | HashKey Chain RPC endpoint |
| `CHAIN_ID` | Chain ID (default: `133`) |
| `PRIVATE_KEY` | Operator key for signing on-chain transactions |
| `HASH_CREDIT_MANAGER` | HashCreditManager contract address |
| `CHECKPOINT_MANAGER` | CheckpointManager contract address |

### Worker-Specific Variables

| Variable | Description |
|----------|-------------|
| `ADDRESSES_JSON_B64` | Base64-encoded JSON of watched addresses (recommended) |
| `ADDRESSES_JSON` | Raw JSON string of watched addresses (alternative) |
| `ADDRESSES_FILE` | Path to addresses JSON file (not recommended for containers) |
| `SPV_CONFIRMATIONS` | Required confirmations (default: `6`) |
| `SPV_POLL_INTERVAL` | Poll interval in seconds (default: `60`) |
| `SPV_RUN_ONCE` | Run one cycle and exit (default: `false`) |

## SPV Proof Constraints

For gas efficiency, the header chain length in each proof is limited. Keep the difference between `checkpoint_height` and `target_height` within **1–144 blocks**.

## Usage

### Register a checkpoint

```bash
hashcredit-prover set-checkpoint <height> \
  --checkpoint-manager $CHECKPOINT_MANAGER
```

### Register borrower BTC address

```bash
hashcredit-prover set-borrower-pubkey-hash \
  <borrower_evm> <btc_address> \
  --spv-verifier $BTC_SPV_VERIFIER
```

Supported address formats:
- Bech32 P2WPKH: testnet `tb1q...`, mainnet `bc1q...`
- Base58 P2PKH: testnet `m.../n...`, mainnet `1...`

### Build proof (hex output)

```bash
hashcredit-prover build-proof \
  <txid> <output_index> <checkpoint_height> <target_height> <borrower_evm> \
  --hex
```

### Build and submit proof

```bash
hashcredit-prover submit-proof \
  <txid> <output_index> <borrower_evm> \
  --checkpoint <checkpoint_height> \
  --target <target_height> \
  --manager $HASH_CREDIT_MANAGER
```

Options:
- `--dry-run` — Build proof without submitting
- `--hex-only` — Print proof hex without submitting

### Run worker (auto-detect and submit)

Prepare a JSON file of watched addresses:

```json
[
  {"btc_address": "tb1q...", "borrower": "0x1234...", "enabled": true}
]
```

Run locally:

```bash
hashcredit-prover run-relayer addresses.json \
  --manager $HASH_CREDIT_MANAGER \
  --checkpoint-manager $CHECKPOINT_MANAGER
```

For Railway, encode the address list as base64 and set `ADDRESSES_JSON_B64`:

```bash
base64 < addresses.json | tr -d '\n'
```

## Requirements

- Python 3.11+
- Bitcoin RPC access (`txindex=1` recommended for arbitrary txid lookups)
