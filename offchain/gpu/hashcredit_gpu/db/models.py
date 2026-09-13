"""
SQLAlchemy 2.0 declarative models for the GPU-015 core domain (PostgreSQL).

These models mirror the Alembic migrations under `migrations/versions/`; `hashcredit-gpu-db check`
and `tests/test_migrations.py` assert the two never drift. Production schemas are created only by
migrations (never `metadata.create_all()`).

Money columns are NUMERIC(78,0) base units paired with explicit asset columns (chain id, token address,
decimals). Sensitive material is stored as references only (`*_ref`), never as content.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from ..domain import enums as E

ULID = String(26)
ADDR = String(42)
HEX32 = String(66)
MONEY = Numeric(78, 0)

ULID_CHECK = "~ '^[0-9A-HJKMNP-TV-Z]{26}$'"
ADDR_CHECK = "~ '^0x[0-9a-f]{40}$'"
HEX32_CHECK = "~ '^0x[0-9a-f]{64}$'"


def _in(values: type[E.StrEnum] | list[str]) -> str:
    vals = [v.value for v in values] if isinstance(values, type) else values
    return "(" + ", ".join(f"'{v}'" for v in vals) + ")"


class Base(DeclarativeBase):
    pass


class Provider(Base):
    """Provider registry row: which source environment/chain a provider settles on."""

    __tablename__ = "providers"
    provider_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    source_env_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source_chain_key: Mapped[int] = mapped_column(Integer, nullable=False)
    source_chain_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    execution_profile: Mapped[str] = mapped_column(String(32), nullable=False)
    environment_status: Mapped[str] = mapped_column(String(32), nullable=False)
    required_verification: Mapped[str] = mapped_column(String(32), nullable=False, server_default="ATTESTCOIN_NATIVE")
    manifest_hash: Mapped[str | None] = mapped_column(String(71))
    capabilities: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    test_only: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        CheckConstraint("provider_id ~ '^[a-z0-9-]+$'", name="ck_providers_id_slug"),
        CheckConstraint(f"execution_profile IN {_in(E.ExecutionProfile)}", name="ck_providers_profile"),
        CheckConstraint(f"environment_status IN {_in(E.EnvironmentStatus)}", name="ck_providers_env_status"),
        CheckConstraint("required_verification = 'ATTESTCOIN_NATIVE'", name="ck_providers_required_verification"),
        CheckConstraint("source_chain_key > 0 AND source_chain_id > 0", name="ck_providers_chain_positive"),
        CheckConstraint("manifest_hash IS NULL OR manifest_hash ~ '^sha256:[0-9a-f]{64}$'", name="ck_providers_manifest_hash"),
        CheckConstraint("(execution_profile = 'PRODUCTION') = (NOT test_only)", name="ck_providers_test_only_profile"),
        UniqueConstraint("source_env_id", "source_chain_key", "provider_id", name="uq_providers_env_key"),
    )


class LegalEntity(Base):
    __tablename__ = "legal_entities"
    legal_entity_id: Mapped[str] = mapped_column(ULID, primary_key=True)
    jurisdiction: Mapped[str | None] = mapped_column(String(64))
    registration_ref: Mapped[str | None] = mapped_column(Text)
    beneficial_owners_ref: Mapped[str | None] = mapped_column(Text)
    signing_authority_ref: Mapped[str | None] = mapped_column(Text)
    documents_ref: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        CheckConstraint(f"legal_entity_id {ULID_CHECK}", name="ck_legal_entities_ulid"),
        CheckConstraint(
            "(registration_ref IS NULL OR registration_ref ~ '^(vault|secret|doc)://') AND "
            "(beneficial_owners_ref IS NULL OR beneficial_owners_ref ~ '^(vault|secret|doc)://') AND "
            "(signing_authority_ref IS NULL OR signing_authority_ref ~ '^(vault|secret|doc)://')",
            name="ck_legal_entities_refs_only",
        ),
    )


class Borrower(Base):
    __tablename__ = "borrowers"
    borrower_id: Mapped[str] = mapped_column(ULID, primary_key=True)
    legal_entity_id: Mapped[str] = mapped_column(ULID, ForeignKey("legal_entities.legal_entity_id", ondelete="RESTRICT"), nullable=False)
    group_id: Mapped[str | None] = mapped_column(String(64))
    kyc_status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="NONE")
    underwriting_status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="NONE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        CheckConstraint(f"borrower_id {ULID_CHECK}", name="ck_borrowers_ulid"),
        CheckConstraint("kyc_status IN ('NONE','PENDING','VERIFIED','REJECTED')", name="ck_borrowers_kyc"),
        CheckConstraint("underwriting_status IN ('NONE','IN_REVIEW','APPROVED','DECLINED')", name="ck_borrowers_uw"),
    )


class BorrowerWallet(Base):
    __tablename__ = "borrower_wallets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    borrower_id: Mapped[str] = mapped_column(ULID, ForeignKey("borrowers.borrower_id", ondelete="CASCADE"), nullable=False)
    chain_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    address: Mapped[str] = mapped_column(ADDR, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint(f"address {ADDR_CHECK}", name="ck_borrower_wallets_addr"),
        CheckConstraint("role IN ('SIGNER','PAYEE','VIEWER')", name="ck_borrower_wallets_role"),
        # A wallet is linked to at most one borrower at a time (release before re-link).
        Index("uq_borrower_wallets_active", "chain_id", "address", unique=True, postgresql_where="released_at IS NULL"),
    )


class ProviderAccount(Base):
    __tablename__ = "provider_accounts"
    provider_account_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    provider_id: Mapped[str] = mapped_column(String(64), ForeignKey("providers.provider_id", ondelete="RESTRICT"), nullable=False)
    external_account_id: Mapped[str] = mapped_column(String(128), nullable=False)
    borrower_id: Mapped[str] = mapped_column(ULID, ForeignKey("borrowers.borrower_id", ondelete="RESTRICT"), nullable=False)
    roles: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    auth_scope: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    credential_ref: Mapped[str | None] = mapped_column(Text)
    control_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        UniqueConstraint("provider_id", "external_account_id", name="uq_provider_accounts_external"),
        CheckConstraint("provider_account_id = provider_id || ':' || external_account_id", name="ck_provider_accounts_id_format"),
        CheckConstraint("credential_ref IS NULL OR credential_ref ~ '^(secret|vault)://'", name="ck_provider_accounts_credential_ref"),
        CheckConstraint("control_version >= 0", name="ck_provider_accounts_control_version"),
    )


class AccountAuthorization(Base):
    """Auxiliary signature grants (wallet link, consent, attestation, API scope). Never source facts."""

    __tablename__ = "account_authorizations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider_account_id: Mapped[str] = mapped_column(String(200), ForeignKey("provider_accounts.provider_account_id", ondelete="CASCADE"), nullable=False)
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    granted_by: Mapped[str] = mapped_column(String(16), nullable=False)
    signer_address: Mapped[str | None] = mapped_column(ADDR)
    key_epoch: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    nonce: Mapped[int | None] = mapped_column(BigInteger)
    signature_ref: Mapped[str | None] = mapped_column(Text)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("purpose IN ('WALLET_LINK','AGREEMENT_CONSENT','CONTROL_ATTESTATION','API_SCOPE')", name="ck_account_authorizations_purpose"),
        CheckConstraint(f"granted_by IN {_in(E.Role)}", name="ck_account_authorizations_role"),
        CheckConstraint("signer_address IS NULL OR signer_address " + ADDR_CHECK, name="ck_account_authorizations_addr"),
        CheckConstraint("expires_at IS NULL OR expires_at > granted_at", name="ck_account_authorizations_expiry"),
        UniqueConstraint("signer_address", "purpose", "nonce", name="uq_account_authorizations_nonce"),
    )


class GpuAsset(Base):
    __tablename__ = "gpu_assets"
    asset_id: Mapped[str] = mapped_column(ULID, primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    sku: Mapped[str | None] = mapped_column(String(128))
    unit_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    ownership: Mapped[str] = mapped_column(String(16), nullable=False, server_default="UNKNOWN")
    custodian: Mapped[str | None] = mapped_column(String(200))
    location: Mapped[str | None] = mapped_column(String(64))
    parent_asset_id: Mapped[str | None] = mapped_column(ULID, ForeignKey("gpu_assets.asset_id", ondelete="RESTRICT"))
    eligible: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    # GPU-017 (migration 0003): lifecycle, RMA lineage and the *separate* ownership review result.
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="ACTIVE")
    replaces_asset_id: Mapped[str | None] = mapped_column(ULID, ForeignKey("gpu_assets.asset_id", ondelete="RESTRICT"))
    ownership_review: Mapped[str] = mapped_column(String(16), nullable=False, server_default="UNVERIFIED")
    identity_confidence: Mapped[str] = mapped_column(String(8), nullable=False, server_default="LOW")
    review_ref: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        CheckConstraint(f"asset_id {ULID_CHECK}", name="ck_gpu_assets_ulid"),
        CheckConstraint(f"kind IN {_in(E.AssetKind)}", name="ck_gpu_assets_kind"),
        CheckConstraint("unit_count > 0", name="ck_gpu_assets_unit_count"),
        CheckConstraint("ownership IN ('OWNED','LEASED','UNKNOWN')", name="ck_gpu_assets_ownership"),
        CheckConstraint("parent_asset_id IS NULL OR parent_asset_id <> asset_id", name="ck_gpu_assets_no_self_parent"),
        # Ownership must be confirmed before an asset can be eligible (GPU-017 sets it; DB refuses the shortcut).
        CheckConstraint("NOT eligible OR ownership <> 'UNKNOWN'", name="ck_gpu_assets_eligible_requires_ownership"),
        CheckConstraint("status IN ('ACTIVE','RETIRED')", name="ck_gpu_assets_status"),
        CheckConstraint("replaces_asset_id IS NULL OR replaces_asset_id <> asset_id", name="ck_gpu_assets_no_self_replace"),
        CheckConstraint("ownership_review IN ('UNVERIFIED','VERIFIED','REJECTED')", name="ck_gpu_assets_ownership_review"),
        CheckConstraint("identity_confidence IN ('LOW','MEDIUM','HIGH')", name="ck_gpu_assets_identity_confidence"),
        CheckConstraint("review_ref IS NULL OR review_ref ~ '^(vault|secret|doc)://'", name="ck_gpu_assets_review_ref"),
        # Identity confidence and ownership review are different facts; only a VERIFIED, ACTIVE asset may be eligible.
        CheckConstraint(
            "NOT eligible OR (ownership_review = 'VERIFIED' AND status = 'ACTIVE')",
            name="ck_gpu_assets_eligible_requires_review",
        ),
    )


class AssetIdentityKey(Base):
    __tablename__ = "asset_identity_keys"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset_id: Mapped[str] = mapped_column(ULID, ForeignKey("gpu_assets.asset_id", ondelete="CASCADE"), nullable=False)
    scheme: Mapped[str] = mapped_column(String(16), nullable=False)
    value: Mapped[str] = mapped_column(String(200), nullable=False)
    provenance: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # GPU-017: keys have a lifetime (NIC change, RMA move) — the *active* key is unique per physical identity.
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("scheme IN ('GPU_UUID','SERIAL','HOST_ID','GROUP_ID','NFT_TOKEN','NIC_MAC')", name="ck_asset_identity_keys_scheme"),
        CheckConstraint("retired_at IS NULL OR retired_at >= recorded_at", name="ck_asset_identity_keys_lifetime"),
        # The same physical identity cannot be *actively* listed as two assets; history rows keep the old value.
        Index("uq_asset_identity_keys_active", "scheme", "value", unique=True, postgresql_where="retired_at IS NULL"),
    )


class AssetProviderAssignment(Base):
    __tablename__ = "asset_provider_assignments"
    assignment_id: Mapped[str] = mapped_column(ULID, primary_key=True)
    asset_id: Mapped[str] = mapped_column(ULID, ForeignKey("gpu_assets.asset_id", ondelete="CASCADE"), nullable=False)
    provider_account_id: Mapped[str] = mapped_column(String(200), ForeignKey("provider_accounts.provider_account_id", ondelete="RESTRICT"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str] = mapped_column(String(16), nullable=False)
    provenance: Mapped[dict] = mapped_column(JSONB, nullable=False)
    __table_args__ = (
        CheckConstraint(f"assignment_id {ULID_CHECK}", name="ck_asset_assignments_ulid"),
        CheckConstraint("reason IN ('ONBOARD','MOVE','RMA','OFFBOARD')", name="ck_asset_assignments_reason"),
        CheckConstraint("ended_at IS NULL OR ended_at > started_at", name="ck_asset_assignments_period"),
        # One open assignment per asset: the same GPU cannot be live on two provider accounts.
        Index("uq_asset_assignments_open", "asset_id", unique=True, postgresql_where="ended_at IS NULL"),
    )


class AssetEncumbrance(Base):
    __tablename__ = "asset_encumbrances"
    encumbrance_id: Mapped[str] = mapped_column(ULID, primary_key=True)
    asset_id: Mapped[str | None] = mapped_column(ULID, ForeignKey("gpu_assets.asset_id", ondelete="RESTRICT"))
    # receivables live in GPU-016; the FK is added by that migration.
    receivable_id: Mapped[str | None] = mapped_column(ULID)
    holder: Mapped[str] = mapped_column(String(200), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    document_ref: Mapped[str | None] = mapped_column(Text)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # GPU-017: which facility (if ours) holds it and whether it is still open; released rows are history.
    facility_id: Mapped[str | None] = mapped_column(ULID, ForeignKey("facilities.facility_id", ondelete="RESTRICT"))
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="OPEN")
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint(f"encumbrance_id {ULID_CHECK}", name="ck_asset_encumbrances_ulid"),
        CheckConstraint("status IN ('OPEN','RELEASED')", name="ck_asset_encumbrances_status"),
        CheckConstraint("(status = 'RELEASED') = (released_at IS NOT NULL)", name="ck_asset_encumbrances_released"),
        # One open facility-held encumbrance per asset: no double financing of the same GPU (GPU-017).
        Index(
            "uq_asset_encumbrances_open_facility",
            "asset_id",
            unique=True,
            postgresql_where="status = 'OPEN' AND facility_id IS NOT NULL AND asset_id IS NOT NULL",
        ),
        CheckConstraint("asset_id IS NOT NULL OR receivable_id IS NOT NULL", name="ck_asset_encumbrances_target"),
        CheckConstraint("priority > 0", name="ck_asset_encumbrances_priority"),
        CheckConstraint("kind IN ('LIEN','ASSIGNMENT','LEASE','PLEDGE')", name="ck_asset_encumbrances_kind"),
        CheckConstraint("document_ref IS NULL OR document_ref ~ '^(vault|secret|doc)://'", name="ck_asset_encumbrances_doc_ref"),
        CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="ck_asset_encumbrances_period"),
    )


class CustodyDocument(Base):
    __tablename__ = "custody_documents"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset_id: Mapped[str] = mapped_column(ULID, ForeignKey("gpu_assets.asset_id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    document_ref: Mapped[str] = mapped_column(Text, nullable=False)
    document_hash: Mapped[str | None] = mapped_column(HEX32)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("document_ref ~ '^(vault|secret|doc)://'", name="ck_custody_documents_ref"),
        CheckConstraint("document_hash IS NULL OR document_hash " + HEX32_CHECK, name="ck_custody_documents_hash"),
    )


class PolicyVersion(Base):
    __tablename__ = "policy_versions"
    policy_version_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    approved_by: Mapped[str | None] = mapped_column(String(64))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    parameters: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    test_only: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        # A non-test policy must carry an approver; TEST_ONLY policies may not.
        CheckConstraint("test_only OR (approved_by IS NOT NULL AND approved_at IS NOT NULL)", name="ck_policy_versions_approved"),
    )


class TermsVersion(Base):
    __tablename__ = "terms_versions"
    terms_version_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    approved_by: Mapped[str | None] = mapped_column(String(64))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    parameters: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    test_only: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        CheckConstraint("test_only OR (approved_by IS NOT NULL AND approved_at IS NOT NULL)", name="ck_terms_versions_approved"),
    )


class ControlAgreement(Base):
    __tablename__ = "control_agreements"
    control_agreement_id: Mapped[str] = mapped_column(ULID, primary_key=True)
    borrower_id: Mapped[str] = mapped_column(ULID, ForeignKey("borrowers.borrower_id", ondelete="RESTRICT"), nullable=False)
    provider_account_id: Mapped[str] = mapped_column(String(200), ForeignKey("provider_accounts.provider_account_id", ondelete="RESTRICT"), nullable=False)
    control_grade: Mapped[str] = mapped_column(String(2), nullable=False, server_default="E0")
    subject: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    receiver_chain_id: Mapped[int | None] = mapped_column(BigInteger)
    receiver_address: Mapped[str | None] = mapped_column(ADDR)
    change_authority: Mapped[str] = mapped_column(String(16), nullable=False, server_default="BORROWER_ALONE")
    agreement_hash: Mapped[str | None] = mapped_column(HEX32)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    precedence: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    observation_provenance: Mapped[dict | None] = mapped_column(JSONB)
    poc_ref: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        CheckConstraint(f"control_agreement_id {ULID_CHECK}", name="ck_control_agreements_ulid"),
        CheckConstraint(f"control_grade IN {_in(E.ControlGrade)}", name="ck_control_agreements_grade"),
        CheckConstraint("change_authority IN ('BORROWER_ALONE','PROTOCOL','PARTNER','MULTI')", name="ck_control_agreements_authority"),
        CheckConstraint("receiver_address IS NULL OR receiver_address " + ADDR_CHECK, name="ck_control_agreements_receiver"),
        CheckConstraint("agreement_hash IS NULL OR agreement_hash " + HEX32_CHECK, name="ck_control_agreements_hash"),
        CheckConstraint("version >= 1", name="ck_control_agreements_version"),
        CheckConstraint("effective_to IS NULL OR effective_from IS NULL OR effective_to > effective_from", name="ck_control_agreements_period"),
        # E2/E3 needs partner-recognized change authority, a hash, an effective date and a PoC reference (GPU-009).
        CheckConstraint(
            "control_grade IN ('E0','E1') OR (change_authority <> 'BORROWER_ALONE' AND agreement_hash IS NOT NULL "
            "AND effective_from IS NOT NULL AND poc_ref IS NOT NULL AND receiver_address IS NOT NULL)",
            name="ck_control_agreements_e2_requirements",
        ),
        UniqueConstraint("provider_account_id", "version", name="uq_control_agreements_version"),
    )


class ControlObservation(Base):
    __tablename__ = "control_observations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    control_agreement_id: Mapped[str] = mapped_column(ULID, ForeignKey("control_agreements.control_agreement_id", ondelete="CASCADE"), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    observed_grade: Mapped[str] = mapped_column(String(2), nullable=False)
    receiver_address: Mapped[str | None] = mapped_column(ADDR)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    provenance: Mapped[dict] = mapped_column(JSONB, nullable=False)
    raw_hash: Mapped[str | None] = mapped_column(HEX32)
    __table_args__ = (
        CheckConstraint(f"observed_grade IN {_in(E.ControlGrade)}", name="ck_control_observations_grade"),
        CheckConstraint("source IN ('API','RPC','MANUAL','SIMULATED')", name="ck_control_observations_source"),
        Index("ix_control_observations_agreement_time", "control_agreement_id", "observed_at"),
    )


class Facility(Base):
    __tablename__ = "facilities"
    facility_id: Mapped[str] = mapped_column(ULID, primary_key=True)
    borrower_id: Mapped[str] = mapped_column(ULID, ForeignKey("borrowers.borrower_id", ondelete="RESTRICT"), nullable=False)
    vault_id: Mapped[str] = mapped_column(String(64), nullable=False)
    loan_chain_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    loan_token_address: Mapped[str | None] = mapped_column(ADDR)
    loan_decimals: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False, server_default="DRAFT")
    approved_cap: Mapped[int] = mapped_column(MONEY, nullable=False, server_default="0")
    advance_rate_bps: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    terms_version_id: Mapped[str] = mapped_column(String(64), ForeignKey("terms_versions.terms_version_id", ondelete="RESTRICT"), nullable=False)
    policy_version_id: Mapped[str] = mapped_column(String(64), ForeignKey("policy_versions.policy_version_id", ondelete="RESTRICT"), nullable=False)
    required_verification: Mapped[str] = mapped_column(String(32), nullable=False, server_default="ATTESTCOIN_NATIVE")
    execution_profile: Mapped[str] = mapped_column(String(32), nullable=False)
    principal: Mapped[int] = mapped_column(MONEY, nullable=False, server_default="0")
    unpaid_interest: Mapped[int] = mapped_column(MONEY, nullable=False, server_default="0")
    fees: Mapped[int] = mapped_column(MONEY, nullable=False, server_default="0")
    reserved_draws: Mapped[int] = mapped_column(MONEY, nullable=False, server_default="0")
    rate_bps: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    accrual_basis: Mapped[str] = mapped_column(String(16), nullable=False, server_default="ACT_365")
    maturity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    control_agreement_id: Mapped[str | None] = mapped_column(ULID, ForeignKey("control_agreements.control_agreement_id", ondelete="RESTRICT"))
    funded_agreement_version: Mapped[int | None] = mapped_column(Integer)
    manifest_hash: Mapped[str | None] = mapped_column(String(71))
    test_only_terms: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        CheckConstraint(f"facility_id {ULID_CHECK}", name="ck_facilities_ulid"),
        CheckConstraint(f"state IN {_in(E.FacilityState)}", name="ck_facilities_state"),
        CheckConstraint("loan_token_address IS NULL OR loan_token_address " + ADDR_CHECK, name="ck_facilities_loan_token"),
        CheckConstraint("loan_decimals BETWEEN 0 AND 36", name="ck_facilities_loan_decimals"),
        CheckConstraint("approved_cap >= 0 AND principal >= 0 AND unpaid_interest >= 0 AND fees >= 0 AND reserved_draws >= 0", name="ck_facilities_money_nonneg"),
        CheckConstraint("advance_rate_bps BETWEEN 0 AND 10000", name="ck_facilities_advance_rate"),
        CheckConstraint("rate_bps >= 0", name="ck_facilities_rate"),
        CheckConstraint("required_verification = 'ATTESTCOIN_NATIVE'", name="ck_facilities_required_verification"),
        CheckConstraint(f"execution_profile IN {_in(E.ExecutionProfile)}", name="ck_facilities_profile"),
        CheckConstraint("accrual_basis = 'ACT_365'", name="ck_facilities_accrual_basis"),
        CheckConstraint("manifest_hash IS NULL OR manifest_hash ~ '^sha256:[0-9a-f]{64}$'", name="ck_facilities_manifest_hash"),
        # Funded states need a control agreement and the funded version pinned.
        CheckConstraint(
            "state IN ('DRAFT','UNDER_REVIEW','CONTROL_PENDING') OR (control_agreement_id IS NOT NULL AND funded_agreement_version IS NOT NULL)",
            name="ck_facilities_funded_requires_control",
        ),
        # Nothing is released or repaid with debt outstanding.
        CheckConstraint("state NOT IN ('REPAID','RELEASED') OR (principal = 0 AND unpaid_interest = 0 AND fees = 0)", name="ck_facilities_released_debt_zero"),
        # Production facilities cannot run on TEST_ONLY terms.
        CheckConstraint("execution_profile <> 'PRODUCTION' OR NOT test_only_terms", name="ck_facilities_prod_not_test_terms"),
        Index("ix_facilities_borrower_state", "borrower_id", "state"),
    )


class CreditDecision(Base):
    __tablename__ = "credit_decisions"
    credit_decision_id: Mapped[str] = mapped_column(ULID, primary_key=True)
    facility_id: Mapped[str] = mapped_column(ULID, ForeignKey("facilities.facility_id", ondelete="RESTRICT"), nullable=False)
    decided_by: Mapped[str] = mapped_column(String(16), nullable=False)
    policy_version_id: Mapped[str] = mapped_column(String(64), ForeignKey("policy_versions.policy_version_id", ondelete="RESTRICT"), nullable=False)
    inputs: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    limit_amount: Mapped[int] = mapped_column(MONEY, nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    freshness_checkpoint: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="DRAFT")
    execution_profile: Mapped[str] = mapped_column(String(32), nullable=False)
    __table_args__ = (
        CheckConstraint(f"credit_decision_id {ULID_CHECK}", name="ck_credit_decisions_ulid"),
        CheckConstraint("decided_by IN ('underwriter','system')", name="ck_credit_decisions_decider"),
        CheckConstraint("limit_amount >= 0", name="ck_credit_decisions_limit"),
        CheckConstraint("valid_until > decided_at", name="ck_credit_decisions_validity"),
        CheckConstraint("status IN ('DRAFT','APPROVED','EXPIRED','REVOKED')", name="ck_credit_decisions_status"),
        CheckConstraint(f"execution_profile IN {_in(E.ExecutionProfile)}", name="ck_credit_decisions_profile"),
        Index("ix_credit_decisions_facility", "facility_id", "status"),
    )


class FacilityStateTransition(Base):
    """Append-only audit of facility state changes (authority recorded; oracle never allowed)."""

    __tablename__ = "facility_state_transitions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    facility_id: Mapped[str] = mapped_column(ULID, ForeignKey("facilities.facility_id", ondelete="RESTRICT"), nullable=False)
    from_state: Mapped[str] = mapped_column(String(24), nullable=False)
    to_state: Mapped[str] = mapped_column(String(24), nullable=False)
    trigger: Mapped[str] = mapped_column(String(64), nullable=False)
    authority: Mapped[str] = mapped_column(String(24), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        CheckConstraint(f"from_state IN {_in(E.FacilityState)} AND to_state IN {_in(E.FacilityState)}", name="ck_facility_transitions_states"),
        CheckConstraint("authority <> 'oracle' AND authority <> 'keeper'", name="ck_facility_transitions_no_oracle"),
        Index("ix_facility_transitions_facility", "facility_id", "occurred_at"),
    )


# Cross-row invariants enforced by PostgreSQL triggers (see migration 0001):
#   * credit_decisions.execution_profile must equal facilities.execution_profile
#   * facilities with execution_profile = PRODUCTION cannot reference test_only policy/terms versions
#     nor a control agreement whose provider is not PRODUCTION / is test_only
#   * a PRODUCTION facility cannot be downgraded to a lower profile, and a lower-profile facility
#     cannot be promoted to PRODUCTION (no reuse of testnet data)
TRIGGER_NAMES = (
    "trg_credit_decisions_profile_match",
    "trg_facilities_production_isolation",
)

# GPU-016 ledgers register themselves on the same metadata (import for side effects).
from . import ledgers as _ledgers  # noqa: E402,F401
# GPU-017 account-link history and asset review flags (migration 0003).
from . import assets_models as _assets_models  # noqa: E402,F401
