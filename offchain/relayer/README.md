# hashcredit_relayer (legacy v1)

Standalone EIP-712 signer utility from the Rackline v1 (then HashCredit) Bitcoin-SPV prototype. It is kept for provenance and regression coverage only.

It is **not** part of the Rackline v2 GPU runtime. v2 has no relayer-signature evidence path: source facts enter through the official Attestcoin native verifier (`offchain/prover`, `offchain/attestcoin`), and the API never signs transactions. See the repository `README.md` and `TECH.md` §11.

## Install and run

```bash
# from this package directory
pip install -e .
hashcredit-relayer run --help
hashcredit-relayer version
```

Configuration comes from `.env` (copy `.env.example`): `BITCOIN_API_URL`, `RPC_URL`, `RELAYER_PRIVATE_KEY`, `HASH_CREDIT_MANAGER`.

## Development

```bash
pytest
mypy hashcredit_relayer
ruff check hashcredit_relayer
```
