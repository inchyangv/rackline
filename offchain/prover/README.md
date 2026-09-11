# HashCredit Prover

Bitcoin SPV Proof Builder for HashCredit. Generates Merkle inclusion proofs for Bitcoin transactions to be verified on-chain by the `BtcSpvVerifier` contract.

## Installation

```bash
cd offchain/prover
pip install -e .
```

For development:
```bash
pip install -e ".[dev]"
```

## Configuration

Set environment variables or use command-line options:

```bash
export BITCOIN_RPC_URL=http://localhost:8332
export BITCOIN_RPC_USER=your_user
export BITCOIN_RPC_PASSWORD=your_password
```

## Usage

### Build a proof

```bash
hashcredit-prover build-proof \
    <txid> \
    <output_index> \
    <checkpoint_height> \
    <target_height> \
    <borrower_address>
```

Example:
```bash
hashcredit-prover build-proof \
    abc123def456...txid... \
    0 \
    800000 \
    800006 \
    0x1234567890123456789012345678901234567890 \
    --output proof.json
```

### Get ABI-encoded proof for contract

```bash
hashcredit-prover build-proof \
    abc123def456...txid... \
    0 \
    800000 \
    800006 \
    0x1234...borrower \
    --hex
```

### Submit proof to HashCreditManager

Build and submit an SPV proof in one command:

```bash
hashcredit-prover submit-proof \
    <txid> <output_index> <borrower_address> \
    --checkpoint <checkpoint_height> \
    --target <target_height> \
    --manager $HASH_CREDIT_MANAGER
```

Required environment variables (or CLI options):
- `BITCOIN_RPC_URL`: Bitcoin Core RPC URL
- `BITCOIN_RPC_USER`: RPC username
- `BITCOIN_RPC_PASSWORD`: RPC password
- `HASH_CREDIT_MANAGER`: Contract address (or use `--manager`)
- `EVM_RPC_URL`: Creditcoin/EVM RPC URL
- `PRIVATE_KEY`: Transaction signer private key

Example:
```bash
# Dry run (build proof but don't submit)
hashcredit-prover submit-proof \
    abc123...txid... 0 0x1234...borrower \
    --checkpoint 2500000 \
    --target 2500006 \
    --manager 0xABC123... \
    --dry-run

# Get hex-encoded proof only (no submission)
hashcredit-prover submit-proof \
    abc123...txid... 0 0x1234...borrower \
    --checkpoint 2500000 \
    --target 2500006 \
    --hex-only

# Submit to chain
hashcredit-prover submit-proof \
    abc123...txid... 0 0x1234...borrower \
    --checkpoint 2500000 \
    --target 2500006 \
    --manager 0xABC123... \
    --private-key $PRIVATE_KEY
```

### Verify a proof locally

```bash
hashcredit-prover verify-local proof.json
```

### Set a checkpoint

Register a Bitcoin block as a checkpoint on the `CheckpointManager` contract:

```bash
hashcredit-prover set-checkpoint <height> \
    --checkpoint-manager 0x1234...contract_address
```

Required environment variables (or CLI options):
- `BITCOIN_RPC_URL`: Bitcoin Core RPC URL (default: `http://localhost:18332` for testnet)
- `BITCOIN_RPC_USER`: RPC username
- `BITCOIN_RPC_PASSWORD`: RPC password
- `CHECKPOINT_MANAGER`: Contract address (or use `--checkpoint-manager`)
- `EVM_RPC_URL`: Creditcoin/EVM RPC URL
- `CHAIN_ID`: Chain ID (default: 102031 for Creditcoin testnet)
- `PRIVATE_KEY`: Deployer private key

Example:
```bash
# Dry run (show data without sending)
hashcredit-prover set-checkpoint 2500000 \
    --checkpoint-manager 0xABC123... \
    --dry-run

# Send transaction
hashcredit-prover set-checkpoint 2500000 \
    --checkpoint-manager 0xABC123... \
    --private-key $PRIVATE_KEY
```

### Set borrower's BTC pubkey hash

Register a borrower's Bitcoin address on the `BtcSpvVerifier` contract for SPV proof verification:

```bash
hashcredit-prover set-borrower-pubkey-hash \
    <borrower_evm_address> \
    <btc_address> \
    --spv-verifier 0x1234...contract_address
```

Supported Bitcoin address formats:
- P2WPKH (bech32): `tb1q...` (testnet), `bc1q...` (mainnet)
- P2PKH (base58check): `m...`/`n...` (testnet), `1...` (mainnet)

Required environment variables (or CLI options):
- `BTC_SPV_VERIFIER`: Contract address (or use `--spv-verifier`)
- `EVM_RPC_URL`: Creditcoin/EVM RPC URL
- `CHAIN_ID`: Chain ID (default: 102031)
- `PRIVATE_KEY`: Deployer private key

Example:
```bash
# Dry run
hashcredit-prover set-borrower-pubkey-hash \
    0x1234567890123456789012345678901234567890 \
    tb1qw508d6qejxtdg4y5r3zarvary0c5xw7kxpjzsx \
    --spv-verifier 0xABC123... \
    --dry-run

# Send transaction
hashcredit-prover set-borrower-pubkey-hash \
    0x1234567890123456789012345678901234567890 \
    tb1qw508d6qejxtdg4y5r3zarvary0c5xw7kxpjzsx \
    --spv-verifier 0xABC123... \
    --private-key $PRIVATE_KEY
```

### Run the SPV relayer

Automatically watch Bitcoin addresses and submit proofs:

```bash
hashcredit-prover run-relayer addresses.json \
    --manager $HASH_CREDIT_MANAGER \
    --checkpoint-manager $CHECKPOINT_MANAGER
```

The addresses file should be a JSON array:
```json
[
    {"btc_address": "tb1q...", "borrower": "0x1234...", "enabled": true},
    {"btc_address": "tb1q...", "borrower": "0x5678...", "enabled": true}
]
```

Options:
- `--confirmations`: Required confirmations (default: 6)
- `--poll-interval`: Poll interval in seconds (default: 60)
- `--db`: SQLite database path for dedupe (default: relayer.db)
- `--once`: Run once and exit (for testing)

The relayer will:
1. Scan new blocks for transactions to watched addresses
2. Wait for required confirmations
3. Automatically select a suitable checkpoint
4. Build SPV proof and submit to HashCreditManager
5. Track submitted payouts in SQLite to prevent double-submission

## Requirements

- Python 3.11+
- Access to Bitcoin Core RPC (for real proofs)
  - Requires `txindex=1` in bitcoin.conf for arbitrary transaction lookup

## Proof Structure

The generated proof contains:

- `checkpointHeight`: Block height of the trusted checkpoint
- `headers`: Array of 80-byte block headers from checkpoint+1 to target
- `rawTx`: Full serialized Bitcoin transaction
- `merkleProof`: Array of 32-byte sibling hashes for Merkle inclusion
- `txIndex`: Transaction position in the block
- `outputIndex`: Which output is the payout (vout)
- `borrower`: Borrower's EVM address

## Testing

```bash
pytest tests/ -v
```

## Architecture

```
hashcredit_prover/
├── __init__.py
├── bitcoin.py       # Bitcoin data structures and utilities
├── address.py       # Bitcoin address decoding (bech32/base58)
├── rpc.py           # Bitcoin RPC client
├── evm.py           # EVM/Creditcoin contract interactions
├── proof_builder.py # Main proof generation logic
├── watcher.py       # Bitcoin address monitoring
├── relayer.py       # SPV relayer (auto proof submission)
└── cli.py           # Command-line interface
```
