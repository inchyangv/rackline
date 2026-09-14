# hashcredit_gpu

Shared Python package for Rackline's GPU lending system. It holds the domain enums and exact money types that mirror `config/gpu/schema/domain-v1.schema.json`, the SQLAlchemy 2.0 models, the Alembic migrations for PostgreSQL, the accounting and reconciliation reference models, and the projection/ledger code that `offchain/api` and `offchain/prover` import. Install it before either of them.

The package name keeps the legacy `hashcredit` identifier; the product is Rackline.

## Install

```bash
# repository root, Python >= 3.11
pip install -e "offchain/gpu[dev]"
```

## Migrations

PostgreSQL only. The URL is never logged.

```bash
export HASHCREDIT_GPU_DATABASE_URL=postgresql+psycopg2://user:pass@host:5432/db
hashcredit-gpu-db upgrade head
hashcredit-gpu-db check          # fails on ORM <-> schema drift
hashcredit-gpu-db downgrade base
```

Production schemas come only from migrations, never from `metadata.create_all()`.

## Tests

Tests run against a real PostgreSQL server. Either point at a server that allows `CREATE DATABASE`, or let the fixture start an ephemeral cluster from local `initdb`/`pg_ctl` (Homebrew `postgresql@16` works).

```bash
export HASHCREDIT_GPU_TEST_DATABASE_URL=postgresql+psycopg2://postgres@127.0.0.1:5432/postgres   # optional
python -m pytest offchain/gpu/tests -q
```

## Rules enforced by the schema

- `required_verification` is always `ATTESTCOIN_NATIVE`.
- Money is `NUMERIC(78,0)` base units with explicit asset columns.
- Secrets and documents are stored as `secret://`, `vault://`, or `doc://` references only.
- A wallet links to one borrower at a time; one open provider assignment per asset.
- E2 agreements need partner change authority, a hash, an effective date, and a PoC reference. Funded facilities pin an agreement version.
- Nothing is `REPAID` or `RELEASED` with debt outstanding.
- `execution_profile` is immutable. PRODUCTION rows can never reference TEST_ONLY policies or terms, non-production providers, or LOCAL_MOCK verifications (PL/pgSQL triggers).

## Ledgers

Migration `0002_event_cash_job_ledgers` and `hashcredit_gpu/db/ledgers.py` define the raw-observation and official-proof pipeline (`proof_requests` → `proof_artifacts` → `native_verifications` → `evidence_consumptions`) plus the receivable, settlement, destination-cash/allocation, recovery/write-off, audit, cursor, job, outbox, tx-intent, and exception ledgers.

- Proof API 200, `eth_call` pre-check, native acceptance, and economic consumption are four independent facts guarded by triggers.
- `audit_log` and `raw_source_observations` are append-only.
- `allocations` never exceed their `cash_receipts` row; `excess` is borrower-refundable (`v_cash_ownership`).
- `hcg_lease_job()` hands out exclusive job leases.

## Related

- Worker runtime and operations: [RUNTIME.md](RUNTIME.md)
- Accounting reference model: `hashcredit_gpu/accounting/`, spec `docs/gpu/accounting.md`
- Reconciliation reference model: `hashcredit_gpu/reconciliation/`, spec `docs/gpu/evidence-and-reconciliation.md`
