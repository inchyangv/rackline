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
├── rpc.py           # Bitcoin RPC client
├── evm.py           # EVM/Creditcoin contract interactions
├── proof_builder.py # Main proof generation logic
└── cli.py           # Command-line interface
```
