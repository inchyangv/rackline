"""Durable GPU API challenges, review workflow, commands and facility ID bindings.

Revision ID: 0005
Revises: 0004
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("api_login_challenges",
        sa.Column("nonce", sa.String(64), primary_key=True),
        sa.Column("wallet", sa.String(42), nullable=False),
        sa.Column("chain_id", sa.BigInteger(), nullable=False),
        sa.Column("app_domain", sa.String(300), nullable=False),
        sa.Column("borrower_hint", sa.String(64), nullable=False),
        sa.Column("issued_at", sa.BigInteger(), nullable=False),
        sa.Column("expires_at", sa.BigInteger(), nullable=False))
    op.create_index("ix_api_login_challenges_expires_at", "api_login_challenges", ["expires_at"])
    op.create_table("api_roles",
        sa.Column("chain_id", sa.BigInteger(), primary_key=True),
        sa.Column("wallet", sa.String(42), primary_key=True),
        sa.Column("role", sa.String(24), primary_key=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("approval_ref", sa.String(300), nullable=False))
    op.create_table("api_role_epochs",
        sa.Column("chain_id", sa.BigInteger(), primary_key=True),
        sa.Column("role", sa.String(24), primary_key=True),
        sa.Column("epoch", sa.Integer(), nullable=False, server_default="0"))
    op.create_table("api_commands",
        sa.Column("chain_id", sa.BigInteger(), primary_key=True),
        sa.Column("wallet", sa.String(42), primary_key=True),
        sa.Column("scope", sa.String(200), primary_key=True),
        sa.Column("idempotency_key", sa.String(100), primary_key=True),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("response", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_table("connection_applications",
        sa.Column("application_id", sa.String(26), primary_key=True),
        sa.Column("borrower_id", sa.String(26), sa.ForeignKey("borrowers.borrower_id"), nullable=False),
        sa.Column("provider_id", sa.String(64), sa.ForeignKey("providers.provider_id"), nullable=False),
        sa.Column("external_account_id", sa.String(128), nullable=False),
        sa.Column("evidence_ref", sa.String(300), nullable=False),
        sa.Column("reason", sa.String(1000), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="PENDING_REVIEW"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("borrower_id", "provider_id", "external_account_id", name="uq_connection_application"))
    op.create_table("operation_reviews",
        sa.Column("exception_id", sa.String(26), sa.ForeignKey("exceptions.exception_id"), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("state", sa.String(24), nullable=False, server_default="OPEN"),
        sa.Column("assignee", sa.String(42)),
        sa.Column("last_reason", sa.String(1000)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_table("facility_chain_bindings",
        sa.Column("deployment_id", sa.String(26), sa.ForeignKey("chain_deployments.deployment_id"), primary_key=True),
        sa.Column("facility_id", sa.String(26), sa.ForeignKey("facilities.facility_id"), primary_key=True),
        sa.Column("onchain_id", sa.String(66), nullable=False),
        sa.Column("binding_tx_hash", sa.String(66), nullable=False),
        sa.UniqueConstraint("deployment_id", "onchain_id", name="uq_facility_onchain_binding"))


def downgrade():
    for table in ("facility_chain_bindings", "operation_reviews", "connection_applications", "api_commands", "api_role_epochs", "api_roles", "api_login_challenges"):
        op.drop_table(table)
