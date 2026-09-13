"""asset rights, account-link history and review flags (GPU-017).

Hand-written (no autogenerate): adds lifecycle/RMA/ownership-review columns to gpu_assets, key lifetimes to
asset_identity_keys (active-key uniqueness instead of a global unique), facility/status to
asset_encumbrances with a single-open-facility-encumbrance index (no double financing), and two new tables:
provider_account_links (link history with its own review state; linking is never approval) and
asset_review_flags (duplicate listing / unverified ownership or lease / priority conflict).

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-14
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None

ROLES = "('borrower','lp','underwriter','operator','keeper','guardian','treasury','system')"
REF_RE = "~ '^(vault|secret|doc)://'"


def upgrade() -> None:
    # --- gpu_assets: lifecycle, RMA lineage, separate ownership review
    op.add_column('gpu_assets', sa.Column('status', sa.String(length=16), server_default='ACTIVE', nullable=False))
    op.add_column('gpu_assets', sa.Column('replaces_asset_id', sa.String(length=26), nullable=True))
    op.add_column('gpu_assets', sa.Column('ownership_review', sa.String(length=16), server_default='UNVERIFIED', nullable=False))
    op.add_column('gpu_assets', sa.Column('identity_confidence', sa.String(length=8), server_default='LOW', nullable=False))
    op.add_column('gpu_assets', sa.Column('review_ref', sa.Text(), nullable=True))
    op.create_foreign_key('fk_gpu_assets_replaces', 'gpu_assets', 'gpu_assets', ['replaces_asset_id'], ['asset_id'], ondelete='RESTRICT')
    op.create_check_constraint('ck_gpu_assets_status', 'gpu_assets', "status IN ('ACTIVE','RETIRED')")
    op.create_check_constraint('ck_gpu_assets_no_self_replace', 'gpu_assets', "replaces_asset_id IS NULL OR replaces_asset_id <> asset_id")
    op.create_check_constraint('ck_gpu_assets_ownership_review', 'gpu_assets', "ownership_review IN ('UNVERIFIED','VERIFIED','REJECTED')")
    op.create_check_constraint('ck_gpu_assets_identity_confidence', 'gpu_assets', "identity_confidence IN ('LOW','MEDIUM','HIGH')")
    op.create_check_constraint('ck_gpu_assets_review_ref', 'gpu_assets', f"review_ref IS NULL OR review_ref {REF_RE}")
    op.create_check_constraint('ck_gpu_assets_eligible_requires_review', 'gpu_assets', "NOT eligible OR (ownership_review = 'VERIFIED' AND status = 'ACTIVE')")

    # --- asset_identity_keys: key lifetime, active-key uniqueness, NIC_MAC scheme
    op.add_column('asset_identity_keys', sa.Column('recorded_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False))
    op.add_column('asset_identity_keys', sa.Column('retired_at', sa.DateTime(timezone=True), nullable=True))
    op.drop_constraint('uq_asset_identity_keys_value', 'asset_identity_keys', type_='unique')
    op.drop_constraint('ck_asset_identity_keys_scheme', 'asset_identity_keys', type_='check')
    op.create_check_constraint('ck_asset_identity_keys_scheme', 'asset_identity_keys', "scheme IN ('GPU_UUID','SERIAL','HOST_ID','GROUP_ID','NFT_TOKEN','NIC_MAC')")
    op.create_check_constraint('ck_asset_identity_keys_lifetime', 'asset_identity_keys', "retired_at IS NULL OR retired_at >= recorded_at")
    op.create_index('uq_asset_identity_keys_active', 'asset_identity_keys', ['scheme', 'value'], unique=True, postgresql_where=sa.text('retired_at IS NULL'))

    # --- asset_encumbrances: facility binding, open/released, single open facility encumbrance per asset
    op.add_column('asset_encumbrances', sa.Column('facility_id', sa.String(length=26), nullable=True))
    op.add_column('asset_encumbrances', sa.Column('status', sa.String(length=16), server_default='OPEN', nullable=False))
    op.add_column('asset_encumbrances', sa.Column('released_at', sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key('fk_asset_encumbrances_facility', 'asset_encumbrances', 'facilities', ['facility_id'], ['facility_id'], ondelete='RESTRICT')
    op.create_check_constraint('ck_asset_encumbrances_status', 'asset_encumbrances', "status IN ('OPEN','RELEASED')")
    op.create_check_constraint('ck_asset_encumbrances_released', 'asset_encumbrances', "(status = 'RELEASED') = (released_at IS NOT NULL)")
    op.create_index('uq_asset_encumbrances_open_facility', 'asset_encumbrances', ['asset_id'], unique=True,
                    postgresql_where=sa.text("status = 'OPEN' AND facility_id IS NOT NULL AND asset_id IS NOT NULL"))

    # --- provider_account_links
    op.create_table(
        'provider_account_links',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('provider_account_id', sa.String(length=200), nullable=False),
        sa.Column('borrower_id', sa.String(length=26), nullable=False),
        sa.Column('legal_entity_id', sa.String(length=26), nullable=False),
        sa.Column('review_state', sa.String(length=16), server_default='REGISTERED', nullable=False),
        sa.Column('linked_by', sa.String(length=16), nullable=False),
        sa.Column('linked_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('reviewed_by', sa.String(length=16), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('review_ref', sa.Text(), nullable=True),
        sa.Column('released_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('release_reason', sa.Text(), nullable=True),
        sa.Column('previous_link_id', sa.Integer(), nullable=True),
        sa.Column('provenance', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
        sa.CheckConstraint("review_state IN ('REGISTERED', 'VERIFIED', 'REJECTED')", name='ck_provider_account_links_state'),
        sa.CheckConstraint(f"linked_by IN {ROLES}", name='ck_provider_account_links_linked_by'),
        sa.CheckConstraint(f"reviewed_by IS NULL OR reviewed_by IN {ROLES}", name='ck_provider_account_links_reviewed_by'),
        sa.CheckConstraint("(review_state = 'REGISTERED') = (reviewed_at IS NULL)", name='ck_provider_account_links_reviewed'),
        sa.CheckConstraint(f"review_ref IS NULL OR review_ref {REF_RE}", name='ck_provider_account_links_ref'),
        sa.CheckConstraint("released_at IS NULL OR released_at >= linked_at", name='ck_provider_account_links_release'),
        sa.ForeignKeyConstraint(['borrower_id'], ['borrowers.borrower_id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['legal_entity_id'], ['legal_entities.legal_entity_id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['previous_link_id'], ['provider_account_links.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['provider_account_id'], ['provider_accounts.provider_account_id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('uq_provider_account_links_active', 'provider_account_links', ['provider_account_id'], unique=True, postgresql_where=sa.text('released_at IS NULL'))

    # --- asset_review_flags
    op.create_table(
        'asset_review_flags',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('asset_id', sa.String(length=26), nullable=False),
        sa.Column('flag', sa.String(length=24), nullable=False),
        sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('raised_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolved_by', sa.String(length=16), nullable=True),
        sa.Column('resolution', sa.Text(), nullable=True),
        sa.CheckConstraint("flag IN ('DUPLICATE_LISTING', 'OWNERSHIP_UNVERIFIED', 'LEASE_UNVERIFIED', 'PRIORITY_CONFLICT', 'RMA_PENDING')", name='ck_asset_review_flags_flag'),
        sa.CheckConstraint(f"resolved_by IS NULL OR resolved_by IN {ROLES}", name='ck_asset_review_flags_resolved_by'),
        sa.CheckConstraint("(resolved_at IS NULL) = (resolved_by IS NULL)", name='ck_asset_review_flags_resolution'),
        sa.ForeignKeyConstraint(['asset_id'], ['gpu_assets.asset_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_asset_review_flags_open', 'asset_review_flags', ['asset_id'], unique=False, postgresql_where=sa.text('resolved_at IS NULL'))


def downgrade() -> None:
    op.drop_index('ix_asset_review_flags_open', table_name='asset_review_flags')
    op.drop_table('asset_review_flags')
    op.drop_index('uq_provider_account_links_active', table_name='provider_account_links')
    op.drop_table('provider_account_links')

    op.drop_index('uq_asset_encumbrances_open_facility', table_name='asset_encumbrances')
    op.drop_constraint('ck_asset_encumbrances_released', 'asset_encumbrances', type_='check')
    op.drop_constraint('ck_asset_encumbrances_status', 'asset_encumbrances', type_='check')
    op.drop_constraint('fk_asset_encumbrances_facility', 'asset_encumbrances', type_='foreignkey')
    op.drop_column('asset_encumbrances', 'released_at')
    op.drop_column('asset_encumbrances', 'status')
    op.drop_column('asset_encumbrances', 'facility_id')

    op.drop_index('uq_asset_identity_keys_active', table_name='asset_identity_keys')
    op.drop_constraint('ck_asset_identity_keys_lifetime', 'asset_identity_keys', type_='check')
    op.drop_constraint('ck_asset_identity_keys_scheme', 'asset_identity_keys', type_='check')
    op.create_check_constraint('ck_asset_identity_keys_scheme', 'asset_identity_keys', "scheme IN ('GPU_UUID','SERIAL','HOST_ID','GROUP_ID','NFT_TOKEN')")
    # retired history rows would violate the old global unique; keep only the active key value per identity
    op.execute("DELETE FROM asset_identity_keys WHERE retired_at IS NOT NULL")
    op.create_unique_constraint('uq_asset_identity_keys_value', 'asset_identity_keys', ['scheme', 'value'])
    op.drop_column('asset_identity_keys', 'retired_at')
    op.drop_column('asset_identity_keys', 'recorded_at')

    for ck in ('ck_gpu_assets_eligible_requires_review', 'ck_gpu_assets_review_ref', 'ck_gpu_assets_identity_confidence',
               'ck_gpu_assets_ownership_review', 'ck_gpu_assets_no_self_replace', 'ck_gpu_assets_status'):
        op.drop_constraint(ck, 'gpu_assets', type_='check')
    op.drop_constraint('fk_gpu_assets_replaces', 'gpu_assets', type_='foreignkey')
    for col in ('review_ref', 'identity_confidence', 'ownership_review', 'replaces_asset_id', 'status'):
        op.drop_column('gpu_assets', col)
