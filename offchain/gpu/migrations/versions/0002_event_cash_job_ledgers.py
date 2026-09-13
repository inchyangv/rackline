"""event, cash, repayment and job ledgers + audit (GPU-016).

Generated once by autogenerate from hashcredit_gpu.db.ledgers and frozen; cross-row invariants are
enforced by the PL/pgSQL triggers/functions/view appended below:
  * audit_log / raw_source_observations are append-only
  * proof_requests.status cannot claim a later pipeline fact without the row that proves it
    (artifact -> ACCEPTED native verification -> evidence consumption); API-ready and eth_call
    pre-check are separate timestamp columns and never advance the status by themselves
  * evidence_consumptions reference an ACCEPTED verification with the same method/profile; a
    PRODUCTION consumption can never point at a LOCAL_MOCK verification
  * receivable_revisions are monotonic unless explicitly recorded as out_of_order
  * allocations of one cash receipt never exceed the receipt amount
  * hcg_lease_job() grants an exclusive, expiring lease
  * v_cash_ownership separates LP-applied cash from borrower-refundable excess

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-14 09:16:04.500430
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


TRIGGER_SQL = r"""
CREATE OR REPLACE FUNCTION hcg_reject_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION '% is append-only (% rejected)', TG_TABLE_NAME, TG_OP USING ERRCODE = 'check_violation';
END $$ LANGUAGE plpgsql;

CREATE TRIGGER trg_audit_log_immutable
    BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION hcg_reject_mutation();

CREATE TRIGGER trg_raw_source_observations_immutable
    BEFORE UPDATE OR DELETE ON raw_source_observations
    FOR EACH ROW EXECUTE FUNCTION hcg_reject_mutation();

-- proof pipeline: each status claim needs the row that proves the earlier fact
CREATE OR REPLACE FUNCTION hcg_proof_requests_status_evidence() RETURNS trigger AS $$
DECLARE n_artifacts int; n_accepted int; n_consumed int;
BEGIN
    IF NEW.status IN ('PROOF_READY', 'SUBMITTED', 'NATIVE_ACCEPTED', 'CONSUMED') THEN
        SELECT count(*) INTO n_artifacts FROM proof_artifacts WHERE proof_request_id = NEW.proof_request_id;
        IF n_artifacts = 0 THEN
            RAISE EXCEPTION 'proof request % cannot be % without a stored proof artifact', NEW.proof_request_id, NEW.status
                USING ERRCODE = 'check_violation';
        END IF;
    END IF;
    IF NEW.status IN ('NATIVE_ACCEPTED', 'CONSUMED') THEN
        SELECT count(*) INTO n_accepted FROM native_verifications
            WHERE proof_request_id = NEW.proof_request_id AND status = 'ACCEPTED';
        IF n_accepted = 0 THEN
            RAISE EXCEPTION 'proof request % cannot be % without an ACCEPTED native verification (API 200 / eth_call are not acceptance)',
                NEW.proof_request_id, NEW.status USING ERRCODE = 'check_violation';
        END IF;
    END IF;
    IF NEW.status = 'CONSUMED' THEN
        SELECT count(*) INTO n_consumed FROM evidence_consumptions ec
            JOIN native_verifications nv ON nv.native_verification_id = ec.native_verification_id
            WHERE nv.proof_request_id = NEW.proof_request_id;
        IF n_consumed = 0 THEN
            RAISE EXCEPTION 'proof request % cannot be CONSUMED without an evidence consumption row', NEW.proof_request_id
                USING ERRCODE = 'check_violation';
        END IF;
    END IF;
    NEW.updated_at := now();
    RETURN NEW;
END $$ LANGUAGE plpgsql;

CREATE TRIGGER trg_proof_requests_status_evidence
    BEFORE INSERT OR UPDATE OF status ON proof_requests
    FOR EACH ROW EXECUTE FUNCTION hcg_proof_requests_status_evidence();

-- consumption: only an ACCEPTED verification of the same method/profile; production never references a mock
CREATE OR REPLACE FUNCTION hcg_evidence_consumptions_verified() RETURNS trigger AS $$
DECLARE v_status text; v_method text; v_profile text;
BEGIN
    SELECT status, verification_method, execution_profile INTO v_status, v_method, v_profile
        FROM native_verifications WHERE native_verification_id = NEW.native_verification_id;
    IF v_status IS NULL THEN
        RAISE EXCEPTION 'consumption % references unknown verification %', NEW.consumption_id, NEW.native_verification_id;
    END IF;
    IF v_status <> 'ACCEPTED' THEN
        RAISE EXCEPTION 'consumption % requires an ACCEPTED native verification (found %)', NEW.consumption_id, v_status
            USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.execution_profile = 'PRODUCTION' AND v_method <> 'ATTESTCOIN_NATIVE' THEN
        RAISE EXCEPTION 'PRODUCTION consumption % cannot reference a % verification', NEW.consumption_id, v_method
            USING ERRCODE = 'check_violation';
    END IF;
    IF v_profile <> NEW.execution_profile THEN
        RAISE EXCEPTION 'consumption profile % does not match verification profile %', NEW.execution_profile, v_profile
            USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.verification_method <> 'OFFCHAIN_ASSERTION' AND NEW.verification_method <> v_method THEN
        RAISE EXCEPTION 'consumption method % does not match verification method %', NEW.verification_method, v_method
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$ LANGUAGE plpgsql;

CREATE TRIGGER trg_evidence_consumptions_verified
    BEFORE INSERT OR UPDATE OF native_verification_id, execution_profile, verification_method ON evidence_consumptions
    FOR EACH ROW EXECUTE FUNCTION hcg_evidence_consumptions_verified();

-- receivable revisions: monotonic unless explicitly recorded as out of order
CREATE OR REPLACE FUNCTION hcg_receivable_revisions_monotonic() RETURNS trigger AS $$
DECLARE latest int;
BEGIN
    SELECT max(revision) INTO latest FROM receivable_revisions
        WHERE receivable_id = NEW.receivable_id AND NOT out_of_order;
    IF NOT NEW.out_of_order AND latest IS NOT NULL AND NEW.revision <= latest THEN
        RAISE EXCEPTION 'receivable % revision % is not after latest % (record it with out_of_order = true)',
            NEW.receivable_id, NEW.revision, latest USING ERRCODE = 'check_violation';
    END IF;
    IF NOT NEW.out_of_order THEN
        UPDATE receivables SET revision = NEW.revision, updated_at = now()
            WHERE receivable_id = NEW.receivable_id AND revision < NEW.revision;
    END IF;
    RETURN NEW;
END $$ LANGUAGE plpgsql;

CREATE TRIGGER trg_receivable_revisions_monotonic
    BEFORE INSERT ON receivable_revisions
    FOR EACH ROW EXECUTE FUNCTION hcg_receivable_revisions_monotonic();

-- allocations of one receipt never exceed the receipt
CREATE OR REPLACE FUNCTION hcg_allocations_within_receipt() RETURNS trigger AS $$
DECLARE total numeric; receipt numeric;
BEGIN
    SELECT amount INTO receipt FROM cash_receipts WHERE cash_receipt_id = NEW.cash_receipt_id FOR UPDATE;
    IF receipt IS NULL THEN
        RAISE EXCEPTION 'allocation % references unknown cash receipt %', NEW.allocation_id, NEW.cash_receipt_id;
    END IF;
    SELECT COALESCE(sum(received), 0) INTO total FROM allocations
        WHERE cash_receipt_id = NEW.cash_receipt_id AND allocation_id <> NEW.allocation_id;
    IF total + NEW.received > receipt THEN
        RAISE EXCEPTION 'allocations for receipt % (% + %) exceed the received amount %',
            NEW.cash_receipt_id, total, NEW.received, receipt USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$ LANGUAGE plpgsql;

CREATE TRIGGER trg_allocations_within_receipt
    BEFORE INSERT OR UPDATE OF received, cash_receipt_id ON allocations
    FOR EACH ROW EXECUTE FUNCTION hcg_allocations_within_receipt();

-- exclusive job lease: true only for the caller that won the row
CREATE OR REPLACE FUNCTION hcg_lease_job(p_job_id varchar, p_worker varchar, p_seconds integer) RETURNS boolean AS $$
DECLARE won boolean;
BEGIN
    UPDATE jobs
        SET state = 'LEASED', leased_by = p_worker, lease_until = now() + make_interval(secs => p_seconds),
            attempt = attempt + 1, updated_at = now()
        WHERE job_id = p_job_id
          AND state IN ('PENDING', 'LEASED')
          AND attempt < max_attempts
          AND next_run_at <= now()
          AND (lease_until IS NULL OR lease_until < now());
    won := FOUND;
    RETURN won;
END $$ LANGUAGE plpgsql;

-- cash ownership: LP-applied vs borrower-refundable, per receipt
CREATE VIEW v_cash_ownership AS
SELECT r.cash_receipt_id,
       r.vault_id,
       r.chain_id,
       r.token_address,
       r.amount AS received,
       COALESCE(sum(a.fee_paid + a.interest_paid + a.principal_paid), 0) AS lp_applied,
       COALESCE(sum(a.excess), 0) AS borrower_refundable,
       COALESCE(sum(a.excess) FILTER (WHERE a.excess_refunded_at IS NOT NULL), 0) AS borrower_refunded,
       r.amount - COALESCE(sum(a.received), 0) AS unallocated
FROM cash_receipts r
LEFT JOIN allocations a ON a.cash_receipt_id = r.cash_receipt_id
GROUP BY r.cash_receipt_id, r.vault_id, r.chain_id, r.token_address, r.amount;
"""

TRIGGER_DROP_SQL = r"""
DROP VIEW IF EXISTS v_cash_ownership;
DROP FUNCTION IF EXISTS hcg_lease_job(varchar, varchar, integer);
DROP TRIGGER IF EXISTS trg_allocations_within_receipt ON allocations;
DROP FUNCTION IF EXISTS hcg_allocations_within_receipt();
DROP TRIGGER IF EXISTS trg_receivable_revisions_monotonic ON receivable_revisions;
DROP FUNCTION IF EXISTS hcg_receivable_revisions_monotonic();
DROP TRIGGER IF EXISTS trg_evidence_consumptions_verified ON evidence_consumptions;
DROP FUNCTION IF EXISTS hcg_evidence_consumptions_verified();
DROP TRIGGER IF EXISTS trg_proof_requests_status_evidence ON proof_requests;
DROP FUNCTION IF EXISTS hcg_proof_requests_status_evidence();
DROP TRIGGER IF EXISTS trg_raw_source_observations_immutable ON raw_source_observations;
DROP TRIGGER IF EXISTS trg_audit_log_immutable ON audit_log;
DROP FUNCTION IF EXISTS hcg_reject_mutation();
"""


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('audit_log',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('occurred_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('actor', sa.String(length=128), nullable=False),
    sa.Column('actor_role', sa.String(length=24), nullable=False),
    sa.Column('action', sa.String(length=64), nullable=False),
    sa.Column('entity_table', sa.String(length=64), nullable=False),
    sa.Column('entity_id', sa.String(length=300), nullable=False),
    sa.Column('before', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('after', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('correlation_id', sa.String(length=64), nullable=True),
    sa.Column('prev_hash', sa.String(length=66), nullable=True),
    sa.Column('entry_hash', sa.String(length=66), nullable=False),
    sa.CheckConstraint("actor_role IN ('borrower', 'lp', 'underwriter', 'operator', 'keeper', 'guardian', 'treasury', 'system')", name='ck_audit_log_role'),
    sa.CheckConstraint("entry_hash ~ '^0x[0-9a-f]{64}$'", name='ck_audit_log_entry_hash'),
    sa.CheckConstraint("prev_hash IS NULL OR prev_hash ~ '^0x[0-9a-f]{64}$'", name='ck_audit_log_prev_hash'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_audit_log_entity', 'audit_log', ['entity_table', 'entity_id'], unique=False)
    op.create_table('exceptions',
    sa.Column('exception_id', sa.String(length=26), nullable=False),
    sa.Column('kind', sa.String(length=64), nullable=False),
    sa.Column('severity', sa.String(length=16), nullable=False),
    sa.Column('entity_table', sa.String(length=64), nullable=False),
    sa.Column('entity_id', sa.String(length=300), nullable=False),
    sa.Column('detail', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('opened_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('resolved_by', sa.String(length=24), nullable=True),
    sa.Column('resolution', sa.Text(), nullable=True),
    sa.CheckConstraint("exception_id ~ '^[0-9A-HJKMNP-TV-Z]{26}$'", name='ck_exceptions_ulid'),
    sa.CheckConstraint("resolved_by IS NULL OR resolved_by IN ('borrower', 'lp', 'underwriter', 'operator', 'keeper', 'guardian', 'treasury', 'system')", name='ck_exceptions_resolver'),
    sa.CheckConstraint("severity IN ('INFO', 'WARNING', 'BLOCKING')", name='ck_exceptions_severity'),
    sa.CheckConstraint('(resolved_at IS NULL) = (resolved_by IS NULL)', name='ck_exceptions_resolution_pair'),
    sa.PrimaryKeyConstraint('exception_id')
    )
    op.create_index('ix_exceptions_open', 'exceptions', ['kind', 'opened_at'], unique=False, postgresql_where='resolved_at IS NULL')
    op.create_table('jobs',
    sa.Column('job_id', sa.String(length=26), nullable=False),
    sa.Column('kind', sa.String(length=64), nullable=False),
    sa.Column('semantic_idempotency_key', sa.String(length=300), nullable=False),
    sa.Column('payload_hash', sa.String(length=66), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('state', sa.String(length=16), server_default='PENDING', nullable=False),
    sa.Column('attempt', sa.Integer(), server_default='0', nullable=False),
    sa.Column('max_attempts', sa.Integer(), server_default='10', nullable=False),
    sa.Column('leased_by', sa.String(length=128), nullable=True),
    sa.Column('lease_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('next_run_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("job_id ~ '^[0-9A-HJKMNP-TV-Z]{26}$'", name='ck_jobs_ulid'),
    sa.CheckConstraint("payload_hash ~ '^0x[0-9a-f]{64}$'", name='ck_jobs_payload_hash'),
    sa.CheckConstraint("state <> 'LEASED' OR (leased_by IS NOT NULL AND lease_until IS NOT NULL)", name='ck_jobs_lease_fields'),
    sa.CheckConstraint("state IN ('PENDING', 'LEASED', 'SUCCEEDED', 'FAILED', 'DEAD')", name='ck_jobs_state'),
    sa.CheckConstraint('attempt >= 0 AND max_attempts >= 1', name='ck_jobs_attempts'),
    sa.PrimaryKeyConstraint('job_id'),
    sa.UniqueConstraint('semantic_idempotency_key', name='uq_jobs_idempotency')
    )
    op.create_index('ix_jobs_state_next', 'jobs', ['state', 'next_run_at'], unique=False)
    op.create_table('outbox',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('aggregate_type', sa.String(length=64), nullable=False),
    sa.Column('aggregate_id', sa.String(length=300), nullable=False),
    sa.Column('event_type', sa.String(length=64), nullable=False),
    sa.Column('idempotency_key', sa.String(length=300), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('attempt', sa.Integer(), server_default='0', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('idempotency_key', name='uq_outbox_idempotency')
    )
    op.create_index('ix_outbox_unpublished', 'outbox', ['created_at'], unique=False, postgresql_where='published_at IS NULL')
    op.create_table('ingest_cursors',
    sa.Column('provider_id', sa.String(length=64), nullable=False),
    sa.Column('stream', sa.String(length=64), nullable=False),
    sa.Column('position_kind', sa.String(length=16), nullable=False),
    sa.Column('position', sa.Text(), nullable=False),
    sa.Column('backfill_from', sa.Text(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("position_kind IN ('BLOCK', 'TIMESTAMP', 'OPAQUE')", name='ck_ingest_cursors_kind'),
    sa.ForeignKeyConstraint(['provider_id'], ['providers.provider_id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('provider_id', 'stream')
    )
    op.create_table('proof_requests',
    sa.Column('proof_request_id', sa.String(length=26), nullable=False),
    sa.Column('env_id', sa.String(length=64), nullable=False),
    sa.Column('chain_key', sa.Integer(), nullable=False),
    sa.Column('tx_hash', sa.String(length=66), nullable=False),
    sa.Column('provider_id', sa.String(length=64), nullable=False),
    sa.Column('execution_profile', sa.String(length=32), nullable=False),
    sa.Column('manifest_hash', sa.String(length=71), nullable=False),
    sa.Column('sdk_version', sa.String(length=32), nullable=False),
    sa.Column('encoding_version', sa.SmallInteger(), server_default='1', nullable=False),
    sa.Column('abi_sha256s', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('decoder_ref', sa.Text(), nullable=True),
    sa.Column('status', sa.String(length=24), server_default='OBSERVED', nullable=False),
    sa.Column('attempt', sa.Integer(), server_default='0', nullable=False),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('lease_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('api_ready_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('precheck_ok_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("execution_profile IN ('LOCAL_MOCK', 'NATIVE_TESTNET', 'PRODUCTION')", name='ck_proof_requests_profile'),
    sa.CheckConstraint("manifest_hash ~ '^sha256:[0-9a-f]{64}$'", name='ck_proof_requests_manifest'),
    sa.CheckConstraint("proof_request_id ~ '^[0-9A-HJKMNP-TV-Z]{26}$'", name='ck_proof_requests_ulid'),
    sa.CheckConstraint("status IN ('NOT_REQUIRED', 'NOT_REQUESTED', 'OBSERVED', 'WAITING_ATTESTATION', 'PROOF_READY', 'SUBMITTED', 'NATIVE_ACCEPTED', 'CONSUMED', 'INVALID', 'UNSUPPORTED', 'EXPIRED') AND status NOT IN ('NOT_REQUIRED')", name='ck_proof_requests_status'),
    sa.CheckConstraint("tx_hash ~ '^0x[0-9a-f]{64}$'", name='ck_proof_requests_tx_hash'),
    sa.CheckConstraint('attempt >= 0', name='ck_proof_requests_attempt'),
    sa.CheckConstraint('chain_key > 0', name='ck_proof_requests_chain_key'),
    sa.CheckConstraint('encoding_version = 1', name='ck_proof_requests_encoding'),
    sa.ForeignKeyConstraint(['provider_id'], ['providers.provider_id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('proof_request_id'),
    sa.UniqueConstraint('env_id', 'chain_key', 'tx_hash', name='uq_proof_requests_query_key')
    )
    op.create_index('ix_proof_requests_status_next', 'proof_requests', ['status', 'next_attempt_at'], unique=False)
    op.create_table('raw_source_observations',
    sa.Column('observation_id', sa.String(length=26), nullable=False),
    sa.Column('provider_id', sa.String(length=64), nullable=False),
    sa.Column('origin', sa.String(length=16), nullable=False),
    sa.Column('schema_id', sa.String(length=64), nullable=False),
    sa.Column('schema_revision', sa.Integer(), server_default='1', nullable=False),
    sa.Column('payload_hash', sa.String(length=66), nullable=False),
    sa.Column('payload_ref', sa.Text(), nullable=True),
    sa.Column('source_cursor', sa.Text(), nullable=True),
    sa.Column('trust', sa.String(length=16), nullable=False),
    sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('collected_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("observation_id ~ '^[0-9A-HJKMNP-TV-Z]{26}$'", name='ck_raw_obs_ulid'),
    sa.CheckConstraint("origin IN ('CHAIN', 'API', 'WEBHOOK', 'MANUAL')", name='ck_raw_obs_origin'),
    sa.CheckConstraint("payload_hash ~ '^0x[0-9a-f]{64}$'", name='ck_raw_obs_payload_hash'),
    sa.CheckConstraint("payload_ref IS NULL OR payload_ref ~ '^(secret|vault|doc|blob|s3)://'", name='ck_raw_obs_payload_ref'),
    sa.CheckConstraint("trust IN ('PROVEN', 'ASSERTED', 'OBSERVED', 'CLAIMED')", name='ck_raw_obs_trust'),
    sa.CheckConstraint('schema_revision >= 1', name='ck_raw_obs_schema_revision'),
    sa.ForeignKeyConstraint(['provider_id'], ['providers.provider_id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('observation_id'),
    sa.UniqueConstraint('provider_id', 'origin', 'payload_hash', name='uq_raw_obs_payload')
    )
    op.create_index('ix_raw_obs_provider_observed', 'raw_source_observations', ['provider_id', 'observed_at'], unique=False)
    op.create_table('tx_intents',
    sa.Column('tx_intent_id', sa.String(length=26), nullable=False),
    sa.Column('job_id', sa.String(length=26), nullable=True),
    sa.Column('chain_id', sa.BigInteger(), nullable=False),
    sa.Column('signer_address', sa.String(length=42), nullable=False),
    sa.Column('nonce', sa.BigInteger(), nullable=False),
    sa.Column('purpose', sa.String(length=64), nullable=False),
    sa.Column('to_address', sa.String(length=42), nullable=False),
    sa.Column('calldata_hash', sa.String(length=66), nullable=False),
    sa.Column('tx_hash', sa.String(length=66), nullable=True),
    sa.Column('state', sa.String(length=16), server_default='PREPARED', nullable=False),
    sa.Column('replaces_tx_intent_id', sa.String(length=26), nullable=True),
    sa.Column('mined_block', sa.BigInteger(), nullable=True),
    sa.Column('finality_block', sa.BigInteger(), nullable=True),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("calldata_hash ~ '^0x[0-9a-f]{64}$'", name='ck_tx_intents_calldata'),
    sa.CheckConstraint("signer_address ~ '^0x[0-9a-f]{40}$' AND to_address ~ '^0x[0-9a-f]{40}$'", name='ck_tx_intents_addrs'),
    sa.CheckConstraint("state <> 'FINAL' OR (mined_block IS NOT NULL AND finality_block IS NOT NULL AND finality_block >= mined_block)", name='ck_tx_intents_final_blocks'),
    sa.CheckConstraint("state IN ('PREPARED', 'SENT', 'MINED', 'FINAL', 'REPLACED', 'FAILED', 'ORPHANED')", name='ck_tx_intents_state'),
    sa.CheckConstraint("state NOT IN ('SENT','MINED','FINAL') OR tx_hash IS NOT NULL", name='ck_tx_intents_sent_has_hash'),
    sa.CheckConstraint("tx_hash IS NULL OR tx_hash ~ '^0x[0-9a-f]{64}$'", name='ck_tx_intents_tx'),
    sa.CheckConstraint("tx_intent_id ~ '^[0-9A-HJKMNP-TV-Z]{26}$'", name='ck_tx_intents_ulid'),
    sa.CheckConstraint('chain_id > 0 AND nonce >= 0', name='ck_tx_intents_values'),
    sa.CheckConstraint('replaces_tx_intent_id IS NULL OR replaces_tx_intent_id <> tx_intent_id', name='ck_tx_intents_no_self_replace'),
    sa.ForeignKeyConstraint(['job_id'], ['jobs.job_id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['replaces_tx_intent_id'], ['tx_intents.tx_intent_id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('tx_intent_id'),
    sa.UniqueConstraint('chain_id', 'signer_address', 'nonce', name='uq_tx_intents_nonce'),
    sa.UniqueConstraint('tx_hash', name='uq_tx_intents_tx_hash')
    )
    op.create_index('ix_tx_intents_state', 'tx_intents', ['state'], unique=False)
    op.create_table('proof_artifacts',
    sa.Column('proof_artifact_id', sa.String(length=26), nullable=False),
    sa.Column('proof_request_id', sa.String(length=26), nullable=False),
    sa.Column('artifact_hash', sa.String(length=66), nullable=False),
    sa.Column('storage_ref', sa.Text(), nullable=False),
    sa.Column('byte_length', sa.Integer(), nullable=False),
    sa.Column('sdk_version', sa.String(length=32), nullable=False),
    sa.Column('encoding_version', sa.SmallInteger(), server_default='1', nullable=False),
    sa.Column('claimed_height', sa.BigInteger(), nullable=True),
    sa.Column('claimed_tx_index', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("artifact_hash ~ '^0x[0-9a-f]{64}$'", name='ck_proof_artifacts_hash'),
    sa.CheckConstraint("proof_artifact_id ~ '^[0-9A-HJKMNP-TV-Z]{26}$'", name='ck_proof_artifacts_ulid'),
    sa.CheckConstraint("storage_ref ~ '^(secret|vault|doc|blob|s3)://'", name='ck_proof_artifacts_storage_ref'),
    sa.CheckConstraint('byte_length > 0', name='ck_proof_artifacts_length'),
    sa.CheckConstraint('claimed_height IS NULL OR claimed_height >= 0', name='ck_proof_artifacts_height'),
    sa.CheckConstraint('claimed_tx_index IS NULL OR claimed_tx_index >= 0', name='ck_proof_artifacts_tx_index'),
    sa.CheckConstraint('encoding_version = 1', name='ck_proof_artifacts_encoding'),
    sa.ForeignKeyConstraint(['proof_request_id'], ['proof_requests.proof_request_id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('proof_artifact_id'),
    sa.UniqueConstraint('proof_request_id', 'artifact_hash', name='uq_proof_artifacts_request_hash')
    )
    op.create_table('native_verifications',
    sa.Column('native_verification_id', sa.String(length=26), nullable=False),
    sa.Column('proof_request_id', sa.String(length=26), nullable=False),
    sa.Column('proof_artifact_id', sa.String(length=26), nullable=False),
    sa.Column('execution_profile', sa.String(length=32), nullable=False),
    sa.Column('verification_method', sa.String(length=32), nullable=False),
    sa.Column('destination_chain_id', sa.BigInteger(), nullable=False),
    sa.Column('verifier_address', sa.String(length=42), nullable=False),
    sa.Column('submission_tx_hash', sa.String(length=66), nullable=False),
    sa.Column('verification_block', sa.BigInteger(), nullable=True),
    sa.Column('receipt_status', sa.SmallInteger(), nullable=True),
    sa.Column('status', sa.String(length=16), server_default='SUBMITTED', nullable=False),
    sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('proven_height', sa.BigInteger(), nullable=True),
    sa.Column('proven_tx_index', sa.Integer(), nullable=True),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(verification_method = 'LOCAL_MOCK') = (execution_profile = 'LOCAL_MOCK')", name='ck_native_verifications_mock_profile'),
    sa.CheckConstraint("execution_profile IN ('LOCAL_MOCK', 'NATIVE_TESTNET', 'PRODUCTION')", name='ck_native_verifications_profile'),
    sa.CheckConstraint("native_verification_id ~ '^[0-9A-HJKMNP-TV-Z]{26}$'", name='ck_native_verifications_ulid'),
    sa.CheckConstraint("status <> 'ACCEPTED' OR (accepted_at IS NOT NULL AND receipt_status = 1 AND verification_block IS NOT NULL AND proven_height IS NOT NULL AND proven_tx_index IS NOT NULL)", name='ck_native_verifications_accepted_evidence'),
    sa.CheckConstraint("status = 'ACCEPTED' OR accepted_at IS NULL", name='ck_native_verifications_accepted_only'),
    sa.CheckConstraint("status IN ('SUBMITTED', 'ACCEPTED', 'REJECTED', 'ORPHANED')", name='ck_native_verifications_status'),
    sa.CheckConstraint("submission_tx_hash ~ '^0x[0-9a-f]{64}$'", name='ck_native_verifications_tx'),
    sa.CheckConstraint("verification_method IN ('ATTESTCOIN_NATIVE','LOCAL_MOCK')", name='ck_native_verifications_method'),
    sa.CheckConstraint("verifier_address ~ '^0x[0-9a-f]{40}$'", name='ck_native_verifications_verifier'),
    sa.CheckConstraint('destination_chain_id > 0', name='ck_native_verifications_chain'),
    sa.CheckConstraint('receipt_status IS NULL OR receipt_status IN (0, 1)', name='ck_native_verifications_receipt'),
    sa.ForeignKeyConstraint(['proof_artifact_id'], ['proof_artifacts.proof_artifact_id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['proof_request_id'], ['proof_requests.proof_request_id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('native_verification_id'),
    sa.UniqueConstraint('proof_request_id', 'submission_tx_hash', name='uq_native_verifications_request_tx')
    )
    op.create_index('ix_native_verifications_status', 'native_verifications', ['status'], unique=False)
    op.create_table('evidence_consumptions',
    sa.Column('consumption_id', sa.String(length=26), nullable=False),
    sa.Column('env_id', sa.String(length=64), nullable=False),
    sa.Column('source_event_id', sa.String(length=66), nullable=False),
    sa.Column('economic_event_id', sa.String(length=300), nullable=False),
    sa.Column('native_verification_id', sa.String(length=26), nullable=False),
    sa.Column('provider_id', sa.String(length=64), nullable=False),
    sa.Column('provider_account_id', sa.String(length=200), nullable=False),
    sa.Column('meaning', sa.String(length=32), nullable=False),
    sa.Column('verification_method', sa.String(length=32), nullable=False),
    sa.Column('trust', sa.String(length=16), nullable=False),
    sa.Column('execution_profile', sa.String(length=32), nullable=False),
    sa.Column('consumer_address', sa.String(length=42), nullable=False),
    sa.Column('consumption_tx_hash', sa.String(length=66), nullable=False),
    sa.Column('manifest_hash', sa.String(length=71), nullable=False),
    sa.Column('proven_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('valid_until', sa.DateTime(timezone=True), nullable=False),
    sa.Column('chain_key', sa.Integer(), nullable=False),
    sa.Column('height', sa.BigInteger(), nullable=False),
    sa.Column('tx_index', sa.Integer(), nullable=False),
    sa.Column('log_ordinal', sa.Integer(), nullable=False),
    sa.Column('emitter_address', sa.String(length=42), nullable=False),
    sa.Column('topic0', sa.String(length=66), nullable=False),
    sa.Column('data_hash', sa.String(length=66), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(verification_method = 'OFFCHAIN_ASSERTION') = (trust = 'ASSERTED')", name='ck_evidence_consumptions_assertion_trust'),
    sa.CheckConstraint("consumer_address ~ '^0x[0-9a-f]{40}$' AND emitter_address ~ '^0x[0-9a-f]{40}$'", name='ck_evidence_consumptions_addrs'),
    sa.CheckConstraint("consumption_id ~ '^[0-9A-HJKMNP-TV-Z]{26}$'", name='ck_evidence_consumptions_ulid'),
    sa.CheckConstraint("consumption_tx_hash ~ '^0x[0-9a-f]{64}$' AND topic0 ~ '^0x[0-9a-f]{64}$' AND data_hash ~ '^0x[0-9a-f]{64}$'", name='ck_evidence_consumptions_hashes'),
    sa.CheckConstraint("economic_event_id ~ '^[a-z0-9-]+/[^/]+/[A-Z_]+/.+$'", name='ck_evidence_consumptions_economic_id'),
    sa.CheckConstraint("execution_profile <> 'PRODUCTION' OR verification_method <> 'LOCAL_MOCK'", name='ck_evidence_consumptions_prod_no_mock'),
    sa.CheckConstraint("execution_profile IN ('LOCAL_MOCK', 'NATIVE_TESTNET', 'PRODUCTION')", name='ck_evidence_consumptions_profile'),
    sa.CheckConstraint("manifest_hash ~ '^sha256:[0-9a-f]{64}$'", name='ck_evidence_consumptions_manifest'),
    sa.CheckConstraint("meaning IN ('OBLIGATION_RECOGNIZED', 'ASSIGNMENT_RECOGNIZED', 'CORRECTION', 'PAYOUT', 'PAYMENT_CANCELLED', 'CHECKPOINT')", name='ck_evidence_consumptions_meaning'),
    sa.CheckConstraint("source_event_id ~ '^0x[0-9a-f]{64}$'", name='ck_evidence_consumptions_source_event'),
    sa.CheckConstraint("trust IN ('PROVEN', 'ASSERTED', 'OBSERVED', 'CLAIMED')", name='ck_evidence_consumptions_trust'),
    sa.CheckConstraint("verification_method IN ('ATTESTCOIN_NATIVE', 'LOCAL_MOCK', 'OFFCHAIN_ASSERTION')", name='ck_evidence_consumptions_method'),
    sa.CheckConstraint('chain_key > 0 AND height >= 0 AND tx_index >= 0 AND log_ordinal >= 0', name='ck_evidence_consumptions_locator'),
    sa.CheckConstraint('valid_until > proven_at', name='ck_evidence_consumptions_validity'),
    sa.ForeignKeyConstraint(['native_verification_id'], ['native_verifications.native_verification_id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['provider_account_id'], ['provider_accounts.provider_account_id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['provider_id'], ['providers.provider_id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('consumption_id'),
    sa.UniqueConstraint('economic_event_id', name='uq_evidence_consumptions_economic_event'),
    sa.UniqueConstraint('env_id', 'chain_key', 'height', 'tx_index', 'log_ordinal', name='uq_evidence_consumptions_locator'),
    sa.UniqueConstraint('env_id', 'source_event_id', name='uq_evidence_consumptions_source_event')
    )
    op.create_index('ix_evidence_consumptions_account', 'evidence_consumptions', ['provider_account_id', 'meaning'], unique=False)
    op.create_table('correction_links',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('source_economic_event_id', sa.String(length=300), nullable=False),
    sa.Column('target_economic_event_id', sa.String(length=300), nullable=False),
    sa.Column('kind', sa.String(length=24), nullable=False),
    sa.Column('consumption_id', sa.String(length=26), nullable=True),
    sa.Column('observation_id', sa.String(length=26), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("kind IN ('CORRECTION', 'CANCELLATION', 'REVERSAL', 'RECONCILED_DUPLICATE')", name='ck_correction_links_kind'),
    sa.CheckConstraint('source_economic_event_id <> target_economic_event_id', name='ck_correction_links_distinct'),
    sa.ForeignKeyConstraint(['consumption_id'], ['evidence_consumptions.consumption_id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['observation_id'], ['raw_source_observations.observation_id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source_economic_event_id', 'target_economic_event_id', 'kind', name='uq_correction_links')
    )
    op.create_table('receivables',
    sa.Column('receivable_id', sa.String(length=26), nullable=False),
    sa.Column('economic_event_id', sa.String(length=300), nullable=False),
    sa.Column('provider_account_id', sa.String(length=200), nullable=False),
    sa.Column('obligation_ref', sa.String(length=128), nullable=False),
    sa.Column('debtor', sa.Text(), nullable=True),
    sa.Column('contract_ref', sa.Text(), nullable=True),
    sa.Column('asset_chain_id', sa.BigInteger(), nullable=False),
    sa.Column('asset_token_address', sa.String(length=42), nullable=True),
    sa.Column('asset_decimals', sa.SmallInteger(), nullable=False),
    sa.Column('gross', sa.Numeric(precision=78, scale=0), nullable=False),
    sa.Column('net', sa.Numeric(precision=78, scale=0), nullable=False),
    sa.Column('paid_amount', sa.Numeric(precision=78, scale=0), server_default='0', nullable=False),
    sa.Column('unpaid_amount', sa.Numeric(precision=78, scale=0), nullable=False),
    sa.Column('state', sa.String(length=24), server_default='RECOGNIZED', nullable=False),
    sa.Column('revision', sa.Integer(), server_default='1', nullable=False),
    sa.Column('facility_id', sa.String(length=26), nullable=True),
    sa.Column('checkpoint_seq', sa.BigInteger(), nullable=True),
    sa.Column('checkpoint_consumption_id', sa.String(length=26), nullable=True),
    sa.Column('period_from', sa.DateTime(timezone=True), nullable=True),
    sa.Column('period_to', sa.DateTime(timezone=True), nullable=True),
    sa.Column('due_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('disputed_reason', sa.Text(), nullable=True),
    sa.Column('execution_profile', sa.String(length=32), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("asset_token_address IS NULL OR asset_token_address ~ '^0x[0-9a-f]{40}$'", name='ck_receivables_token'),
    sa.CheckConstraint("execution_profile IN ('LOCAL_MOCK', 'NATIVE_TESTNET', 'PRODUCTION')", name='ck_receivables_profile'),
    sa.CheckConstraint("receivable_id ~ '^[0-9A-HJKMNP-TV-Z]{26}$'", name='ck_receivables_ulid'),
    sa.CheckConstraint("state <> 'ASSIGNED' OR facility_id IS NOT NULL", name='ck_receivables_assigned_has_facility'),
    sa.CheckConstraint("state <> 'DISPUTED' OR disputed_reason IS NOT NULL", name='ck_receivables_disputed_reason'),
    sa.CheckConstraint("state <> 'PAID' OR unpaid_amount = 0", name='ck_receivables_paid_is_zero'),
    sa.CheckConstraint("state IN ('RECOGNIZED', 'ASSIGNED', 'PARTIALLY_PAID', 'PAID', 'DISPUTED', 'CANCELLED', 'WRITTEN_OFF')", name='ck_receivables_state'),
    sa.CheckConstraint('asset_chain_id > 0 AND asset_decimals BETWEEN 0 AND 36', name='ck_receivables_asset'),
    sa.CheckConstraint('gross >= 0 AND net >= 0 AND paid_amount >= 0 AND unpaid_amount >= 0', name='ck_receivables_money_nonneg'),
    sa.CheckConstraint('net <= gross AND paid_amount <= net AND unpaid_amount = net - paid_amount', name='ck_receivables_balance'),
    sa.CheckConstraint('revision >= 1', name='ck_receivables_revision'),
    sa.ForeignKeyConstraint(['checkpoint_consumption_id'], ['evidence_consumptions.consumption_id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['facility_id'], ['facilities.facility_id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['provider_account_id'], ['provider_accounts.provider_account_id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('receivable_id'),
    sa.UniqueConstraint('economic_event_id', name='uq_receivables_economic_event'),
    sa.UniqueConstraint('provider_account_id', 'obligation_ref', name='uq_receivables_account_ref')
    )
    op.create_index('ix_receivables_facility_state', 'receivables', ['facility_id', 'state'], unique=False)
    op.create_table('settlements',
    sa.Column('settlement_id', sa.String(length=26), nullable=False),
    sa.Column('provider_account_id', sa.String(length=200), nullable=False),
    sa.Column('settlement_ref', sa.String(length=128), nullable=False),
    sa.Column('settlement_seq', sa.BigInteger(), nullable=True),
    sa.Column('state', sa.String(length=32), server_default='ANNOUNCED', nullable=False),
    sa.Column('asset_chain_id', sa.BigInteger(), nullable=False),
    sa.Column('asset_token_address', sa.String(length=42), nullable=True),
    sa.Column('asset_decimals', sa.SmallInteger(), nullable=False),
    sa.Column('source_amount', sa.Numeric(precision=78, scale=0), nullable=False),
    sa.Column('payout_consumption_id', sa.String(length=26), nullable=True),
    sa.Column('execution_profile', sa.String(length=32), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("asset_token_address IS NULL OR asset_token_address ~ '^0x[0-9a-f]{40}$'", name='ck_settlements_token'),
    sa.CheckConstraint("execution_profile IN ('LOCAL_MOCK', 'NATIVE_TESTNET', 'PRODUCTION')", name='ck_settlements_profile'),
    sa.CheckConstraint("settlement_id ~ '^[0-9A-HJKMNP-TV-Z]{26}$'", name='ck_settlements_ulid'),
    sa.CheckConstraint("state IN ('ANNOUNCED', 'PAID_AT_SOURCE', 'CONVERTING', 'RECEIVED_AT_DESTINATION', 'ALLOCATED', 'REVERSED')", name='ck_settlements_state'),
    sa.CheckConstraint("state IN ('ANNOUNCED','REVERSED') OR payout_consumption_id IS NOT NULL", name='ck_settlements_paid_requires_proof'),
    sa.CheckConstraint('asset_chain_id > 0 AND asset_decimals BETWEEN 0 AND 36 AND source_amount >= 0', name='ck_settlements_asset'),
    sa.CheckConstraint('settlement_seq IS NULL OR settlement_seq >= 0', name='ck_settlements_seq'),
    sa.ForeignKeyConstraint(['payout_consumption_id'], ['evidence_consumptions.consumption_id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['provider_account_id'], ['provider_accounts.provider_account_id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('settlement_id'),
    sa.UniqueConstraint('provider_account_id', 'settlement_ref', name='uq_settlements_account_ref')
    )
    op.create_index('ix_settlements_state', 'settlements', ['state'], unique=False)
    op.create_table('writeoffs',
    sa.Column('writeoff_id', sa.String(length=26), nullable=False),
    sa.Column('facility_id', sa.String(length=26), nullable=False),
    sa.Column('amount', sa.Numeric(precision=78, scale=0), nullable=False),
    sa.Column('legal_debt_remaining', sa.Numeric(precision=78, scale=0), nullable=False),
    sa.Column('extinguishes_debt', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('approved_by', sa.String(length=24), nullable=False),
    sa.Column('approved_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("approved_by IN ('underwriter','guardian','treasury')", name='ck_writeoffs_approver'),
    sa.CheckConstraint("writeoff_id ~ '^[0-9A-HJKMNP-TV-Z]{26}$'", name='ck_writeoffs_ulid'),
    sa.CheckConstraint('amount > 0 AND legal_debt_remaining >= 0', name='ck_writeoffs_amounts'),
    sa.CheckConstraint('extinguishes_debt = false', name='ck_writeoffs_never_forgive'),
    sa.ForeignKeyConstraint(['facility_id'], ['facilities.facility_id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('writeoff_id')
    )
    op.create_index('ix_writeoffs_facility', 'writeoffs', ['facility_id'], unique=False)
    op.create_table('cash_receipts',
    sa.Column('cash_receipt_id', sa.String(length=26), nullable=False),
    sa.Column('vault_id', sa.String(length=64), nullable=False),
    sa.Column('chain_id', sa.BigInteger(), nullable=False),
    sa.Column('token_address', sa.String(length=42), nullable=True),
    sa.Column('decimals', sa.SmallInteger(), nullable=False),
    sa.Column('amount', sa.Numeric(precision=78, scale=0), nullable=False),
    sa.Column('tx_hash', sa.String(length=66), nullable=False),
    sa.Column('log_index', sa.Integer(), nullable=False),
    sa.Column('payer_address', sa.String(length=42), nullable=True),
    sa.Column('source_kind', sa.String(length=24), server_default='UNKNOWN', nullable=False),
    sa.Column('settlement_id', sa.String(length=26), nullable=True),
    sa.Column('cash_state', sa.String(length=24), server_default='DESTINATION_RECEIVED', nullable=False),
    sa.Column('execution_profile', sa.String(length=32), nullable=False),
    sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("cash_receipt_id ~ '^[0-9A-HJKMNP-TV-Z]{26}$'", name='ck_cash_receipts_ulid'),
    sa.CheckConstraint("cash_state IN ('DESTINATION_RECEIVED','ALLOCATED','RETURNED')", name='ck_cash_receipts_state'),
    sa.CheckConstraint("execution_profile IN ('LOCAL_MOCK', 'NATIVE_TESTNET', 'PRODUCTION')", name='ck_cash_receipts_profile'),
    sa.CheckConstraint("payer_address IS NULL OR payer_address ~ '^0x[0-9a-f]{40}$'", name='ck_cash_receipts_payer'),
    sa.CheckConstraint("source_kind <> 'SETTLEMENT' OR settlement_id IS NOT NULL", name='ck_cash_receipts_settlement_link'),
    sa.CheckConstraint("source_kind IN ('SETTLEMENT', 'DIRECT_REPAYMENT', 'RECOVERY', 'UNKNOWN')", name='ck_cash_receipts_source_kind'),
    sa.CheckConstraint("token_address IS NULL OR token_address ~ '^0x[0-9a-f]{40}$'", name='ck_cash_receipts_token'),
    sa.CheckConstraint("tx_hash ~ '^0x[0-9a-f]{64}$'", name='ck_cash_receipts_tx'),
    sa.CheckConstraint('chain_id > 0 AND decimals BETWEEN 0 AND 36 AND amount > 0 AND log_index >= 0', name='ck_cash_receipts_values'),
    sa.ForeignKeyConstraint(['settlement_id'], ['settlements.settlement_id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('cash_receipt_id'),
    sa.UniqueConstraint('chain_id', 'tx_hash', 'log_index', name='uq_cash_receipts_semantic_key')
    )
    op.create_index('ix_cash_receipts_vault_state', 'cash_receipts', ['vault_id', 'cash_state'], unique=False)
    op.create_table('receivable_revisions',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('receivable_id', sa.String(length=26), nullable=False),
    sa.Column('revision', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('consumption_id', sa.String(length=26), nullable=True),
    sa.Column('observation_id', sa.String(length=26), nullable=True),
    sa.Column('delta', sa.Numeric(precision=78, scale=0), server_default='0', nullable=False),
    sa.Column('net_after', sa.Numeric(precision=78, scale=0), nullable=False),
    sa.Column('unpaid_after', sa.Numeric(precision=78, scale=0), nullable=False),
    sa.Column('out_of_order', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('recorded_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("kind IN ('RECOGNIZED', 'CORRECTION', 'ASSIGNMENT', 'PAYOUT', 'CANCELLATION', 'DISPUTE', 'CHECKPOINT')", name='ck_receivable_revisions_kind'),
    sa.CheckConstraint('consumption_id IS NOT NULL OR observation_id IS NOT NULL', name='ck_receivable_revisions_provenance'),
    sa.CheckConstraint('revision >= 1 AND net_after >= 0 AND unpaid_after >= 0', name='ck_receivable_revisions_values'),
    sa.ForeignKeyConstraint(['consumption_id'], ['evidence_consumptions.consumption_id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['observation_id'], ['raw_source_observations.observation_id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['receivable_id'], ['receivables.receivable_id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('receivable_id', 'revision', 'kind', name='uq_receivable_revisions_rev')
    )
    op.create_index('ix_receivable_revisions_receivable', 'receivable_revisions', ['receivable_id', 'revision'], unique=False)
    op.create_table('settlement_receivables',
    sa.Column('settlement_id', sa.String(length=26), nullable=False),
    sa.Column('receivable_id', sa.String(length=26), nullable=False),
    sa.Column('amount', sa.Numeric(precision=78, scale=0), nullable=False),
    sa.CheckConstraint('amount > 0', name='ck_settlement_receivables_amount'),
    sa.ForeignKeyConstraint(['receivable_id'], ['receivables.receivable_id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['settlement_id'], ['settlements.settlement_id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('settlement_id', 'receivable_id')
    )
    op.create_table('allocations',
    sa.Column('allocation_id', sa.String(length=26), nullable=False),
    sa.Column('cash_receipt_id', sa.String(length=26), nullable=False),
    sa.Column('facility_id', sa.String(length=26), nullable=False),
    sa.Column('received', sa.Numeric(precision=78, scale=0), nullable=False),
    sa.Column('fee_paid', sa.Numeric(precision=78, scale=0), server_default='0', nullable=False),
    sa.Column('interest_paid', sa.Numeric(precision=78, scale=0), server_default='0', nullable=False),
    sa.Column('principal_paid', sa.Numeric(precision=78, scale=0), server_default='0', nullable=False),
    sa.Column('excess', sa.Numeric(precision=78, scale=0), server_default='0', nullable=False),
    sa.Column('excess_refunded_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('new_debt', sa.Numeric(precision=78, scale=0), nullable=False),
    sa.Column('onchain_tx_hash', sa.String(length=66), nullable=True),
    sa.Column('allocated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("allocation_id ~ '^[0-9A-HJKMNP-TV-Z]{26}$'", name='ck_allocations_ulid'),
    sa.CheckConstraint("onchain_tx_hash IS NULL OR onchain_tx_hash ~ '^0x[0-9a-f]{64}$'", name='ck_allocations_tx'),
    sa.CheckConstraint('fee_paid + interest_paid + principal_paid + excess = received', name='ck_allocations_split_sum'),
    sa.CheckConstraint('received > 0 AND fee_paid >= 0 AND interest_paid >= 0 AND principal_paid >= 0 AND excess >= 0 AND new_debt >= 0', name='ck_allocations_nonneg'),
    sa.ForeignKeyConstraint(['cash_receipt_id'], ['cash_receipts.cash_receipt_id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['facility_id'], ['facilities.facility_id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('allocation_id'),
    sa.UniqueConstraint('cash_receipt_id', 'facility_id', name='uq_allocations_receipt_facility')
    )
    op.create_index('ix_allocations_facility', 'allocations', ['facility_id', 'allocated_at'], unique=False)
    op.create_table('recovery_events',
    sa.Column('recovery_event_id', sa.String(length=26), nullable=False),
    sa.Column('facility_id', sa.String(length=26), nullable=False),
    sa.Column('kind', sa.String(length=24), nullable=False),
    sa.Column('amount', sa.Numeric(precision=78, scale=0), nullable=False),
    sa.Column('cash_receipt_id', sa.String(length=26), nullable=True),
    sa.Column('evidence_ref', sa.Text(), nullable=True),
    sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('recorded_by', sa.String(length=24), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("evidence_ref IS NULL OR evidence_ref ~ '^(secret|vault|doc|blob|s3)://'", name='ck_recovery_events_ref'),
    sa.CheckConstraint("kind IN ('COLLECTION', 'COLLATERAL_SALE', 'INSURANCE', 'LEGAL', 'OTHER')", name='ck_recovery_events_kind'),
    sa.CheckConstraint("recorded_by IN ('operator','underwriter','guardian','treasury','system')", name='ck_recovery_events_role'),
    sa.CheckConstraint("recovery_event_id ~ '^[0-9A-HJKMNP-TV-Z]{26}$'", name='ck_recovery_events_ulid'),
    sa.CheckConstraint('amount >= 0', name='ck_recovery_events_amount'),
    sa.ForeignKeyConstraint(['cash_receipt_id'], ['cash_receipts.cash_receipt_id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['facility_id'], ['facilities.facility_id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('recovery_event_id')
    )
    op.create_index('ix_recovery_events_facility', 'recovery_events', ['facility_id', 'occurred_at'], unique=False)
    # ### end Alembic commands ###
    op.execute(TRIGGER_SQL)


def downgrade() -> None:
    op.execute(TRIGGER_DROP_SQL)
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index('ix_recovery_events_facility', table_name='recovery_events')
    op.drop_table('recovery_events')
    op.drop_index('ix_allocations_facility', table_name='allocations')
    op.drop_table('allocations')
    op.drop_table('settlement_receivables')
    op.drop_index('ix_receivable_revisions_receivable', table_name='receivable_revisions')
    op.drop_table('receivable_revisions')
    op.drop_index('ix_cash_receipts_vault_state', table_name='cash_receipts')
    op.drop_table('cash_receipts')
    op.drop_index('ix_writeoffs_facility', table_name='writeoffs')
    op.drop_table('writeoffs')
    op.drop_index('ix_settlements_state', table_name='settlements')
    op.drop_table('settlements')
    op.drop_index('ix_receivables_facility_state', table_name='receivables')
    op.drop_table('receivables')
    op.drop_table('correction_links')
    op.drop_index('ix_evidence_consumptions_account', table_name='evidence_consumptions')
    op.drop_table('evidence_consumptions')
    op.drop_index('ix_native_verifications_status', table_name='native_verifications')
    op.drop_table('native_verifications')
    op.drop_table('proof_artifacts')
    op.drop_index('ix_tx_intents_state', table_name='tx_intents')
    op.drop_table('tx_intents')
    op.drop_index('ix_raw_obs_provider_observed', table_name='raw_source_observations')
    op.drop_table('raw_source_observations')
    op.drop_index('ix_proof_requests_status_next', table_name='proof_requests')
    op.drop_table('proof_requests')
    op.drop_table('ingest_cursors')
    op.drop_index('ix_outbox_unpublished', table_name='outbox', postgresql_where='published_at IS NULL')
    op.drop_table('outbox')
    op.drop_index('ix_jobs_state_next', table_name='jobs')
    op.drop_table('jobs')
    op.drop_index('ix_exceptions_open', table_name='exceptions', postgresql_where='resolved_at IS NULL')
    op.drop_table('exceptions')
    op.drop_index('ix_audit_log_entity', table_name='audit_log')
    op.drop_table('audit_log')
    # ### end Alembic commands ###
