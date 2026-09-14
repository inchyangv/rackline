# Rackline workers

`hashcredit_prover.gpu` contains the Rackline v2 background services. The package name keeps the legacy `hashcredit` identifier.

| Module | Responsibility |
| --- | --- |
| `chain_indexer` | Projects finalized deployment logs and reconciles reorgs |
| `attestcoin_worker` | Fetches official proof artifacts, prepares pinned calldata, dispatches reviewed transactions, confirms native acceptance, consumes evidence |
| `ingestion`, `backfill_native` | Collect and reconstruct bounded source history |
| `control_monitor`, `control_executor` | Observe and act on payment-control state without granting financial authority |
| `reconcile_cash` | Compares source, in-flight, destination, and allocated cash |
| `bootstrap_native` | Imports an existing TEST_ONLY deployment as metadata |

## Run

Requires the shared GPU package and PostgreSQL.

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

The proof-service response is untrusted input. SDK readiness, transaction submission, native acceptance, economic consumption, and destination cash are separate durable states. Without an operator-reviewed submission plan the worker only fetches proof artifacts and holds no signing credential. Configuration, failure handling, and bootstrap/backfill procedures: [`offchain/gpu/RUNTIME.md`](../gpu/RUNTIME.md).

`hashcredit_prover.cli` and the Bitcoin modules are legacy v1 code and are not an evidence path for Rackline v2.

## Tests

```bash
python -m pytest offchain/prover/tests offchain/gpu/tests/test_attestcoin_worker.py -q
```
