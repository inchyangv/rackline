"""Durable API identity, review commands and explicit on-chain ID bindings (GPU-045)."""

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .models import Base


class LoginChallenge(Base):
    __tablename__ = "api_login_challenges"
    nonce: Mapped[str] = mapped_column(String(64), primary_key=True)
    wallet: Mapped[str] = mapped_column(String(42), nullable=False)
    chain_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    app_domain: Mapped[str] = mapped_column(String(300), nullable=False)
    borrower_hint: Mapped[str] = mapped_column(String(64), nullable=False)
    issued_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    expires_at: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)


class ApiRole(Base):
    __tablename__ = "api_roles"
    chain_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    wallet: Mapped[str] = mapped_column(String(42), primary_key=True)
    role: Mapped[str] = mapped_column(String(24), primary_key=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    approval_ref: Mapped[str] = mapped_column(String(300), nullable=False)


class ApiRoleEpoch(Base):
    __tablename__ = "api_role_epochs"
    chain_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    role: Mapped[str] = mapped_column(String(24), primary_key=True)
    epoch: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")


class ApiCommand(Base):
    __tablename__ = "api_commands"
    chain_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    wallet: Mapped[str] = mapped_column(String(42), primary_key=True)
    scope: Mapped[str] = mapped_column(String(200), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(100), primary_key=True)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ConnectionApplication(Base):
    __tablename__ = "connection_applications"
    application_id: Mapped[str] = mapped_column(String(26), primary_key=True)
    borrower_id: Mapped[str] = mapped_column(String(26), ForeignKey("borrowers.borrower_id"), nullable=False)
    provider_id: Mapped[str] = mapped_column(String(64), ForeignKey("providers.provider_id"), nullable=False)
    external_account_id: Mapped[str] = mapped_column(String(128), nullable=False)
    evidence_ref: Mapped[str] = mapped_column(String(300), nullable=False)
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, server_default="PENDING_REVIEW")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (UniqueConstraint("borrower_id", "provider_id", "external_account_id", name="uq_connection_application"),)


class OperationReview(Base):
    __tablename__ = "operation_reviews"
    exception_id: Mapped[str] = mapped_column(String(26), ForeignKey("exceptions.exception_id"), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    state: Mapped[str] = mapped_column(String(24), nullable=False, server_default="OPEN")
    assignee: Mapped[str | None] = mapped_column(String(42))
    last_reason: Mapped[str | None] = mapped_column(String(1000))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class FacilityBinding(Base):
    __tablename__ = "facility_chain_bindings"
    deployment_id: Mapped[str] = mapped_column(String(26), ForeignKey("chain_deployments.deployment_id"), primary_key=True)
    facility_id: Mapped[str] = mapped_column(String(26), ForeignKey("facilities.facility_id"), primary_key=True)
    onchain_id: Mapped[str] = mapped_column(String(66), nullable=False)
    binding_tx_hash: Mapped[str] = mapped_column(String(66), nullable=False)
    __table_args__ = (UniqueConstraint("deployment_id", "onchain_id", name="uq_facility_onchain_binding"),)
