"""Facility credit status projection: state triggers, recovery schedule, default, reserve, impairment, write-off.

Revision ID: 0007
Revises: 0006
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

HEX32_RE = "~ '^0x[0-9a-f]{64}$'"
TIER = "tier IN ('PENDING','FINALIZED')"
STATES = "('DRAFT','UNDER_REVIEW','CONTROL_PENDING','ACTIVE','DRAW_FROZEN','DELINQUENT','DEFAULTED','RECOVERY','REPAID','RELEASED','CLOSED_WITH_LOSS')"


def upgrade():
    op.create_table(
        "proj_facility_credit",
        sa.Column("deployment_id", sa.String(length=26), nullable=False),
        sa.Column("tier", sa.String(length=10), nullable=False),
        sa.Column("facility_key", sa.String(length=66), nullable=False),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column("state_trigger", sa.String(length=66), nullable=True),
        sa.Column("state_authority", sa.String(length=42), nullable=True),
        sa.Column("state_changed_at", sa.BigInteger(), nullable=True),
        sa.Column("state_tx_hash", sa.String(length=66), nullable=True),
        sa.Column("schedule_due_at", sa.BigInteger(), nullable=True),
        sa.Column("schedule_grace_seconds", sa.BigInteger(), nullable=True),
        sa.Column("schedule_due_amount", sa.Numeric(78, 0), nullable=True),
        sa.Column("schedule_set_at", sa.BigInteger(), nullable=True),
        sa.Column("disputed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("default_reason", sa.String(length=66), nullable=True),
        sa.Column("default_approved_at", sa.BigInteger(), nullable=True),
        sa.Column("reserve_owner", sa.String(length=42), nullable=True),
        sa.Column("reserve_pledged", sa.Numeric(78, 0), nullable=False, server_default="0"),
        sa.Column("reserve_applied", sa.Numeric(78, 0), nullable=False, server_default="0"),
        sa.Column("impairment", sa.Numeric(78, 0), nullable=False, server_default="0"),
        sa.Column("loss_id", sa.String(length=66), nullable=True),
        sa.Column("loss_amount", sa.Numeric(78, 0), nullable=True),
        sa.Column("written_off_at", sa.BigInteger(), nullable=True),
        sa.Column("transitions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("last_block", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(f"facility_key {HEX32_RE}", name="ck_proj_facility_credit_key"),
        sa.CheckConstraint(f"state IN {STATES}", name="ck_proj_facility_credit_state"),
        sa.CheckConstraint(
            "reserve_pledged >= 0 AND reserve_applied >= 0 AND impairment >= 0 AND (loss_amount IS NULL OR loss_amount >= 0)",
            name="ck_proj_facility_credit_amounts",
        ),
        sa.CheckConstraint("(loss_id IS NULL) = (written_off_at IS NULL)", name="ck_proj_facility_credit_writeoff"),
        sa.CheckConstraint(TIER, name="ck_proj_facility_credit_tier"),
        sa.ForeignKeyConstraint(["deployment_id"], ["chain_deployments.deployment_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("deployment_id", "tier", "facility_key"),
    )


def downgrade():
    op.drop_table("proj_facility_credit")
