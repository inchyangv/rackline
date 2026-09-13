# GPU worker runtime

These workers use PostgreSQL migrations through `0005` and the pinned official
`@gluwa/usc-sdk@0.18.0` / `@gluwa/asc-contracts@0.2.1` packages. Native operation has
no mock, signature, operator-acceptance or SPV fallback. Proof-service readiness,
application native acceptance, source-event consumption and destination cash are
separate durable facts.

Set `HASHCREDIT_GPU_DATABASE_URL` (or `GPU_DATABASE_URL`) through the deployment's
secret store. The proof artifact directory must be persistent. Package the ABI
snapshots in `hashcredit_gpu/projections/abi` and `offchain/attestcoin/abi`; the test
suite compares these with the exported contract ABI snapshots.

## Long-running services

```sh
python -m hashcredit_prover.gpu.chain_indexer \
  --manifest config/attestcoin/cc3-testnet.sepolia.release.json \
  --deployment-id DEPLOYMENT_ULID --reconcile

python -m hashcredit_prover.gpu.attestcoin_worker \
  --manifest config/attestcoin/cc3-testnet.sepolia.release.json \
  --deployment-id DEPLOYMENT_ULID \
  --sdk-cli /opt/attestcoin/dist/src/cli.js --artifact-dir /data/proofs

python -m hashcredit_prover.gpu.control_monitor --deployment-id DEPLOYMENT_ULID
```

Each service also accepts `--once`. The indexer keeps a deployment-block cursor,
replays pending reorgs and refuses to rewrite finalized history. The optional
reconciler compares debt and LP shares against canonical views at the same block.
RPC/database outages preserve cursors and durable job leases.

Proof jobs that reach `DEAD` atomically publish an account-scoped operation case
and outbox event. Terminal failures are not retryable; exhausted attestation/cache
polling is a warning, not borrower default. Only the authorized API's artifact-fetch
and attestation-wait retries are generic operator actions. Repeated exhaustion
updates the same unresolved case and invalidates its old review version. Case
payloads carry stable failure codes, never raw upstream diagnostic text.
An expired final-attempt lease is reaped into the same retryable review path;
it cannot remain silently leased forever. Resuming preserves the monotonically
increasing attempt counter, so a delayed pre-resume worker cannot reuse a fencing
token. Proof polling and exhausted-lease recovery are restricted to the worker's
pinned source, manifest, profile and SDK version.
SDK failure statuses are persisted with the fenced job result, not in an autonomous
transaction. A delayed old worker cannot downgrade a newer proof preparation result.

Without `--plans reviewed.json`, the proof service only fetches artifacts and has
no signing credential. A reviewed submission plan supplies the exact app purpose,
provider/emitter/topics, source-log instructions, and account/economic-ID bindings.
Enabling it requires the isolated `GPU_KEEPER_PRIVATE_KEY`; treasury
purposes cannot be signed by that credential. The dispatcher persists signed bytes
and nonce before broadcast, reconciles unknown outcomes, and never allocates a new
nonce solely because a response timed out.

The official SDK's cache-wait diagnostics are excluded from stdout so the CLI
returns one JSON value. For the Docker layout, set `ATTESTCOIN_REPO_ROOT=/app` and
`ATTESTCOIN_CONFIG_DIR=/app/config/attestcoin` for configuration checks.

## Actual TEST_ONLY deployment import

`bootstrap_native` verifies the canonical final facility, account/wallet link,
provider/manifest binding, loan token, terms and the successful `openFacility`
transaction input/receipt. It creates metadata only: KYC stays PENDING and legal
approval is not asserted. The simulated on-chain control is recorded as provenance,
not promoted to partner E2. No proof, revenue, cash or credit-decision rows are seeded.

```sh
python -m hashcredit_prover.gpu.bootstrap_native \
  --deployment config/gpu/deployments/cc3-testnet.json \
  --manifest config/attestcoin/cc3-testnet.sepolia.release.json \
  --setup-receipt config/gpu/evidence/native-20260914/setup-receipt.json
```

API operator roles are never inferred from a deployer key; pass explicit repeated
`--operator ADDRESS`, `--underwriter ADDRESS` or `--treasury ADDRESS` options when
authorized. Existing conflicting database identities are rejected.

After actual native app transactions have been finalized and indexed:

```sh
python -m hashcredit_prover.gpu.backfill_native \
  --manifest config/attestcoin/cc3-testnet.sepolia.release.json \
  --deployment-id DEPLOYMENT_ULID \
  --proof-dir config/gpu/evidence/native-20260914 --artifact-dir /data/proofs

python -m hashcredit_prover.gpu.reconcile_cash \
  --manifest config/attestcoin/cc3-testnet.sepolia.release.json \
  --deployment-id DEPLOYMENT_ULID --reference TX_HASH:MANAGER_REPAID_LOG_INDEX
```

The bounded native backfill requires the exact proof artifacts used in canonical
`ReceivableBook.ingest` calldata, verifier and consumption events in the same final
receipt, matching canonical source receipt/log contents, and complete v2
recognition/assignment/payout/checkpoint history. It atomically imports proof,
verification, consumption and receivable provenance. Unknown correction histories
are rejected, not reconstructed by guessing. A source payout creates no destination
cash. Cash reconciliation separately mirrors measured custody and the final
fee/interest/principal/excess allocation without writing a second debt ledger.

## Partner operations and settlement rails

`ControlExecutor` requires a scoped, approved provider binding and an independent
effect reader. A provider acknowledgement does not change control grade or become
cash. Retries first observe the effect; release requires the injected canonical
debt/refund guard. The monitor records idempotent review cases; stale proof or API
availability never automatically defaults a facility or disables repayment.

`SettlementLegExecutor` requires an approved rail, exact integer asset units,
receiver/refund allowlists, source and fee caps, minimum-out/slippage bounds, and an
idempotent external interface with lookup-by-request. Source sends and bridge
acknowledgements remain in flight. Actual destination cash remains recorded even
when allocation is pending or execution breaches the quoted minimum; the breach
opens a review case. Refunds do not repay debt.

There are no configured live Aethir/GPU.net write credentials or approved live
cross-chain rail bindings in this repository. These adapters cannot be enabled in
production with local mocks or unverified partner bindings.

## Verification

Run `python -m pytest offchain/gpu/tests -q` and, in `offchain/attestcoin`,
`npm test -- --run && npm run build`. PostgreSQL tests use isolated temporary
clusters, not SQLite. The SDK tests are local transport fixtures, not claims of
real native acceptance.

For an explicitly selected local native review runtime, the opt-in cold-database
regression copies its public canonical journal read-only and replays it into a
separate temporary database:

```sh
GPU_NATIVE_REPLAY_RUNTIME=keys/gpu-local-runtime.json \
  python -m pytest offchain/gpu/tests/test_native_journal_replay.py -q
```
