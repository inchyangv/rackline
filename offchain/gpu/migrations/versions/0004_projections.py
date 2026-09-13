"""on-chain projector: deployments, cursors, block/reorg journals, raw logs, read models (GPU-073).

Hand-written (mirrors hashcredit_gpu/db/projections_models.py; `hashcredit-gpu-db check` asserts no drift).

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-14
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None

ULID_RE = "~ '^[0-9A-HJKMNP-TV-Z]{26}$'"
ADDR_RE = "~ '^0x[0-9a-f]{40}$'"
HEX32_RE = "~ '^0x[0-9a-f]{64}$'"
PROFILES = "('LOCAL_MOCK','NATIVE_TESTNET','PRODUCTION')"
METHODS = "('ATTESTCOIN_NATIVE','LOCAL_MOCK','OFFCHAIN_ASSERTION')"
STATES = "('DRAFT','UNDER_REVIEW','CONTROL_PENDING','ACTIVE','DRAW_FROZEN','DELINQUENT','DEFAULTED','RECOVERY','REPAID','RELEASED','CLOSED_WITH_LOSS')"
TIER = "tier IN ('PENDING','FINALIZED')"
KINDS = "('VAULT','RESERVATION','CONTROL_AGREEMENT','ROLE','PROVIDER','POLICY','VERIFIER_BINDING','RECEIVABLE','ESCROW','ADMIN')"


def upgrade() -> None:
    op.create_table(
        'chain_deployments',
        sa.Column('deployment_id', sa.String(length=26), nullable=False),
        sa.Column('chain_id', sa.BigInteger(), nullable=False),
        sa.Column('execution_profile', sa.String(length=32), nullable=False),
        sa.Column('env_id', sa.String(length=64), nullable=False),
        sa.Column('manifest_hash', sa.String(length=71), nullable=False),
        sa.Column('deployment_block', sa.BigInteger(), nullable=False),
        sa.Column('contracts', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('schema_version', sa.Integer(), server_default='1', nullable=False),
        sa.Column('finality_depth', sa.Integer(), server_default='12', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint(f"deployment_id {ULID_RE}", name='ck_chain_deployments_ulid'),
        sa.CheckConstraint('chain_id > 0', name='ck_chain_deployments_chain'),
        sa.CheckConstraint(f"execution_profile IN {PROFILES}", name='ck_chain_deployments_profile'),
        sa.CheckConstraint("manifest_hash ~ '^sha256:[0-9a-f]{64}$'", name='ck_chain_deployments_manifest'),
        sa.CheckConstraint('deployment_block >= 0 AND finality_depth >= 0', name='ck_chain_deployments_blocks'),
        sa.CheckConstraint("(execution_profile = 'LOCAL_MOCK') = (chain_id NOT IN (102030, 102031, 102032))", name='ck_chain_deployments_mock_chain'),
        sa.PrimaryKeyConstraint('deployment_id'),
        sa.UniqueConstraint('chain_id', 'manifest_hash', 'deployment_block', name='uq_chain_deployments_identity'),
    )
    op.create_table(
        'chain_cursors',
        sa.Column('deployment_id', sa.String(length=26), nullable=False),
        sa.Column('last_block_number', sa.BigInteger(), nullable=False),
        sa.Column('last_block_hash', sa.String(length=66), nullable=False),
        sa.Column('finalized_block_number', sa.BigInteger(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint(f"last_block_hash {HEX32_RE}", name='ck_chain_cursors_hash'),
        sa.CheckConstraint('finalized_block_number <= last_block_number', name='ck_chain_cursors_order'),
        sa.ForeignKeyConstraint(['deployment_id'], ['chain_deployments.deployment_id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('deployment_id'),
    )
    op.create_table(
        'chain_blocks',
        sa.Column('deployment_id', sa.String(length=26), nullable=False),
        sa.Column('number', sa.BigInteger(), nullable=False),
        sa.Column('hash', sa.String(length=66), nullable=False),
        sa.Column('parent_hash', sa.String(length=66), nullable=False),
        sa.Column('timestamp', sa.BigInteger(), nullable=False),
        sa.Column('tier', sa.String(length=10), server_default='PENDING', nullable=False),
        sa.CheckConstraint(f"hash {HEX32_RE} AND parent_hash {HEX32_RE}", name='ck_chain_blocks_hashes'),
        sa.CheckConstraint(TIER, name='ck_chain_blocks_tier'),
        sa.ForeignKeyConstraint(['deployment_id'], ['chain_deployments.deployment_id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('deployment_id', 'number'),
    )
    op.create_table(
        'reorg_journal',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('deployment_id', sa.String(length=26), nullable=False),
        sa.Column('fork_block', sa.BigInteger(), nullable=False),
        sa.Column('old_hash', sa.String(length=66), nullable=False),
        sa.Column('new_hash', sa.String(length=66), nullable=False),
        sa.Column('logs_rolled_back', sa.Integer(), nullable=False),
        sa.Column('detected_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint(f"old_hash {HEX32_RE} AND new_hash {HEX32_RE}", name='ck_reorg_journal_hashes'),
        sa.ForeignKeyConstraint(['deployment_id'], ['chain_deployments.deployment_id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'chain_logs',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('deployment_id', sa.String(length=26), nullable=False),
        sa.Column('block_number', sa.BigInteger(), nullable=False),
        sa.Column('block_hash', sa.String(length=66), nullable=False),
        sa.Column('tx_hash', sa.String(length=66), nullable=False),
        sa.Column('tx_index', sa.Integer(), nullable=False),
        sa.Column('log_index', sa.Integer(), nullable=False),
        sa.Column('tx_status', sa.Integer(), nullable=False),
        sa.Column('address', sa.String(length=42), nullable=False),
        sa.Column('contract_name', sa.String(length=48), nullable=False),
        sa.Column('event_name', sa.String(length=64), nullable=False),
        sa.Column('topics', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('data', sa.Text(), nullable=False),
        sa.Column('decoded', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('tier', sa.String(length=10), server_default='PENDING', nullable=False),
        sa.CheckConstraint(f"block_hash {HEX32_RE} AND tx_hash {HEX32_RE}", name='ck_chain_logs_hashes'),
        sa.CheckConstraint(f"address {ADDR_RE}", name='ck_chain_logs_address'),
        sa.CheckConstraint('tx_status IN (0, 1)', name='ck_chain_logs_tx_status'),
        sa.CheckConstraint('block_number >= 0 AND tx_index >= 0 AND log_index >= 0', name='ck_chain_logs_position'),
        sa.CheckConstraint(TIER, name='ck_chain_logs_tier'),
        sa.ForeignKeyConstraint(['deployment_id'], ['chain_deployments.deployment_id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('deployment_id', 'block_hash', 'tx_hash', 'log_index', name='uq_chain_logs_position'),
    )
    op.create_index('ix_chain_logs_block', 'chain_logs', ['deployment_id', 'block_number'], unique=False)
    op.create_table(
        'proj_facilities',
        sa.Column('deployment_id', sa.String(length=26), nullable=False),
        sa.Column('tier', sa.String(length=10), nullable=False),
        sa.Column('facility_key', sa.String(length=66), nullable=False),
        sa.Column('borrower_key', sa.String(length=66), nullable=True),
        sa.Column('execution_profile', sa.String(length=32), nullable=False),
        sa.Column('state', sa.String(length=24), nullable=False),
        sa.Column('principal', sa.Numeric(precision=78, scale=0), server_default='0', nullable=False),
        sa.Column('fees', sa.Numeric(precision=78, scale=0), server_default='0', nullable=False),
        sa.Column('unpaid_interest_recorded', sa.Numeric(precision=78, scale=0), server_default='0', nullable=False),
        sa.Column('rate_bps', sa.Integer(), server_default='0', nullable=False),
        sa.Column('last_accrual_at', sa.BigInteger(), nullable=True),
        sa.Column('accrual_frozen', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('last_decision_hash', sa.String(length=66), nullable=True),
        sa.Column('authorization_valid_until', sa.BigInteger(), nullable=True),
        sa.Column('last_block', sa.BigInteger(), nullable=False),
        sa.CheckConstraint(f"facility_key {HEX32_RE}", name='ck_proj_facilities_key'),
        sa.CheckConstraint(f"execution_profile IN {PROFILES}", name='ck_proj_facilities_profile'),
        sa.CheckConstraint(f"state IN {STATES}", name='ck_proj_facilities_state'),
        sa.CheckConstraint('principal >= 0 AND fees >= 0 AND unpaid_interest_recorded >= 0', name='ck_proj_facilities_amounts'),
        sa.CheckConstraint(TIER, name='ck_proj_facilities_tier'),
        sa.ForeignKeyConstraint(['deployment_id'], ['chain_deployments.deployment_id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('deployment_id', 'tier', 'facility_key'),
    )
    op.create_table(
        'proj_evidence',
        sa.Column('deployment_id', sa.String(length=26), nullable=False),
        sa.Column('tier', sa.String(length=10), nullable=False),
        sa.Column('source_event_id', sa.String(length=66), nullable=False),
        sa.Column('economic_event_key', sa.String(length=66), nullable=False),
        sa.Column('consumer_address', sa.String(length=42), nullable=False),
        sa.Column('meaning', sa.String(length=32), nullable=False),
        sa.Column('manifest_hash', sa.String(length=66), nullable=False),
        sa.Column('verification_method', sa.String(length=32), nullable=False),
        sa.Column('execution_profile', sa.String(length=32), nullable=False),
        sa.Column('verified_in_same_tx', sa.Boolean(), nullable=False),
        sa.Column('proven_height', sa.BigInteger(), nullable=True),
        sa.Column('proven_tx_index', sa.Integer(), nullable=True),
        sa.Column('proven_log_ordinal', sa.Integer(), nullable=True),
        sa.Column('consumption_tx_hash', sa.String(length=66), nullable=False),
        sa.Column('block_number', sa.BigInteger(), nullable=False),
        sa.Column('block_hash', sa.String(length=66), nullable=False),
        sa.Column('log_index', sa.Integer(), nullable=False),
        sa.CheckConstraint(f"source_event_id {HEX32_RE} AND economic_event_key {HEX32_RE}", name='ck_proj_evidence_ids'),
        sa.CheckConstraint(f"consumer_address {ADDR_RE}", name='ck_proj_evidence_consumer'),
        sa.CheckConstraint(f"verification_method IN {METHODS}", name='ck_proj_evidence_method'),
        sa.CheckConstraint(f"execution_profile IN {PROFILES}", name='ck_proj_evidence_profile'),
        sa.CheckConstraint("(verification_method = 'LOCAL_MOCK') = (execution_profile = 'LOCAL_MOCK')", name='ck_proj_evidence_mock_profile'),
        sa.CheckConstraint(TIER, name='ck_proj_evidence_tier'),
        sa.ForeignKeyConstraint(['deployment_id'], ['chain_deployments.deployment_id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('deployment_id', 'tier', 'source_event_id'),
        sa.UniqueConstraint('deployment_id', 'tier', 'economic_event_key', name='uq_proj_evidence_economic'),
    )
    op.create_table(
        'proj_entities',
        sa.Column('deployment_id', sa.String(length=26), nullable=False),
        sa.Column('tier', sa.String(length=10), nullable=False),
        sa.Column('kind', sa.String(length=32), nullable=False),
        sa.Column('entity_key', sa.String(length=160), nullable=False),
        sa.Column('state', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('last_block', sa.BigInteger(), nullable=False),
        sa.CheckConstraint(f"kind IN {KINDS}", name='ck_proj_entities_kind'),
        sa.CheckConstraint(TIER, name='ck_proj_entities_tier'),
        sa.ForeignKeyConstraint(['deployment_id'], ['chain_deployments.deployment_id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('deployment_id', 'tier', 'kind', 'entity_key'),
    )
    op.create_table(
        'projection_discrepancies',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('deployment_id', sa.String(length=26), nullable=False),
        sa.Column('block_number', sa.BigInteger(), nullable=False),
        sa.Column('subject', sa.String(length=200), nullable=False),
        sa.Column('projected', sa.Text(), nullable=False),
        sa.Column('canonical', sa.Text(), nullable=False),
        sa.Column('classification', sa.String(length=24), nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('detected_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("classification IN ('EXPECTED_LAG','DISCREPANCY','EXTERNAL_SUBMITTER')", name='ck_projection_discrepancies_kind'),
        sa.ForeignKeyConstraint(['deployment_id'], ['chain_deployments.deployment_id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('projection_discrepancies')
    op.drop_table('proj_entities')
    op.drop_table('proj_evidence')
    op.drop_table('proj_facilities')
    op.drop_index('ix_chain_logs_block', table_name='chain_logs')
    op.drop_table('chain_logs')
    op.drop_table('reorg_journal')
    op.drop_table('chain_blocks')
    op.drop_table('chain_cursors')
    op.drop_table('chain_deployments')
