# hashcredit_gpu

Shared Python package for Rackline's GPU lending system: domain enums and exact
money types mirroring `config/gpu/schema/domain-v1.schema.json`, SQLAlchemy 2.0 models, and Alembic
migrations for PostgreSQL. `offchain/api` and `offchain/prover` depend on it; install it first.

```bash
# from the repo root, project venv (Python >= 3.11)
pip install -e "offchain/gpu[dev]"

# migrations (PostgreSQL only; URL never logged)
export HASHCREDIT_GPU_DATABASE_URL=postgresql+psycopg2://user:pass@host:5432/db
hashcredit-gpu-db upgrade head
hashcredit-gpu-db check          # fails on ORM <-> schema drift
hashcredit-gpu-db downgrade base

# tests (PY-GPU): real PostgreSQL. Either point at a server that allows CREATE DATABASE
export HASHCREDIT_GPU_TEST_DATABASE_URL=postgresql+psycopg2://postgres@127.0.0.1:5432/postgres
# ...or let the fixture start an ephemeral cluster from local initdb/pg_ctl (Homebrew postgresql@16 works).
python -m pytest offchain/gpu/tests -q
```

Rules baked into the schema: `required_verification` is always `ATTESTCOIN_NATIVE`; money is
`NUMERIC(78,0)` base units with explicit asset columns; secrets and documents are stored as
`secret://`/`vault://`/`doc://` references only; a wallet links to one borrower at a time; one open
provider assignment per asset; E2 agreements need partner change authority, hash, effective date and a
PoC reference; funded facilities need a pinned agreement version; nothing is `REPAID`/`RELEASED` with debt;
`execution_profile` is immutable and PRODUCTION rows can never reference TEST_ONLY policies/terms or
non-production providers (PL/pgSQL triggers). Production schemas come only from migrations — never
`metadata.create_all()`.

GPU-016 (`0002_event_cash_job_ledgers`, `hashcredit_gpu/db/ledgers.py`) adds the raw-observation, official-proof
pipeline (`proof_requests` → `proof_artifacts` → `native_verifications` → `evidence_consumptions`), receivable,
settlement, destination-cash/allocation, recovery/write-off, audit, cursor, job, outbox, tx-intent and exception
ledgers. Proof API 200, `eth_call` pre-check, native acceptance and economic consumption are four independent
facts guarded by triggers; PRODUCTION rows can never reference LOCAL_MOCK verifications; `audit_log` and
`raw_source_observations` are append-only; `allocations` never exceed their `cash_receipts` row and `excess` is
borrower-refundable (`v_cash_ownership`); `hcg_lease_job()` hands out exclusive job leases.
