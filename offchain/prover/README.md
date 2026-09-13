# Rackline workers

`hashcredit_prover.gpu` contains the Rackline v2 background services:

- `chain_indexer` projects finalized deployment logs and reconciles reorgs;
- `attestcoin_worker` fetches official proof artifacts, prepares pinned calldata, dispatches approved transactions, confirms native acceptance, and consumes evidence;
- `ingestion` and `backfill_native` collect and reconstruct bounded source history;
- `control_monitor` and `control_executor` observe payment-control state without granting authority;
- `reconcile_cash` compares source, in-flight, destination and allocated cash.

Install and run with the shared GPU package and PostgreSQL:

```bash
python -m pip install -e "offchain/gpu[dev]" -e "offchain/prover[dev]"

python -m hashcredit_prover.gpu.chain_indexer \
  --manifest config/attestcoin/cc3-testnet.sepolia.release.json \
  --deployment-id DEPLOYMENT_ULID --once

python -m hashcredit_prover.gpu.attestcoin_worker \
  --manifest config/attestcoin/cc3-testnet.sepolia.release.json \
  --deployment-id DEPLOYMENT_ULID \
  --sdk-cli offchain/attestcoin/dist/src/cli.js \
  --artifact-dir .artifacts/proofs --once
```

The proof service response is untrusted input. SDK readiness, transaction submission, native acceptance, economic consumption and destination cash are separate durable states. Without an operator-reviewed submission plan, the worker only fetches proof artifacts and has no signing credential.

`hashcredit_prover.cli` and the Bitcoin modules are retained as legacy prototype code. They are not an evidence path for Rackline v2.

## Tests

```bash
python -m pytest offchain/prover/tests offchain/gpu/tests/test_attestcoin_worker.py -q
```
