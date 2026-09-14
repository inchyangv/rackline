# GPU worker runtime

Operations reference for the Rackline v2 background services in `hashcredit_prover.gpu`. The services use PostgreSQL migrations through `0005` and the pinned official `@gluwa/usc-sdk@0.18.0` / `@gluwa/asc-contracts@0.2.1` packages. Native operation has no mock, signature, operator-acceptance, or SPV fallback.

Four facts are stored separately and never inferred from one another: proof-service readiness, application native acceptance, source-event consumption, and destination cash.

## Configuration

| Setting | Purpose |
| --- | --- |
| `HASHCREDIT_GPU_DATABASE_URL` (or `GPU_DATABASE_URL`) | PostgreSQL connection; supply through the deployment's secret store |
| `GPU_ATTESTCOIN_MANIFEST` | Attestcoin environment manifest, for example `config/attestcoin/cc3-testnet.sepolia.release.json` |
| `ATTESTCOIN_CLI` | Built SDK CLI (`offchain/attestcoin/dist/src/cli.js`; `/opt/attestcoin/dist/src/cli.js` in the container) |
| `GPU_ARTIFACT_DIR` | Persistent proof artifact directory |
| `GPU_SUBMISSION_PLANS` | Optional reviewed submission plan; without it the proof worker only fetches artifacts |
| `GPU_KEEPER_PRIVATE_KEY` | Isolated keeper credential, required only when a submission plan is enabled; cannot sign treasury purposes |
| `ATTESTCOIN_REPO_ROOT`, `ATTESTCOIN_CONFIG_DIR` | Set to `/app` and `/app/config/attestcoin` in the Docker layout for configuration checks |

ABI snapshots are packaged in `hashcredit_gpu/projections/abi` and `offchain/attestcoin/abi`; the test suite compares them with the exported contract ABIs.

In the shared container image, `GPU_SERVICE` selects the process: `api`, `indexer`, `proof`, or `monitor` (`offchain/api/hashcredit_api/gpu/server.py`).

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

Each service accepts `--once` for a single pass.

- **Chain indexer.** Keeps a deployment-block cursor, replays pending reorgs, and refuses to rewrite finalized history. `--reconcile` compares debt and LP shares against canonical views at the same block.
- **Proof worker.** Fetches official proof artifacts, prepares deployment-bound calldata, and, only with a reviewed plan, dispatches transactions. The SDK's cache-wait diagnostics are kept off stdout so the CLI returns one JSON value.
- **Control monitor.** Records payment-control observations as review cases. Stale proof or partner API availability never defaults a facility or disables repayment.

RPC and database outages preserve cursors and durable job leases.

## Proof job lifecycle and failure handling

- Jobs are leased with a fencing token and a monotonically increasing attempt counter. A delayed pre-resume worker cannot reuse a token, and an old worker cannot downgrade a newer proof preparation result. SDK failure statuses persist with the fenced job result, not in a separate transaction.
- Polling and lease recovery are restricted to the worker's pinned source, manifest, profile, and SDK version.
- A job that reaches `DEAD` atomically publishes an account-scoped operation case and an outbox event. Terminal failures are not retryable. Exhausted attestation or cache polling is a warning, not a borrower default.
- Repeated exhaustion updates the same unresolved case and invalidates its previous review version. Case payloads carry stable failure codes, never raw upstream text.
- An expired final-attempt lease is reaped into the same review path; it cannot stay leased forever.
- The only generic operator retries are the authorized API's artifact-fetch and attestation-wait actions.

## Submission plans and dispatch

A reviewed plan (`--plans reviewed.json`) supplies the exact app purpose, provider/emitter/topics, source-log instructions, and account/economic-ID bindings. The dispatcher persists signed bytes and nonce before broadcast, reconciles unknown outcomes, and never allocates a new nonce because a response timed out.

## Importing the TEST_ONLY deployment

`bootstrap_native` verifies the canonical facility, account/wallet link, provider/manifest binding, loan token, terms, and the successful `openFacility` transaction, then creates metadata only. KYC stays `PENDING`, legal approval is not asserted, and the simulated on-chain control is recorded as provenance rather than promoted to partner E2. No proof, revenue, cash, or credit-decision rows are seeded.

```sh
python -m hashcredit_prover.gpu.bootstrap_native \
  --deployment config/gpu/deployments/cc3-testnet.json \
  --manifest config/attestcoin/cc3-testnet.sepolia.release.json \
  --setup-receipt config/gpu/evidence/native-20260914/setup-receipt.json
```

API staff roles are never inferred from a deployer key. Pass explicit repeated `--operator`, `--underwriter`, or `--treasury ADDRESS` options when authorized. Conflicting existing database identities are rejected.

After native app transactions are finalized and indexed:

```sh
python -m hashcredit_prover.gpu.backfill_native \
  --manifest config/attestcoin/cc3-testnet.sepolia.release.json \
  --deployment-id DEPLOYMENT_ULID \
  --proof-dir config/gpu/evidence/native-20260914 --artifact-dir /data/proofs

python -m hashcredit_prover.gpu.reconcile_cash \
  --manifest config/attestcoin/cc3-testnet.sepolia.release.json \
  --deployment-id DEPLOYMENT_ULID --reference TX_HASH:MANAGER_REPAID_LOG_INDEX
```

`backfill_native` requires the exact proof artifacts used in the canonical `ReceivableBook.ingest` calldata, verifier and consumption events in the same final receipt, matching source receipt/log contents, and complete recognition/assignment/payout/checkpoint history. It imports proof, verification, consumption, and receivable provenance atomically; unknown correction histories are rejected rather than reconstructed. A source payout creates no destination cash.

`reconcile_cash` mirrors measured custody and the final fee/interest/principal/excess allocation without writing a second debt ledger.

## Partner operations and settlement rails

- `ControlExecutor` requires a scoped, approved provider binding and an independent effect reader. A provider acknowledgement does not change control grade or become cash. Retries observe the effect first; release requires the injected canonical debt/refund guard.
- `SettlementLegExecutor` requires an approved rail, exact integer asset units, receiver and refund allowlists, source and fee caps, minimum-out/slippage bounds, and an idempotent external interface with lookup-by-request. Source sends and bridge acknowledgements stay in flight. Destination cash is recorded even when allocation is pending or execution breaches the quoted minimum; the breach opens a review case. Refunds do not repay debt.

No live Aethir or GPU.net write credentials and no approved live cross-chain rail bindings exist in this repository. These adapters cannot be enabled in production with local mocks or unverified partner bindings.

## Verification

```sh
python -m pytest offchain/gpu/tests -q
npm --prefix offchain/attestcoin test -- --run && npm --prefix offchain/attestcoin run build
```

PostgreSQL tests use isolated temporary clusters, not SQLite. The SDK tests use local transport fixtures and do not claim native acceptance.

Opt-in cold-database regression against a local native runtime: copies the public canonical journal read-only and replays it into a separate temporary database.

```sh
GPU_NATIVE_REPLAY_RUNTIME=keys/gpu-local-runtime.json \
  python -m pytest offchain/gpu/tests/test_native_journal_replay.py -q
```
