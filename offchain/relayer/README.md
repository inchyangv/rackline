# HashCredit Relayer

Bitcoin payout relayer for the HashCredit protocol.

## Overview

The relayer watches Bitcoin blockchain for payout transactions to registered borrowers and submits EIP-712 signed proofs to the HashCreditManager contract on Creditcoin (EVM).

## Installation

```bash
# From repository root
cd offchain/relayer
pip install -e .

# Or with dev dependencies
pip install -e ".[dev]"
```

## Usage

```bash
# Run the relayer
python -m hashcredit_relayer

# Or using the CLI
hashcredit-relayer run

# Show version
hashcredit-relayer version
```

## Configuration

Copy `.env.example` to `.env` and configure:

- `BITCOIN_API_URL`: Bitcoin data source (mempool.space API for MVP)
- `RPC_URL`: EVM RPC endpoint
- `RELAYER_PRIVATE_KEY`: Key for signing EIP-712 payloads
- `HASH_CREDIT_MANAGER`: Contract address

## Development

```bash
# Run tests
pytest

# Type check
mypy hashcredit_relayer

# Format
black hashcredit_relayer
ruff check hashcredit_relayer
```
