"""Chain-projected receivable and repayment history (read models replayed from finalized logs).

Revision ID: 0006
Revises: 0005
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

ADDR_RE = "~ '^0x[0-9a-f]{40}$'"
HEX32_RE = "~ '^0x[0-9a-f]{64}$'"
TIER = "tier IN ('PENDING','FINALIZED')"


def upgrade():
    op.create_table(
        "proj_receivables",
        sa.Column("deployment_id", sa.String(length=26), nullable=False),
        sa.Column("tier", sa.String(length=10), nullable=False),
        sa.Column("receivable_key", sa.String(length=66), nullable=False),
        sa.Column("account_key", sa.String(length=66), nullable=False),
        sa.Column("obligation_ref", sa.String(length=66), nullable=False),
        sa.Column("facility_key", sa.String(length=66), nullable=True),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("net", sa.Numeric(78, 0), nullable=False, server_default="0"),
        sa.Column("paid", sa.Numeric(78, 0), nullable=False, server_default="0"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("disputed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("recognition_tx_hash", sa.String(length=66), nullable=False),
        sa.Column("last_tx_hash", sa.String(length=66), nullable=False),
        sa.Column("first_block", sa.BigInteger(), nullable=False),
        sa.Column("last_block", sa.BigInteger(), nullable=False),
        sa.Column("history", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint(f"receivable_key {HEX32_RE} AND account_key {HEX32_RE} AND obligation_ref {HEX32_RE}", name="ck_proj_receivables_keys"),
        sa.CheckConstraint(f"recognition_tx_hash {HEX32_RE} AND last_tx_hash {HEX32_RE}", name="ck_proj_receivables_hashes"),
        sa.CheckConstraint("state IN ('OPEN','ASSIGNED','PAID','CANCELLED')", name="ck_proj_receivables_state"),
        sa.CheckConstraint("net >= 0 AND paid >= 0 AND paid <= net AND revision >= 1", name="ck_proj_receivables_amounts"),
        sa.CheckConstraint(TIER, name="ck_proj_receivables_tier"),
        sa.ForeignKeyConstraint(["deployment_id"], ["chain_deployments.deployment_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("deployment_id", "tier", "receivable_key"),
    )
    op.create_index("ix_proj_receivables_account", "proj_receivables", ["deployment_id", "tier", "account_key"])
    op.create_index("ix_proj_receivables_facility", "proj_receivables", ["deployment_id", "tier", "facility_key"])
    op.create_table(
        "proj_repayments",
        sa.Column("deployment_id", sa.String(length=26), nullable=False),
        sa.Column("tier", sa.String(length=10), nullable=False),
        sa.Column("tx_hash", sa.String(length=66), nullable=False),
        sa.Column("log_index", sa.Integer(), nullable=False),
        sa.Column("facility_key", sa.String(length=66), nullable=False),
        sa.Column("repaid_contract", sa.String(length=48), nullable=False),
        sa.Column("payer", sa.String(length=42), nullable=False),
        sa.Column("settlement_ref", sa.String(length=66), nullable=True),
        sa.Column("requested", sa.Numeric(78, 0), nullable=False),
        sa.Column("received", sa.Numeric(78, 0), nullable=False),
        sa.Column("fee_paid", sa.Numeric(78, 0), nullable=False),
        sa.Column("interest_paid", sa.Numeric(78, 0), nullable=False),
        sa.Column("principal_paid", sa.Numeric(78, 0), nullable=False),
        sa.Column("excess", sa.Numeric(78, 0), nullable=False),
        sa.Column("new_debt", sa.Numeric(78, 0), nullable=False),
        sa.Column("block_number", sa.BigInteger(), nullable=False),
        sa.Column("block_hash", sa.String(length=66), nullable=False),
        sa.Column("block_timestamp", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(f"tx_hash {HEX32_RE} AND facility_key {HEX32_RE} AND block_hash {HEX32_RE}", name="ck_proj_repayments_hashes"),
        sa.CheckConstraint(f"payer {ADDR_RE}", name="ck_proj_repayments_payer"),
        sa.CheckConstraint("repaid_contract IN ('RepaymentRouter','CreditFacilityManager')", name="ck_proj_repayments_contract"),
        sa.CheckConstraint("requested >= 0 AND received >= 0 AND fee_paid >= 0 AND interest_paid >= 0 AND principal_paid >= 0 AND excess >= 0 AND new_debt >= 0 AND fee_paid + interest_paid + principal_paid + excess = received", name="ck_proj_repayments_amounts"),
        sa.CheckConstraint(TIER, name="ck_proj_repayments_tier"),
        sa.ForeignKeyConstraint(["deployment_id"], ["chain_deployments.deployment_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("deployment_id", "tier", "tx_hash", "log_index"),
    )
    op.create_index("ix_proj_repayments_facility", "proj_repayments", ["deployment_id", "tier", "facility_key"])


def downgrade():
    op.drop_index("ix_proj_repayments_facility", table_name="proj_repayments")
    op.drop_table("proj_repayments")
    op.drop_index("ix_proj_receivables_facility", table_name="proj_receivables")
    op.drop_index("ix_proj_receivables_account", table_name="proj_receivables")
    op.drop_table("proj_receivables")
