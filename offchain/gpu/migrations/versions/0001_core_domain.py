"""core domain (GPU-015): registry, borrowers, accounts, assets, control agreements, facilities, decisions.

Generated once by autogenerate from hashcredit_gpu.db.models and frozen; cross-row invariants are
enforced by the PL/pgSQL triggers appended below (native-testnet data can never be reused in production).

Revision ID: 0001
Revises: 
Create Date: 2026-09-14 07:55:38.368036
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


TRIGGER_SQL = r"""
CREATE OR REPLACE FUNCTION hcg_credit_decisions_profile_match() RETURNS trigger AS $$
DECLARE fac_profile text;
BEGIN
    SELECT execution_profile INTO fac_profile FROM facilities WHERE facility_id = NEW.facility_id;
    IF fac_profile IS NULL THEN
        RAISE EXCEPTION 'credit decision % references unknown facility %', NEW.credit_decision_id, NEW.facility_id;
    END IF;
    IF fac_profile <> NEW.execution_profile THEN
        RAISE EXCEPTION 'credit decision profile % does not match facility profile % (no cross-profile evidence)',
            NEW.execution_profile, fac_profile USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$ LANGUAGE plpgsql;

CREATE TRIGGER trg_credit_decisions_profile_match
    BEFORE INSERT OR UPDATE OF execution_profile, facility_id ON credit_decisions
    FOR EACH ROW EXECUTE FUNCTION hcg_credit_decisions_profile_match();

CREATE OR REPLACE FUNCTION hcg_facilities_production_isolation() RETURNS trigger AS $$
DECLARE pol_test boolean; terms_test boolean; prov_profile text; prov_test boolean;
BEGIN
    -- profile is immutable once set: no promotion of testnet facilities, no demotion of production ones
    IF TG_OP = 'UPDATE' AND OLD.execution_profile <> NEW.execution_profile THEN
        RAISE EXCEPTION 'facility % execution_profile is immutable (% -> %)', NEW.facility_id, OLD.execution_profile, NEW.execution_profile
            USING ERRCODE = 'check_violation';
    END IF;
    SELECT test_only INTO pol_test FROM policy_versions WHERE policy_version_id = NEW.policy_version_id;
    SELECT test_only INTO terms_test FROM terms_versions WHERE terms_version_id = NEW.terms_version_id;
    IF NEW.execution_profile = 'PRODUCTION' AND (COALESCE(pol_test, true) OR COALESCE(terms_test, true)) THEN
        RAISE EXCEPTION 'PRODUCTION facility % cannot use TEST_ONLY policy/terms versions', NEW.facility_id
            USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.control_agreement_id IS NOT NULL THEN
        SELECT p.execution_profile, p.test_only INTO prov_profile, prov_test
          FROM control_agreements ca
          JOIN provider_accounts pa ON pa.provider_account_id = ca.provider_account_id
          JOIN providers p ON p.provider_id = pa.provider_id
         WHERE ca.control_agreement_id = NEW.control_agreement_id;
        IF prov_profile IS NULL THEN
            RAISE EXCEPTION 'facility % references unknown control agreement', NEW.facility_id;
        END IF;
        IF prov_profile <> NEW.execution_profile OR (NEW.execution_profile = 'PRODUCTION' AND prov_test) THEN
            RAISE EXCEPTION 'facility % profile % cannot bind provider with profile % (test_only=%)',
                NEW.facility_id, NEW.execution_profile, prov_profile, prov_test USING ERRCODE = 'check_violation';
        END IF;
    END IF;
    RETURN NEW;
END $$ LANGUAGE plpgsql;

CREATE TRIGGER trg_facilities_production_isolation
    BEFORE INSERT OR UPDATE ON facilities
    FOR EACH ROW EXECUTE FUNCTION hcg_facilities_production_isolation();
"""

TRIGGER_DROP_SQL = r"""
DROP TRIGGER IF EXISTS trg_facilities_production_isolation ON facilities;
DROP FUNCTION IF EXISTS hcg_facilities_production_isolation();
DROP TRIGGER IF EXISTS trg_credit_decisions_profile_match ON credit_decisions;
DROP FUNCTION IF EXISTS hcg_credit_decisions_profile_match();
"""


def upgrade() -> None:
    op.create_table('gpu_assets',
    sa.Column('asset_id', sa.String(length=26), nullable=False),
    sa.Column('kind', sa.String(length=32), nullable=False),
    sa.Column('sku', sa.String(length=128), nullable=True),
    sa.Column('unit_count', sa.Integer(), server_default='1', nullable=False),
    sa.Column('ownership', sa.String(length=16), server_default='UNKNOWN', nullable=False),
    sa.Column('custodian', sa.String(length=200), nullable=True),
    sa.Column('location', sa.String(length=64), nullable=True),
    sa.Column('parent_asset_id', sa.String(length=26), nullable=True),
    sa.Column('eligible', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("NOT eligible OR ownership <> 'UNKNOWN'", name='ck_gpu_assets_eligible_requires_ownership'),
    sa.CheckConstraint("asset_id ~ '^[0-9A-HJKMNP-TV-Z]{26}$'", name='ck_gpu_assets_ulid'),
    sa.CheckConstraint("kind IN ('PHYSICAL_GPU', 'MIG_PARTITION', 'VGPU', 'VM', 'CONTAINER', 'STAKING_GROUP', 'NODE_NFT')", name='ck_gpu_assets_kind'),
    sa.CheckConstraint("ownership IN ('OWNED','LEASED','UNKNOWN')", name='ck_gpu_assets_ownership'),
    sa.CheckConstraint('parent_asset_id IS NULL OR parent_asset_id <> asset_id', name='ck_gpu_assets_no_self_parent'),
    sa.CheckConstraint('unit_count > 0', name='ck_gpu_assets_unit_count'),
    sa.ForeignKeyConstraint(['parent_asset_id'], ['gpu_assets.asset_id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('asset_id')
    )
    op.create_table('legal_entities',
    sa.Column('legal_entity_id', sa.String(length=26), nullable=False),
    sa.Column('jurisdiction', sa.String(length=64), nullable=True),
    sa.Column('registration_ref', sa.Text(), nullable=True),
    sa.Column('beneficial_owners_ref', sa.Text(), nullable=True),
    sa.Column('signing_authority_ref', sa.Text(), nullable=True),
    sa.Column('documents_ref', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(registration_ref IS NULL OR registration_ref ~ '^(vault|secret|doc)://') AND (beneficial_owners_ref IS NULL OR beneficial_owners_ref ~ '^(vault|secret|doc)://') AND (signing_authority_ref IS NULL OR signing_authority_ref ~ '^(vault|secret|doc)://')", name='ck_legal_entities_refs_only'),
    sa.CheckConstraint("legal_entity_id ~ '^[0-9A-HJKMNP-TV-Z]{26}$'", name='ck_legal_entities_ulid'),
    sa.PrimaryKeyConstraint('legal_entity_id')
    )
    op.create_table('policy_versions',
    sa.Column('policy_version_id', sa.String(length=64), nullable=False),
    sa.Column('approved_by', sa.String(length=64), nullable=True),
    sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('parameters', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('test_only', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('test_only OR (approved_by IS NOT NULL AND approved_at IS NOT NULL)', name='ck_policy_versions_approved'),
    sa.PrimaryKeyConstraint('policy_version_id')
    )
    op.create_table('providers',
    sa.Column('provider_id', sa.String(length=64), nullable=False),
    sa.Column('display_name', sa.String(length=200), nullable=False),
    sa.Column('source_env_id', sa.String(length=64), nullable=False),
    sa.Column('source_chain_key', sa.Integer(), nullable=False),
    sa.Column('source_chain_id', sa.BigInteger(), nullable=False),
    sa.Column('execution_profile', sa.String(length=32), nullable=False),
    sa.Column('environment_status', sa.String(length=32), nullable=False),
    sa.Column('required_verification', sa.String(length=32), server_default='ATTESTCOIN_NATIVE', nullable=False),
    sa.Column('manifest_hash', sa.String(length=71), nullable=True),
    sa.Column('capabilities', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('test_only', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(execution_profile = 'PRODUCTION') = (NOT test_only)", name='ck_providers_test_only_profile'),
    sa.CheckConstraint("environment_status IN ('UNCONFIRMED', 'PROBED', 'UNSUPPORTED')", name='ck_providers_env_status'),
    sa.CheckConstraint("execution_profile IN ('LOCAL_MOCK', 'NATIVE_TESTNET', 'PRODUCTION')", name='ck_providers_profile'),
    sa.CheckConstraint("manifest_hash IS NULL OR manifest_hash ~ '^sha256:[0-9a-f]{64}$'", name='ck_providers_manifest_hash'),
    sa.CheckConstraint("provider_id ~ '^[a-z0-9-]+$'", name='ck_providers_id_slug'),
    sa.CheckConstraint("required_verification = 'ATTESTCOIN_NATIVE'", name='ck_providers_required_verification'),
    sa.CheckConstraint('source_chain_key > 0 AND source_chain_id > 0', name='ck_providers_chain_positive'),
    sa.PrimaryKeyConstraint('provider_id'),
    sa.UniqueConstraint('source_env_id', 'source_chain_key', 'provider_id', name='uq_providers_env_key')
    )
    op.create_table('terms_versions',
    sa.Column('terms_version_id', sa.String(length=64), nullable=False),
    sa.Column('approved_by', sa.String(length=64), nullable=True),
    sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('parameters', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('test_only', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('test_only OR (approved_by IS NOT NULL AND approved_at IS NOT NULL)', name='ck_terms_versions_approved'),
    sa.PrimaryKeyConstraint('terms_version_id')
    )
    op.create_table('asset_encumbrances',
    sa.Column('encumbrance_id', sa.String(length=26), nullable=False),
    sa.Column('asset_id', sa.String(length=26), nullable=True),
    sa.Column('receivable_id', sa.String(length=26), nullable=True),
    sa.Column('holder', sa.String(length=200), nullable=False),
    sa.Column('priority', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('document_ref', sa.Text(), nullable=True),
    sa.Column('valid_from', sa.DateTime(timezone=True), nullable=False),
    sa.Column('valid_to', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("document_ref IS NULL OR document_ref ~ '^(vault|secret|doc)://'", name='ck_asset_encumbrances_doc_ref'),
    sa.CheckConstraint("encumbrance_id ~ '^[0-9A-HJKMNP-TV-Z]{26}$'", name='ck_asset_encumbrances_ulid'),
    sa.CheckConstraint("kind IN ('LIEN','ASSIGNMENT','LEASE','PLEDGE')", name='ck_asset_encumbrances_kind'),
    sa.CheckConstraint('asset_id IS NOT NULL OR receivable_id IS NOT NULL', name='ck_asset_encumbrances_target'),
    sa.CheckConstraint('priority > 0', name='ck_asset_encumbrances_priority'),
    sa.CheckConstraint('valid_to IS NULL OR valid_to > valid_from', name='ck_asset_encumbrances_period'),
    sa.ForeignKeyConstraint(['asset_id'], ['gpu_assets.asset_id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('encumbrance_id')
    )
    op.create_table('asset_identity_keys',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('asset_id', sa.String(length=26), nullable=False),
    sa.Column('scheme', sa.String(length=16), nullable=False),
    sa.Column('value', sa.String(length=200), nullable=False),
    sa.Column('provenance', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.CheckConstraint("scheme IN ('GPU_UUID','SERIAL','HOST_ID','GROUP_ID','NFT_TOKEN')", name='ck_asset_identity_keys_scheme'),
    sa.ForeignKeyConstraint(['asset_id'], ['gpu_assets.asset_id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('scheme', 'value', name='uq_asset_identity_keys_value')
    )
    op.create_table('borrowers',
    sa.Column('borrower_id', sa.String(length=26), nullable=False),
    sa.Column('legal_entity_id', sa.String(length=26), nullable=False),
    sa.Column('group_id', sa.String(length=64), nullable=True),
    sa.Column('kyc_status', sa.String(length=16), server_default='NONE', nullable=False),
    sa.Column('underwriting_status', sa.String(length=16), server_default='NONE', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("borrower_id ~ '^[0-9A-HJKMNP-TV-Z]{26}$'", name='ck_borrowers_ulid'),
    sa.CheckConstraint("kyc_status IN ('NONE','PENDING','VERIFIED','REJECTED')", name='ck_borrowers_kyc'),
    sa.CheckConstraint("underwriting_status IN ('NONE','IN_REVIEW','APPROVED','DECLINED')", name='ck_borrowers_uw'),
    sa.ForeignKeyConstraint(['legal_entity_id'], ['legal_entities.legal_entity_id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('borrower_id')
    )
    op.create_table('custody_documents',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('asset_id', sa.String(length=26), nullable=False),
    sa.Column('kind', sa.String(length=32), nullable=False),
    sa.Column('document_ref', sa.Text(), nullable=False),
    sa.Column('document_hash', sa.String(length=66), nullable=True),
    sa.Column('issued_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("document_hash IS NULL OR document_hash ~ '^0x[0-9a-f]{64}$'", name='ck_custody_documents_hash'),
    sa.CheckConstraint("document_ref ~ '^(vault|secret|doc)://'", name='ck_custody_documents_ref'),
    sa.ForeignKeyConstraint(['asset_id'], ['gpu_assets.asset_id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('borrower_wallets',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('borrower_id', sa.String(length=26), nullable=False),
    sa.Column('chain_id', sa.BigInteger(), nullable=False),
    sa.Column('address', sa.String(length=42), nullable=False),
    sa.Column('role', sa.String(length=16), nullable=False),
    sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('released_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("address ~ '^0x[0-9a-f]{40}$'", name='ck_borrower_wallets_addr'),
    sa.CheckConstraint("role IN ('SIGNER','PAYEE','VIEWER')", name='ck_borrower_wallets_role'),
    sa.ForeignKeyConstraint(['borrower_id'], ['borrowers.borrower_id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('uq_borrower_wallets_active', 'borrower_wallets', ['chain_id', 'address'], unique=True, postgresql_where='released_at IS NULL')
    op.create_table('provider_accounts',
    sa.Column('provider_account_id', sa.String(length=200), nullable=False),
    sa.Column('provider_id', sa.String(length=64), nullable=False),
    sa.Column('external_account_id', sa.String(length=128), nullable=False),
    sa.Column('borrower_id', sa.String(length=26), nullable=False),
    sa.Column('roles', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
    sa.Column('auth_scope', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
    sa.Column('credential_ref', sa.Text(), nullable=True),
    sa.Column('control_version', sa.Integer(), server_default='0', nullable=False),
    sa.Column('last_verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("credential_ref IS NULL OR credential_ref ~ '^(secret|vault)://'", name='ck_provider_accounts_credential_ref'),
    sa.CheckConstraint("provider_account_id = provider_id || ':' || external_account_id", name='ck_provider_accounts_id_format'),
    sa.CheckConstraint('control_version >= 0', name='ck_provider_accounts_control_version'),
    sa.ForeignKeyConstraint(['borrower_id'], ['borrowers.borrower_id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['provider_id'], ['providers.provider_id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('provider_account_id'),
    sa.UniqueConstraint('provider_id', 'external_account_id', name='uq_provider_accounts_external')
    )
    op.create_table('account_authorizations',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('provider_account_id', sa.String(length=200), nullable=False),
    sa.Column('purpose', sa.String(length=32), nullable=False),
    sa.Column('granted_by', sa.String(length=16), nullable=False),
    sa.Column('signer_address', sa.String(length=42), nullable=True),
    sa.Column('key_epoch', sa.Integer(), server_default='0', nullable=False),
    sa.Column('nonce', sa.BigInteger(), nullable=True),
    sa.Column('signature_ref', sa.Text(), nullable=True),
    sa.Column('granted_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("granted_by IN ('borrower', 'lp', 'underwriter', 'operator', 'keeper', 'guardian', 'treasury', 'system')", name='ck_account_authorizations_role'),
    sa.CheckConstraint("purpose IN ('WALLET_LINK','AGREEMENT_CONSENT','CONTROL_ATTESTATION','API_SCOPE')", name='ck_account_authorizations_purpose'),
    sa.CheckConstraint("signer_address IS NULL OR signer_address ~ '^0x[0-9a-f]{40}$'", name='ck_account_authorizations_addr'),
    sa.CheckConstraint('expires_at IS NULL OR expires_at > granted_at', name='ck_account_authorizations_expiry'),
    sa.ForeignKeyConstraint(['provider_account_id'], ['provider_accounts.provider_account_id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('signer_address', 'purpose', 'nonce', name='uq_account_authorizations_nonce')
    )
    op.create_table('asset_provider_assignments',
    sa.Column('assignment_id', sa.String(length=26), nullable=False),
    sa.Column('asset_id', sa.String(length=26), nullable=False),
    sa.Column('provider_account_id', sa.String(length=200), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('reason', sa.String(length=16), nullable=False),
    sa.Column('provenance', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.CheckConstraint("assignment_id ~ '^[0-9A-HJKMNP-TV-Z]{26}$'", name='ck_asset_assignments_ulid'),
    sa.CheckConstraint("reason IN ('ONBOARD','MOVE','RMA','OFFBOARD')", name='ck_asset_assignments_reason'),
    sa.CheckConstraint('ended_at IS NULL OR ended_at > started_at', name='ck_asset_assignments_period'),
    sa.ForeignKeyConstraint(['asset_id'], ['gpu_assets.asset_id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['provider_account_id'], ['provider_accounts.provider_account_id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('assignment_id')
    )
    op.create_index('uq_asset_assignments_open', 'asset_provider_assignments', ['asset_id'], unique=True, postgresql_where='ended_at IS NULL')
    op.create_table('control_agreements',
    sa.Column('control_agreement_id', sa.String(length=26), nullable=False),
    sa.Column('borrower_id', sa.String(length=26), nullable=False),
    sa.Column('provider_account_id', sa.String(length=200), nullable=False),
    sa.Column('control_grade', sa.String(length=2), server_default='E0', nullable=False),
    sa.Column('subject', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
    sa.Column('receiver_chain_id', sa.BigInteger(), nullable=True),
    sa.Column('receiver_address', sa.String(length=42), nullable=True),
    sa.Column('change_authority', sa.String(length=16), server_default='BORROWER_ALONE', nullable=False),
    sa.Column('agreement_hash', sa.String(length=66), nullable=True),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.Column('effective_from', sa.DateTime(timezone=True), nullable=True),
    sa.Column('effective_to', sa.DateTime(timezone=True), nullable=True),
    sa.Column('precedence', sa.Integer(), server_default='0', nullable=False),
    sa.Column('last_observed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('observation_provenance', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('poc_ref', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("agreement_hash IS NULL OR agreement_hash ~ '^0x[0-9a-f]{64}$'", name='ck_control_agreements_hash'),
    sa.CheckConstraint("change_authority IN ('BORROWER_ALONE','PROTOCOL','PARTNER','MULTI')", name='ck_control_agreements_authority'),
    sa.CheckConstraint("control_agreement_id ~ '^[0-9A-HJKMNP-TV-Z]{26}$'", name='ck_control_agreements_ulid'),
    sa.CheckConstraint("control_grade IN ('E0', 'E1', 'E2', 'E3')", name='ck_control_agreements_grade'),
    sa.CheckConstraint("control_grade IN ('E0','E1') OR (change_authority <> 'BORROWER_ALONE' AND agreement_hash IS NOT NULL AND effective_from IS NOT NULL AND poc_ref IS NOT NULL AND receiver_address IS NOT NULL)", name='ck_control_agreements_e2_requirements'),
    sa.CheckConstraint("receiver_address IS NULL OR receiver_address ~ '^0x[0-9a-f]{40}$'", name='ck_control_agreements_receiver'),
    sa.CheckConstraint('effective_to IS NULL OR effective_from IS NULL OR effective_to > effective_from', name='ck_control_agreements_period'),
    sa.CheckConstraint('version >= 1', name='ck_control_agreements_version'),
    sa.ForeignKeyConstraint(['borrower_id'], ['borrowers.borrower_id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['provider_account_id'], ['provider_accounts.provider_account_id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('control_agreement_id'),
    sa.UniqueConstraint('provider_account_id', 'version', name='uq_control_agreements_version')
    )
    op.create_table('control_observations',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('control_agreement_id', sa.String(length=26), nullable=False),
    sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('observed_grade', sa.String(length=2), nullable=False),
    sa.Column('receiver_address', sa.String(length=42), nullable=True),
    sa.Column('source', sa.String(length=16), nullable=False),
    sa.Column('provenance', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('raw_hash', sa.String(length=66), nullable=True),
    sa.CheckConstraint("observed_grade IN ('E0', 'E1', 'E2', 'E3')", name='ck_control_observations_grade'),
    sa.CheckConstraint("source IN ('API','RPC','MANUAL','SIMULATED')", name='ck_control_observations_source'),
    sa.ForeignKeyConstraint(['control_agreement_id'], ['control_agreements.control_agreement_id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_control_observations_agreement_time', 'control_observations', ['control_agreement_id', 'observed_at'], unique=False)
    op.create_table('facilities',
    sa.Column('facility_id', sa.String(length=26), nullable=False),
    sa.Column('borrower_id', sa.String(length=26), nullable=False),
    sa.Column('vault_id', sa.String(length=64), nullable=False),
    sa.Column('loan_chain_id', sa.BigInteger(), nullable=False),
    sa.Column('loan_token_address', sa.String(length=42), nullable=True),
    sa.Column('loan_decimals', sa.SmallInteger(), nullable=False),
    sa.Column('state', sa.String(length=24), server_default='DRAFT', nullable=False),
    sa.Column('approved_cap', sa.Numeric(precision=78, scale=0), server_default='0', nullable=False),
    sa.Column('advance_rate_bps', sa.Integer(), server_default='0', nullable=False),
    sa.Column('terms_version_id', sa.String(length=64), nullable=False),
    sa.Column('policy_version_id', sa.String(length=64), nullable=False),
    sa.Column('required_verification', sa.String(length=32), server_default='ATTESTCOIN_NATIVE', nullable=False),
    sa.Column('execution_profile', sa.String(length=32), nullable=False),
    sa.Column('principal', sa.Numeric(precision=78, scale=0), server_default='0', nullable=False),
    sa.Column('unpaid_interest', sa.Numeric(precision=78, scale=0), server_default='0', nullable=False),
    sa.Column('fees', sa.Numeric(precision=78, scale=0), server_default='0', nullable=False),
    sa.Column('reserved_draws', sa.Numeric(precision=78, scale=0), server_default='0', nullable=False),
    sa.Column('rate_bps', sa.Integer(), server_default='0', nullable=False),
    sa.Column('accrual_basis', sa.String(length=16), server_default='ACT_365', nullable=False),
    sa.Column('maturity_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('control_agreement_id', sa.String(length=26), nullable=True),
    sa.Column('funded_agreement_version', sa.Integer(), nullable=True),
    sa.Column('manifest_hash', sa.String(length=71), nullable=True),
    sa.Column('test_only_terms', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("accrual_basis = 'ACT_365'", name='ck_facilities_accrual_basis'),
    sa.CheckConstraint("execution_profile <> 'PRODUCTION' OR NOT test_only_terms", name='ck_facilities_prod_not_test_terms'),
    sa.CheckConstraint("execution_profile IN ('LOCAL_MOCK', 'NATIVE_TESTNET', 'PRODUCTION')", name='ck_facilities_profile'),
    sa.CheckConstraint("facility_id ~ '^[0-9A-HJKMNP-TV-Z]{26}$'", name='ck_facilities_ulid'),
    sa.CheckConstraint("loan_token_address IS NULL OR loan_token_address ~ '^0x[0-9a-f]{40}$'", name='ck_facilities_loan_token'),
    sa.CheckConstraint("manifest_hash IS NULL OR manifest_hash ~ '^sha256:[0-9a-f]{64}$'", name='ck_facilities_manifest_hash'),
    sa.CheckConstraint("required_verification = 'ATTESTCOIN_NATIVE'", name='ck_facilities_required_verification'),
    sa.CheckConstraint("state IN ('DRAFT', 'UNDER_REVIEW', 'CONTROL_PENDING', 'ACTIVE', 'DRAW_FROZEN', 'DELINQUENT', 'DEFAULTED', 'RECOVERY', 'REPAID', 'RELEASED', 'CLOSED_WITH_LOSS')", name='ck_facilities_state'),
    sa.CheckConstraint("state IN ('DRAFT','UNDER_REVIEW','CONTROL_PENDING') OR (control_agreement_id IS NOT NULL AND funded_agreement_version IS NOT NULL)", name='ck_facilities_funded_requires_control'),
    sa.CheckConstraint("state NOT IN ('REPAID','RELEASED') OR (principal = 0 AND unpaid_interest = 0 AND fees = 0)", name='ck_facilities_released_debt_zero'),
    sa.CheckConstraint('advance_rate_bps BETWEEN 0 AND 10000', name='ck_facilities_advance_rate'),
    sa.CheckConstraint('approved_cap >= 0 AND principal >= 0 AND unpaid_interest >= 0 AND fees >= 0 AND reserved_draws >= 0', name='ck_facilities_money_nonneg'),
    sa.CheckConstraint('loan_decimals BETWEEN 0 AND 36', name='ck_facilities_loan_decimals'),
    sa.CheckConstraint('rate_bps >= 0', name='ck_facilities_rate'),
    sa.ForeignKeyConstraint(['borrower_id'], ['borrowers.borrower_id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['control_agreement_id'], ['control_agreements.control_agreement_id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['policy_version_id'], ['policy_versions.policy_version_id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['terms_version_id'], ['terms_versions.terms_version_id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('facility_id')
    )
    op.create_index('ix_facilities_borrower_state', 'facilities', ['borrower_id', 'state'], unique=False)
    op.create_table('credit_decisions',
    sa.Column('credit_decision_id', sa.String(length=26), nullable=False),
    sa.Column('facility_id', sa.String(length=26), nullable=False),
    sa.Column('decided_by', sa.String(length=16), nullable=False),
    sa.Column('policy_version_id', sa.String(length=64), nullable=False),
    sa.Column('inputs', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('limit_amount', sa.Numeric(precision=78, scale=0), nullable=False),
    sa.Column('decided_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('valid_until', sa.DateTime(timezone=True), nullable=False),
    sa.Column('freshness_checkpoint', sa.Text(), nullable=True),
    sa.Column('status', sa.String(length=16), server_default='DRAFT', nullable=False),
    sa.Column('execution_profile', sa.String(length=32), nullable=False),
    sa.CheckConstraint("credit_decision_id ~ '^[0-9A-HJKMNP-TV-Z]{26}$'", name='ck_credit_decisions_ulid'),
    sa.CheckConstraint("decided_by IN ('underwriter','system')", name='ck_credit_decisions_decider'),
    sa.CheckConstraint("execution_profile IN ('LOCAL_MOCK', 'NATIVE_TESTNET', 'PRODUCTION')", name='ck_credit_decisions_profile'),
    sa.CheckConstraint("status IN ('DRAFT','APPROVED','EXPIRED','REVOKED')", name='ck_credit_decisions_status'),
    sa.CheckConstraint('limit_amount >= 0', name='ck_credit_decisions_limit'),
    sa.CheckConstraint('valid_until > decided_at', name='ck_credit_decisions_validity'),
    sa.ForeignKeyConstraint(['facility_id'], ['facilities.facility_id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['policy_version_id'], ['policy_versions.policy_version_id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('credit_decision_id')
    )
    op.create_index('ix_credit_decisions_facility', 'credit_decisions', ['facility_id', 'status'], unique=False)
    op.create_table('facility_state_transitions',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('facility_id', sa.String(length=26), nullable=False),
    sa.Column('from_state', sa.String(length=24), nullable=False),
    sa.Column('to_state', sa.String(length=24), nullable=False),
    sa.Column('trigger', sa.String(length=64), nullable=False),
    sa.Column('authority', sa.String(length=24), nullable=False),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('occurred_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("authority <> 'oracle' AND authority <> 'keeper'", name='ck_facility_transitions_no_oracle'),
    sa.CheckConstraint("from_state IN ('DRAFT', 'UNDER_REVIEW', 'CONTROL_PENDING', 'ACTIVE', 'DRAW_FROZEN', 'DELINQUENT', 'DEFAULTED', 'RECOVERY', 'REPAID', 'RELEASED', 'CLOSED_WITH_LOSS') AND to_state IN ('DRAFT', 'UNDER_REVIEW', 'CONTROL_PENDING', 'ACTIVE', 'DRAW_FROZEN', 'DELINQUENT', 'DEFAULTED', 'RECOVERY', 'REPAID', 'RELEASED', 'CLOSED_WITH_LOSS')", name='ck_facility_transitions_states'),
    sa.ForeignKeyConstraint(['facility_id'], ['facilities.facility_id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_facility_transitions_facility', 'facility_state_transitions', ['facility_id', 'occurred_at'], unique=False)
    op.execute(TRIGGER_SQL)


def downgrade() -> None:
    op.execute(TRIGGER_DROP_SQL)
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index('ix_facility_transitions_facility', table_name='facility_state_transitions')
    op.drop_table('facility_state_transitions')
    op.drop_index('ix_credit_decisions_facility', table_name='credit_decisions')
    op.drop_table('credit_decisions')
    op.drop_index('ix_facilities_borrower_state', table_name='facilities')
    op.drop_table('facilities')
    op.drop_index('ix_control_observations_agreement_time', table_name='control_observations')
    op.drop_table('control_observations')
    op.drop_table('control_agreements')
    op.drop_index('uq_asset_assignments_open', table_name='asset_provider_assignments', postgresql_where='ended_at IS NULL')
    op.drop_table('asset_provider_assignments')
    op.drop_table('account_authorizations')
    op.drop_table('provider_accounts')
    op.drop_index('uq_borrower_wallets_active', table_name='borrower_wallets', postgresql_where='released_at IS NULL')
    op.drop_table('borrower_wallets')
    op.drop_table('custody_documents')
    op.drop_table('borrowers')
    op.drop_table('asset_identity_keys')
    op.drop_table('asset_encumbrances')
    op.drop_table('terms_versions')
    op.drop_table('providers')
    op.drop_table('policy_versions')
    op.drop_table('legal_entities')
    op.drop_table('gpu_assets')
    # ### end Alembic commands ###
