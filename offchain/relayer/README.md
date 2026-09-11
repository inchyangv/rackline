# HashCredit Relayer Utility

This package is a standalone EIP-712 signer utility kept for compatibility experiments.

The active HashCredit runtime path uses:
- `offchain/api` for payload/proof building and verification
- `offchain/prover` for SPV worker submission

## Installation

```bash
# from this package directory
pip install -e .
```

## Commands

```bash
hashcredit-relayer run --help
hashcredit-relayer version
```

## Configuration

Copy `.env.example` to `.env` and configure:
- `BITCOIN_API_URL`
- `RPC_URL`
- `RELAYER_PRIVATE_KEY`
- `HASH_CREDIT_MANAGER`

## Development

```bash
pytest
mypy hashcredit_relayer
ruff check hashcredit_relayer
```
