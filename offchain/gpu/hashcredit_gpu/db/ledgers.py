"""
SQLAlchemy 2.0 models for the GPU-016 ledgers (PostgreSQL): raw observations, the official-proof pipeline
(proof requests → artifacts → native verifications → evidence consumptions), receivables and revisions,
settlements, destination cash receipts and allocations, recovery/write-offs, append-only audit, correction
links, ingest cursors, durable jobs, outbox, EVM tx intents and exceptions.

Mirror of migration `0002_event_cash_job_ledgers`; `hashcredit-gpu-db check` asserts no drift.

Independent states (R2-D02): a proof request being API-ready (`api_ready_at`), an `eth_call` pre-check
succeeding (`precheck_ok_at`), an actual native acceptance (`native_verifications.status = ACCEPTED`) and an
economic consumption (`evidence_consumptions` row) are four separate facts. Triggers in the migration forbid
a status that claims a later fact without the row that proves the earlier one, and forbid PRODUCTION rows
from referencing LOCAL_MOCK verifications.

Cash (R2-D07): only `cash_receipts` (actual destination receipts) feed `allocations`; `excess` is borrower
refundable and never LP cash (`v_cash_ownership`). Write-offs never extinguish legal debt (AC-08).
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
from sqlalchemy.orm import Mapped, mapped_column

from ..domain import enums as E
from .models import ADDR, ADDR_CHECK, HEX32, HEX32_CHECK, MONEY, ULID, ULID_CHECK, Base, _in

SIGNED_MONEY = Numeric(78, 0)
MANIFEST_CHECK = "~ '^sha256:[0-9a-f]{64}$'"
REF_CHECK = "~ '^(secret|vault|doc|blob|s3)://'"

# docs/gpu/attestcoin/evidence-contract.md §4 / GpuTypes.EvidenceMeaning (+ CHECKPOINT for freshness rows)
EVIDENCE_MEANINGS = ["OBLIGATION_RECOGNIZED", "ASSIGNMENT_RECOGNIZED", "CORRECTION", "PAYOUT", "PAYMENT_CANCELLED", "CHECKPOINT"]
OBSERVATION_ORIGINS = ["CHAIN", "API", "WEBHOOK", "MANUAL"]
VERIFICATION_STATUSES = ["SUBMITTED", "ACCEPTED", "REJECTED", "ORPHANED"]
REVISION_KINDS = ["RECOGNIZED", "CORRECTION", "ASSIGNMENT", "PAYOUT", "CANCELLATION", "DISPUTE", "CHECKPOINT"]
CASH_SOURCE_KINDS = ["SETTLEMENT", "DIRECT_REPAYMENT", "RECOVERY", "UNKNOWN"]
RECOVERY_KINDS = ["COLLECTION", "COLLATERAL_SALE", "INSURANCE", "LEGAL", "OTHER"]
CORRECTION_LINK_KINDS = ["CORRECTION", "CANCELLATION", "REVERSAL", "RECONCILED_DUPLICATE"]
JOB_STATES = ["PENDING", "LEASED", "SUCCEEDED", "FAILED", "DEAD"]
TX_STATES = ["PREPARED", "SENT", "MINED", "FINAL", "REPLACED", "FAILED", "ORPHANED"]
EXCEPTION_SEVERITIES = ["INFO", "WARNING", "BLOCKING"]
CURSOR_KINDS = ["BLOCK", "TIMESTAMP", "OPAQUE"]


# ---------------------------------------------------------------- raw observations


class RawSourceObservation(Base):
    """Immutable raw capture (hash + reference, never the secret payload). UPDATE/DELETE are rejected by trigger."""

    __tablename__ = "raw_source_observations"
    observation_id: Mapped[str] = mapped_column(ULID, primary_key=True)
    provider_id: Mapped[str] = mapped_column(String(64), ForeignKey("providers.provider_id", ondelete="RESTRICT"), nullable=False)
    origin: Mapped[str] = mapped_column(String(16), nullable=False)
    schema_id: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_revision: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    payload_hash: Mapped[str] = mapped_column(HEX32, nullable=False)
    payload_ref: Mapped[str | None] = mapped_column(Text)
    source_cursor: Mapped[str | None] = mapped_column(Text)
    trust: Mapped[str] = mapped_column(String(16), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        CheckConstraint(f"observation_id {ULID_CHECK}", name="ck_raw_obs_ulid"),
        CheckConstraint(f"origin IN {_in(OBSERVATION_ORIGINS)}", name="ck_raw_obs_origin"),
        CheckConstraint(f"payload_hash {HEX32_CHECK}", name="ck_raw_obs_payload_hash"),
        CheckConstraint(f"payload_ref IS NULL OR payload_ref {REF_CHECK}", name="ck_raw_obs_payload_ref"),
        CheckConstraint(f"trust IN {_in(E.Trust)}", name="ck_raw_obs_trust"),
        CheckConstraint("schema_revision >= 1", name="ck_raw_obs_schema_revision"),
        UniqueConstraint("provider_id", "origin", "payload_hash", name="uq_raw_obs_payload"),
        Index("ix_raw_obs_provider_observed", "provider_id", "observed_at"),
    )


# ---------------------------------------------------------------- official proof pipeline


class ProofRequest(Base):
    """One official proof query per (env, chainKey, txHash) — the cache key, never a consumption key."""

    __tablename__ = "proof_requests"
    proof_request_id: Mapped[str] = mapped_column(ULID, primary_key=True)
    env_id: Mapped[str] = mapped_column(String(64), nullable=False)
    chain_key: Mapped[int] = mapped_column(Integer, nullable=False)
    tx_hash: Mapped[str] = mapped_column(HEX32, nullable=False)
    provider_id: Mapped[str] = mapped_column(String(64), ForeignKey("providers.provider_id", ondelete="RESTRICT"), nullable=False)
    execution_profile: Mapped[str] = mapped_column(String(32), nullable=False)
    manifest_hash: Mapped[str] = mapped_column(String(71), nullable=False)
    sdk_version: Mapped[str] = mapped_column(String(32), nullable=False)
    encoding_version: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="1")
    abi_sha256s: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    decoder_ref: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), nullable=False, server_default="OBSERVED")
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    api_ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # proof service HTTP 200 (untrusted)
    precheck_ok_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # eth_call verify() == true (not acceptance)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        CheckConstraint(f"proof_request_id {ULID_CHECK}", name="ck_proof_requests_ulid"),
        CheckConstraint(f"tx_hash {HEX32_CHECK}", name="ck_proof_requests_tx_hash"),
        CheckConstraint("chain_key > 0", name="ck_proof_requests_chain_key"),
        CheckConstraint(f"execution_profile IN {_in(E.ExecutionProfile)}", name="ck_proof_requests_profile"),
        CheckConstraint(f"manifest_hash {MANIFEST_CHECK}", name="ck_proof_requests_manifest"),
        CheckConstraint("encoding_version = 1", name="ck_proof_requests_encoding"),
        CheckConstraint(f"status IN {_in(E.NativeStatus)} AND status NOT IN ('NOT_REQUIRED')", name="ck_proof_requests_status"),
        CheckConstraint("attempt >= 0", name="ck_proof_requests_attempt"),
        UniqueConstraint("env_id", "chain_key", "tx_hash", name="uq_proof_requests_query_key"),
        Index("ix_proof_requests_status_next", "status", "next_attempt_at"),
    )


class ProofArtifact(Base):
    """A proof blob obtained from the official service: hash + storage reference; claims are untrusted."""

    __tablename__ = "proof_artifacts"
    proof_artifact_id: Mapped[str] = mapped_column(ULID, primary_key=True)
    proof_request_id: Mapped[str] = mapped_column(ULID, ForeignKey("proof_requests.proof_request_id", ondelete="RESTRICT"), nullable=False)
    artifact_hash: Mapped[str] = mapped_column(HEX32, nullable=False)
    storage_ref: Mapped[str] = mapped_column(Text, nullable=False)
    byte_length: Mapped[int] = mapped_column(Integer, nullable=False)
    sdk_version: Mapped[str] = mapped_column(String(32), nullable=False)
    encoding_version: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="1")
    claimed_height: Mapped[int | None] = mapped_column(BigInteger)
    claimed_tx_index: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        CheckConstraint(f"proof_artifact_id {ULID_CHECK}", name="ck_proof_artifacts_ulid"),
        CheckConstraint(f"artifact_hash {HEX32_CHECK}", name="ck_proof_artifacts_hash"),
        CheckConstraint(f"storage_ref {REF_CHECK}", name="ck_proof_artifacts_storage_ref"),
        CheckConstraint("byte_length > 0", name="ck_proof_artifacts_length"),
        CheckConstraint("encoding_version = 1", name="ck_proof_artifacts_encoding"),
        CheckConstraint("claimed_height IS NULL OR claimed_height >= 0", name="ck_proof_artifacts_height"),
        CheckConstraint("claimed_tx_index IS NULL OR claimed_tx_index >= 0", name="ck_proof_artifacts_tx_index"),
        UniqueConstraint("proof_request_id", "artifact_hash", name="uq_proof_artifacts_request_hash"),
    )


class NativeVerification(Base):
    """A destination-chain submission of an artifact to the app verifier; ACCEPTED only with a receipt."""

    __tablename__ = "native_verifications"
    native_verification_id: Mapped[str] = mapped_column(ULID, primary_key=True)
    proof_request_id: Mapped[str] = mapped_column(ULID, ForeignKey("proof_requests.proof_request_id", ondelete="RESTRICT"), nullable=False)
    proof_artifact_id: Mapped[str] = mapped_column(ULID, ForeignKey("proof_artifacts.proof_artifact_id", ondelete="RESTRICT"), nullable=False)
    execution_profile: Mapped[str] = mapped_column(String(32), nullable=False)
    verification_method: Mapped[str] = mapped_column(String(32), nullable=False)
    destination_chain_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    verifier_address: Mapped[str] = mapped_column(ADDR, nullable=False)
    submission_tx_hash: Mapped[str] = mapped_column(HEX32, nullable=False)
    verification_block: Mapped[int | None] = mapped_column(BigInteger)
    receipt_status: Mapped[int | None] = mapped_column(SmallInteger)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="SUBMITTED")
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    proven_height: Mapped[int | None] = mapped_column(BigInteger)
    proven_tx_index: Mapped[int | None] = mapped_column(Integer)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        CheckConstraint(f"native_verification_id {ULID_CHECK}", name="ck_native_verifications_ulid"),
        CheckConstraint(f"execution_profile IN {_in(E.ExecutionProfile)}", name="ck_native_verifications_profile"),
        CheckConstraint(f"verification_method IN ('ATTESTCOIN_NATIVE','LOCAL_MOCK')", name="ck_native_verifications_method"),
        # a mock verification only exists under the LOCAL_MOCK profile; a production one must be native
        CheckConstraint("(verification_method = 'LOCAL_MOCK') = (execution_profile = 'LOCAL_MOCK')", name="ck_native_verifications_mock_profile"),
        CheckConstraint("destination_chain_id > 0", name="ck_native_verifications_chain"),
        CheckConstraint(f"verifier_address {ADDR_CHECK}", name="ck_native_verifications_verifier"),
        CheckConstraint(f"submission_tx_hash {HEX32_CHECK}", name="ck_native_verifications_tx"),
        CheckConstraint("receipt_status IS NULL OR receipt_status IN (0, 1)", name="ck_native_verifications_receipt"),
        CheckConstraint(f"status IN {_in(VERIFICATION_STATUSES)}", name="ck_native_verifications_status"),
        # acceptance needs a mined block, a successful receipt, a time and the proven position
        CheckConstraint(
            "status <> 'ACCEPTED' OR (accepted_at IS NOT NULL AND receipt_status = 1 AND verification_block IS NOT NULL "
            "AND proven_height IS NOT NULL AND proven_tx_index IS NOT NULL)",
            name="ck_native_verifications_accepted_evidence",
        ),
        CheckConstraint("status = 'ACCEPTED' OR accepted_at IS NULL", name="ck_native_verifications_accepted_only"),
        UniqueConstraint("proof_request_id", "submission_tx_hash", name="uq_native_verifications_request_tx"),
        Index("ix_native_verifications_status", "status"),
    )


class EvidenceConsumption(Base):
    """On-chain EvidenceBook consumption mirror: one per (env, sourceEventId); economic id unique across observers."""

    __tablename__ = "evidence_consumptions"
    consumption_id: Mapped[str] = mapped_column(ULID, primary_key=True)
    env_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source_event_id: Mapped[str] = mapped_column(HEX32, nullable=False)
    economic_event_id: Mapped[str] = mapped_column(String(300), nullable=False)
    native_verification_id: Mapped[str] = mapped_column(ULID, ForeignKey("native_verifications.native_verification_id", ondelete="RESTRICT"), nullable=False)
    provider_id: Mapped[str] = mapped_column(String(64), ForeignKey("providers.provider_id", ondelete="RESTRICT"), nullable=False)
    provider_account_id: Mapped[str] = mapped_column(String(200), ForeignKey("provider_accounts.provider_account_id", ondelete="RESTRICT"), nullable=False)
    meaning: Mapped[str] = mapped_column(String(32), nullable=False)
    verification_method: Mapped[str] = mapped_column(String(32), nullable=False)
    trust: Mapped[str] = mapped_column(String(16), nullable=False)
    execution_profile: Mapped[str] = mapped_column(String(32), nullable=False)
    consumer_address: Mapped[str] = mapped_column(ADDR, nullable=False)
    consumption_tx_hash: Mapped[str] = mapped_column(HEX32, nullable=False)
    manifest_hash: Mapped[str] = mapped_column(String(71), nullable=False)
    proven_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    chain_key: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tx_index: Mapped[int] = mapped_column(Integer, nullable=False)
    log_ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    emitter_address: Mapped[str] = mapped_column(ADDR, nullable=False)
    topic0: Mapped[str] = mapped_column(HEX32, nullable=False)
    data_hash: Mapped[str] = mapped_column(HEX32, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        CheckConstraint(f"consumption_id {ULID_CHECK}", name="ck_evidence_consumptions_ulid"),
        CheckConstraint(f"source_event_id {HEX32_CHECK}", name="ck_evidence_consumptions_source_event"),
        CheckConstraint("economic_event_id ~ '^[a-z0-9-]+/[^/]+/[A-Z_]+/.+$'", name="ck_evidence_consumptions_economic_id"),
        CheckConstraint(f"meaning IN {_in(EVIDENCE_MEANINGS)}", name="ck_evidence_consumptions_meaning"),
        CheckConstraint(f"verification_method IN {_in(E.VerificationMethod)}", name="ck_evidence_consumptions_method"),
        CheckConstraint(f"trust IN {_in(E.Trust)}", name="ck_evidence_consumptions_trust"),
        CheckConstraint(f"execution_profile IN {_in(E.ExecutionProfile)}", name="ck_evidence_consumptions_profile"),
        # production evidence is native or an explicitly labeled assertion; never a mock
        CheckConstraint("execution_profile <> 'PRODUCTION' OR verification_method <> 'LOCAL_MOCK'", name="ck_evidence_consumptions_prod_no_mock"),
        # an assertion (our own anchor) is never PROVEN business evidence
        CheckConstraint("(verification_method = 'OFFCHAIN_ASSERTION') = (trust = 'ASSERTED')", name="ck_evidence_consumptions_assertion_trust"),
        CheckConstraint(f"consumer_address {ADDR_CHECK} AND emitter_address {ADDR_CHECK}", name="ck_evidence_consumptions_addrs"),
        CheckConstraint(f"consumption_tx_hash {HEX32_CHECK} AND topic0 {HEX32_CHECK} AND data_hash {HEX32_CHECK}", name="ck_evidence_consumptions_hashes"),
        CheckConstraint(f"manifest_hash {MANIFEST_CHECK}", name="ck_evidence_consumptions_manifest"),
        CheckConstraint("valid_until > proven_at", name="ck_evidence_consumptions_validity"),
        CheckConstraint("chain_key > 0 AND height >= 0 AND tx_index >= 0 AND log_ordinal >= 0", name="ck_evidence_consumptions_locator"),
        UniqueConstraint("env_id", "source_event_id", name="uq_evidence_consumptions_source_event"),
        UniqueConstraint("economic_event_id", name="uq_evidence_consumptions_economic_event"),
        UniqueConstraint("env_id", "chain_key", "height", "tx_index", "log_ordinal", name="uq_evidence_consumptions_locator"),
        Index("ix_evidence_consumptions_account", "provider_account_id", "meaning"),
    )


# ---------------------------------------------------------------- receivables / settlements


class Receivable(Base):
    __tablename__ = "receivables"
    receivable_id: Mapped[str] = mapped_column(ULID, primary_key=True)
    economic_event_id: Mapped[str] = mapped_column(String(300), nullable=False)
    provider_account_id: Mapped[str] = mapped_column(String(200), ForeignKey("provider_accounts.provider_account_id", ondelete="RESTRICT"), nullable=False)
    obligation_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    debtor: Mapped[str | None] = mapped_column(Text)
    contract_ref: Mapped[str | None] = mapped_column(Text)
    asset_chain_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    asset_token_address: Mapped[str | None] = mapped_column(ADDR)
    asset_decimals: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    gross: Mapped[int] = mapped_column(MONEY, nullable=False)
    net: Mapped[int] = mapped_column(MONEY, nullable=False)
    paid_amount: Mapped[int] = mapped_column(MONEY, nullable=False, server_default="0")
    unpaid_amount: Mapped[int] = mapped_column(MONEY, nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False, server_default="RECOGNIZED")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    facility_id: Mapped[str | None] = mapped_column(ULID, ForeignKey("facilities.facility_id", ondelete="RESTRICT"))
    checkpoint_seq: Mapped[int | None] = mapped_column(BigInteger)
    checkpoint_consumption_id: Mapped[str | None] = mapped_column(ULID, ForeignKey("evidence_consumptions.consumption_id", ondelete="RESTRICT"))
    period_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    period_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disputed_reason: Mapped[str | None] = mapped_column(Text)
    execution_profile: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        CheckConstraint(f"receivable_id {ULID_CHECK}", name="ck_receivables_ulid"),
        CheckConstraint("asset_chain_id > 0 AND asset_decimals BETWEEN 0 AND 36", name="ck_receivables_asset"),
        CheckConstraint(f"asset_token_address IS NULL OR asset_token_address {ADDR_CHECK}", name="ck_receivables_token"),
        CheckConstraint("gross >= 0 AND net >= 0 AND paid_amount >= 0 AND unpaid_amount >= 0", name="ck_receivables_money_nonneg"),
        CheckConstraint("net <= gross AND paid_amount <= net AND unpaid_amount = net - paid_amount", name="ck_receivables_balance"),
        CheckConstraint(f"state IN {_in(E.ReceivableState)}", name="ck_receivables_state"),
        CheckConstraint("revision >= 1", name="ck_receivables_revision"),
        CheckConstraint("state <> 'ASSIGNED' OR facility_id IS NOT NULL", name="ck_receivables_assigned_has_facility"),
        CheckConstraint("state <> 'PAID' OR unpaid_amount = 0", name="ck_receivables_paid_is_zero"),
        CheckConstraint("state <> 'DISPUTED' OR disputed_reason IS NOT NULL", name="ck_receivables_disputed_reason"),
        CheckConstraint(f"execution_profile IN {_in(E.ExecutionProfile)}", name="ck_receivables_profile"),
        UniqueConstraint("economic_event_id", name="uq_receivables_economic_event"),
        UniqueConstraint("provider_account_id", "obligation_ref", name="uq_receivables_account_ref"),
        Index("ix_receivables_facility_state", "facility_id", "state"),
    )


class ReceivableRevision(Base):
    """History per receivable; revision numbers are monotonic unless the row is explicitly `out_of_order`."""

    __tablename__ = "receivable_revisions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    receivable_id: Mapped[str] = mapped_column(ULID, ForeignKey("receivables.receivable_id", ondelete="RESTRICT"), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    consumption_id: Mapped[str | None] = mapped_column(ULID, ForeignKey("evidence_consumptions.consumption_id", ondelete="RESTRICT"))
    observation_id: Mapped[str | None] = mapped_column(ULID, ForeignKey("raw_source_observations.observation_id", ondelete="RESTRICT"))
    delta: Mapped[int] = mapped_column(SIGNED_MONEY, nullable=False, server_default="0")
    net_after: Mapped[int] = mapped_column(MONEY, nullable=False)
    unpaid_after: Mapped[int] = mapped_column(MONEY, nullable=False)
    out_of_order: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        CheckConstraint(f"kind IN {_in(REVISION_KINDS)}", name="ck_receivable_revisions_kind"),
        CheckConstraint("revision >= 1 AND net_after >= 0 AND unpaid_after >= 0", name="ck_receivable_revisions_values"),
        # a proven revision cites its consumption; an observed one cites its raw observation
        CheckConstraint("consumption_id IS NOT NULL OR observation_id IS NOT NULL", name="ck_receivable_revisions_provenance"),
        UniqueConstraint("receivable_id", "revision", "kind", name="uq_receivable_revisions_rev"),
        Index("ix_receivable_revisions_receivable", "receivable_id", "revision"),
    )


class Settlement(Base):
    __tablename__ = "settlements"
    settlement_id: Mapped[str] = mapped_column(ULID, primary_key=True)
    provider_account_id: Mapped[str] = mapped_column(String(200), ForeignKey("provider_accounts.provider_account_id", ondelete="RESTRICT"), nullable=False)
    settlement_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    settlement_seq: Mapped[int | None] = mapped_column(BigInteger)
    state: Mapped[str] = mapped_column(String(32), nullable=False, server_default="ANNOUNCED")
    asset_chain_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    asset_token_address: Mapped[str | None] = mapped_column(ADDR)
    asset_decimals: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    source_amount: Mapped[int] = mapped_column(MONEY, nullable=False)
    payout_consumption_id: Mapped[str | None] = mapped_column(ULID, ForeignKey("evidence_consumptions.consumption_id", ondelete="RESTRICT"))
    execution_profile: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        CheckConstraint(f"settlement_id {ULID_CHECK}", name="ck_settlements_ulid"),
        CheckConstraint(f"state IN {_in(E.SettlementState)}", name="ck_settlements_state"),
        CheckConstraint("asset_chain_id > 0 AND asset_decimals BETWEEN 0 AND 36 AND source_amount >= 0", name="ck_settlements_asset"),
        CheckConstraint(f"asset_token_address IS NULL OR asset_token_address {ADDR_CHECK}", name="ck_settlements_token"),
        CheckConstraint("settlement_seq IS NULL OR settlement_seq >= 0", name="ck_settlements_seq"),
        # a settlement is PAID_AT_SOURCE (or later) only with a natively proven payout
        CheckConstraint("state IN ('ANNOUNCED','REVERSED') OR payout_consumption_id IS NOT NULL", name="ck_settlements_paid_requires_proof"),
        CheckConstraint(f"execution_profile IN {_in(E.ExecutionProfile)}", name="ck_settlements_profile"),
        UniqueConstraint("provider_account_id", "settlement_ref", name="uq_settlements_account_ref"),
        Index("ix_settlements_state", "state"),
    )


class SettlementReceivable(Base):
    """N:M split — one settlement can pay several receivables and one receivable can be paid by several."""

    __tablename__ = "settlement_receivables"
    settlement_id: Mapped[str] = mapped_column(ULID, ForeignKey("settlements.settlement_id", ondelete="RESTRICT"), primary_key=True)
    receivable_id: Mapped[str] = mapped_column(ULID, ForeignKey("receivables.receivable_id", ondelete="RESTRICT"), primary_key=True)
    amount: Mapped[int] = mapped_column(MONEY, nullable=False)
    __table_args__ = (CheckConstraint("amount > 0", name="ck_settlement_receivables_amount"),)


# ---------------------------------------------------------------- destination cash


class CashReceipt(Base):
    """Actual loan-currency receipt at the destination vault/repayment address. The only input to allocations."""

    __tablename__ = "cash_receipts"
    cash_receipt_id: Mapped[str] = mapped_column(ULID, primary_key=True)
    vault_id: Mapped[str] = mapped_column(String(64), nullable=False)
    chain_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    token_address: Mapped[str | None] = mapped_column(ADDR)
    decimals: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    amount: Mapped[int] = mapped_column(MONEY, nullable=False)
    tx_hash: Mapped[str] = mapped_column(HEX32, nullable=False)
    log_index: Mapped[int] = mapped_column(Integer, nullable=False)
    payer_address: Mapped[str | None] = mapped_column(ADDR)
    source_kind: Mapped[str] = mapped_column(String(24), nullable=False, server_default="UNKNOWN")
    settlement_id: Mapped[str | None] = mapped_column(ULID, ForeignKey("settlements.settlement_id", ondelete="RESTRICT"))
    cash_state: Mapped[str] = mapped_column(String(24), nullable=False, server_default="DESTINATION_RECEIVED")
    execution_profile: Mapped[str] = mapped_column(String(32), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        CheckConstraint(f"cash_receipt_id {ULID_CHECK}", name="ck_cash_receipts_ulid"),
        CheckConstraint("chain_id > 0 AND decimals BETWEEN 0 AND 36 AND amount > 0 AND log_index >= 0", name="ck_cash_receipts_values"),
        CheckConstraint(f"token_address IS NULL OR token_address {ADDR_CHECK}", name="ck_cash_receipts_token"),
        CheckConstraint(f"tx_hash {HEX32_CHECK}", name="ck_cash_receipts_tx"),
        CheckConstraint(f"payer_address IS NULL OR payer_address {ADDR_CHECK}", name="ck_cash_receipts_payer"),
        CheckConstraint(f"source_kind IN {_in(CASH_SOURCE_KINDS)}", name="ck_cash_receipts_source_kind"),
        CheckConstraint("cash_state IN ('DESTINATION_RECEIVED','ALLOCATED','RETURNED')", name="ck_cash_receipts_state"),
        CheckConstraint("source_kind <> 'SETTLEMENT' OR settlement_id IS NOT NULL", name="ck_cash_receipts_settlement_link"),
        CheckConstraint(f"execution_profile IN {_in(E.ExecutionProfile)}", name="ck_cash_receipts_profile"),
        UniqueConstraint("chain_id", "tx_hash", "log_index", name="uq_cash_receipts_semantic_key"),
        Index("ix_cash_receipts_vault_state", "vault_id", "cash_state"),
    )


class Allocation(Base):
    """Facility allocation of one receipt: fee → interest → principal → excess; `excess` is borrower refundable."""

    __tablename__ = "allocations"
    allocation_id: Mapped[str] = mapped_column(ULID, primary_key=True)
    cash_receipt_id: Mapped[str] = mapped_column(ULID, ForeignKey("cash_receipts.cash_receipt_id", ondelete="RESTRICT"), nullable=False)
    facility_id: Mapped[str] = mapped_column(ULID, ForeignKey("facilities.facility_id", ondelete="RESTRICT"), nullable=False)
    received: Mapped[int] = mapped_column(MONEY, nullable=False)
    fee_paid: Mapped[int] = mapped_column(MONEY, nullable=False, server_default="0")
    interest_paid: Mapped[int] = mapped_column(MONEY, nullable=False, server_default="0")
    principal_paid: Mapped[int] = mapped_column(MONEY, nullable=False, server_default="0")
    excess: Mapped[int] = mapped_column(MONEY, nullable=False, server_default="0")
    excess_refunded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    new_debt: Mapped[int] = mapped_column(MONEY, nullable=False)
    onchain_tx_hash: Mapped[str | None] = mapped_column(HEX32)
    allocated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        CheckConstraint(f"allocation_id {ULID_CHECK}", name="ck_allocations_ulid"),
        CheckConstraint("received > 0 AND fee_paid >= 0 AND interest_paid >= 0 AND principal_paid >= 0 AND excess >= 0 AND new_debt >= 0", name="ck_allocations_nonneg"),
        CheckConstraint("fee_paid + interest_paid + principal_paid + excess = received", name="ck_allocations_split_sum"),
        CheckConstraint(f"onchain_tx_hash IS NULL OR onchain_tx_hash {HEX32_CHECK}", name="ck_allocations_tx"),
        UniqueConstraint("cash_receipt_id", "facility_id", name="uq_allocations_receipt_facility"),
        Index("ix_allocations_facility", "facility_id", "allocated_at"),
    )


class RecoveryEvent(Base):
    __tablename__ = "recovery_events"
    recovery_event_id: Mapped[str] = mapped_column(ULID, primary_key=True)
    facility_id: Mapped[str] = mapped_column(ULID, ForeignKey("facilities.facility_id", ondelete="RESTRICT"), nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    amount: Mapped[int] = mapped_column(MONEY, nullable=False)
    cash_receipt_id: Mapped[str | None] = mapped_column(ULID, ForeignKey("cash_receipts.cash_receipt_id", ondelete="RESTRICT"))
    evidence_ref: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_by: Mapped[str] = mapped_column(String(24), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        CheckConstraint(f"recovery_event_id {ULID_CHECK}", name="ck_recovery_events_ulid"),
        CheckConstraint(f"kind IN {_in(RECOVERY_KINDS)}", name="ck_recovery_events_kind"),
        CheckConstraint("amount >= 0", name="ck_recovery_events_amount"),
        CheckConstraint(f"evidence_ref IS NULL OR evidence_ref {REF_CHECK}", name="ck_recovery_events_ref"),
        # recoveries are recorded by operations/credit/guardian/treasury/system — never by a keeper or a counterparty
        CheckConstraint("recorded_by IN ('operator','underwriter','guardian','treasury','system')", name="ck_recovery_events_role"),
        Index("ix_recovery_events_facility", "facility_id", "occurred_at"),
    )


class WriteOff(Base):
    """Accounting write-off (impairment). It never extinguishes legal debt: `extinguishes_debt` is always false."""

    __tablename__ = "writeoffs"
    writeoff_id: Mapped[str] = mapped_column(ULID, primary_key=True)
    facility_id: Mapped[str] = mapped_column(ULID, ForeignKey("facilities.facility_id", ondelete="RESTRICT"), nullable=False)
    amount: Mapped[int] = mapped_column(MONEY, nullable=False)
    legal_debt_remaining: Mapped[int] = mapped_column(MONEY, nullable=False)
    extinguishes_debt: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    approved_by: Mapped[str] = mapped_column(String(24), nullable=False)
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        CheckConstraint(f"writeoff_id {ULID_CHECK}", name="ck_writeoffs_ulid"),
        CheckConstraint("amount > 0 AND legal_debt_remaining >= 0", name="ck_writeoffs_amounts"),
        CheckConstraint("extinguishes_debt = false", name="ck_writeoffs_never_forgive"),
        CheckConstraint("approved_by IN ('underwriter','guardian','treasury')", name="ck_writeoffs_approver"),
        Index("ix_writeoffs_facility", "facility_id"),
    )


# ---------------------------------------------------------------- audit / corrections / cursors


class AuditLog(Base):
    """Append-only. Trigger `trg_audit_log_immutable` rejects UPDATE and DELETE."""

    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    actor: Mapped[str] = mapped_column(String(128), nullable=False)
    actor_role: Mapped[str] = mapped_column(String(24), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_table: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(300), nullable=False)
    before: Mapped[dict | None] = mapped_column(JSONB)
    after: Mapped[dict | None] = mapped_column(JSONB)
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    prev_hash: Mapped[str | None] = mapped_column(HEX32)
    entry_hash: Mapped[str] = mapped_column(HEX32, nullable=False)
    __table_args__ = (
        CheckConstraint(f"actor_role IN {_in(E.Role)}", name="ck_audit_log_role"),
        CheckConstraint(f"entry_hash {HEX32_CHECK}", name="ck_audit_log_entry_hash"),
        CheckConstraint(f"prev_hash IS NULL OR prev_hash {HEX32_CHECK}", name="ck_audit_log_prev_hash"),
        Index("ix_audit_log_entity", "entity_table", "entity_id"),
    )


class CorrectionLink(Base):
    __tablename__ = "correction_links"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_economic_event_id: Mapped[str] = mapped_column(String(300), nullable=False)
    target_economic_event_id: Mapped[str] = mapped_column(String(300), nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    consumption_id: Mapped[str | None] = mapped_column(ULID, ForeignKey("evidence_consumptions.consumption_id", ondelete="RESTRICT"))
    observation_id: Mapped[str | None] = mapped_column(ULID, ForeignKey("raw_source_observations.observation_id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        CheckConstraint(f"kind IN {_in(CORRECTION_LINK_KINDS)}", name="ck_correction_links_kind"),
        CheckConstraint("source_economic_event_id <> target_economic_event_id", name="ck_correction_links_distinct"),
        UniqueConstraint("source_economic_event_id", "target_economic_event_id", "kind", name="uq_correction_links"),
    )


class IngestCursor(Base):
    __tablename__ = "ingest_cursors"
    provider_id: Mapped[str] = mapped_column(String(64), ForeignKey("providers.provider_id", ondelete="RESTRICT"), primary_key=True)
    stream: Mapped[str] = mapped_column(String(64), primary_key=True)
    position_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    position: Mapped[str] = mapped_column(Text, nullable=False)
    backfill_from: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (CheckConstraint(f"position_kind IN {_in(CURSOR_KINDS)}", name="ck_ingest_cursors_kind"),)


# ---------------------------------------------------------------- jobs / outbox / tx intents / exceptions


class Job(Base):
    """Durable job with lease; `hcg_lease_job(job_id, worker, seconds)` grants an exclusive lease atomically."""

    __tablename__ = "jobs"
    job_id: Mapped[str] = mapped_column(ULID, primary_key=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    semantic_idempotency_key: Mapped[str] = mapped_column(String(300), nullable=False)
    payload_hash: Mapped[str] = mapped_column(HEX32, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    state: Mapped[str] = mapped_column(String(16), nullable=False, server_default="PENDING")
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="10")
    leased_by: Mapped[str | None] = mapped_column(String(128))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        CheckConstraint(f"job_id {ULID_CHECK}", name="ck_jobs_ulid"),
        CheckConstraint(f"payload_hash {HEX32_CHECK}", name="ck_jobs_payload_hash"),
        CheckConstraint(f"state IN {_in(JOB_STATES)}", name="ck_jobs_state"),
        CheckConstraint("attempt >= 0 AND max_attempts >= 1", name="ck_jobs_attempts"),
        CheckConstraint("state <> 'LEASED' OR (leased_by IS NOT NULL AND lease_until IS NOT NULL)", name="ck_jobs_lease_fields"),
        UniqueConstraint("semantic_idempotency_key", name="uq_jobs_idempotency"),
        Index("ix_jobs_state_next", "state", "next_run_at"),
    )


class Outbox(Base):
    __tablename__ = "outbox"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    aggregate_type: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(300), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(300), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_outbox_idempotency"),
        Index("ix_outbox_unpublished", "created_at", postgresql_where="published_at IS NULL"),
    )


class TxIntent(Base):
    """EVM dispatch intent; (chain, signer, nonce) is unique — the EVM nonce is not a loan/approval nonce."""

    __tablename__ = "tx_intents"
    tx_intent_id: Mapped[str] = mapped_column(ULID, primary_key=True)
    job_id: Mapped[str | None] = mapped_column(ULID, ForeignKey("jobs.job_id", ondelete="RESTRICT"))
    chain_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    signer_address: Mapped[str] = mapped_column(ADDR, nullable=False)
    nonce: Mapped[int] = mapped_column(BigInteger, nullable=False)
    purpose: Mapped[str] = mapped_column(String(64), nullable=False)
    to_address: Mapped[str] = mapped_column(ADDR, nullable=False)
    calldata_hash: Mapped[str] = mapped_column(HEX32, nullable=False)
    tx_hash: Mapped[str | None] = mapped_column(HEX32)
    state: Mapped[str] = mapped_column(String(16), nullable=False, server_default="PREPARED")
    replaces_tx_intent_id: Mapped[str | None] = mapped_column(ULID, ForeignKey("tx_intents.tx_intent_id", ondelete="RESTRICT"))
    mined_block: Mapped[int | None] = mapped_column(BigInteger)
    finality_block: Mapped[int | None] = mapped_column(BigInteger)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        CheckConstraint(f"tx_intent_id {ULID_CHECK}", name="ck_tx_intents_ulid"),
        CheckConstraint("chain_id > 0 AND nonce >= 0", name="ck_tx_intents_values"),
        CheckConstraint(f"signer_address {ADDR_CHECK} AND to_address {ADDR_CHECK}", name="ck_tx_intents_addrs"),
        CheckConstraint(f"calldata_hash {HEX32_CHECK}", name="ck_tx_intents_calldata"),
        CheckConstraint(f"tx_hash IS NULL OR tx_hash {HEX32_CHECK}", name="ck_tx_intents_tx"),
        CheckConstraint(f"state IN {_in(TX_STATES)}", name="ck_tx_intents_state"),
        CheckConstraint("state NOT IN ('SENT','MINED','FINAL') OR tx_hash IS NOT NULL", name="ck_tx_intents_sent_has_hash"),
        CheckConstraint("state <> 'FINAL' OR (mined_block IS NOT NULL AND finality_block IS NOT NULL AND finality_block >= mined_block)", name="ck_tx_intents_final_blocks"),
        CheckConstraint("replaces_tx_intent_id IS NULL OR replaces_tx_intent_id <> tx_intent_id", name="ck_tx_intents_no_self_replace"),
        UniqueConstraint("chain_id", "signer_address", "nonce", name="uq_tx_intents_nonce"),
        UniqueConstraint("tx_hash", name="uq_tx_intents_tx_hash"),
        Index("ix_tx_intents_state", "state"),
    )


class ExceptionCase(Base):
    __tablename__ = "exceptions"
    exception_id: Mapped[str] = mapped_column(ULID, primary_key=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    entity_table: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(300), nullable=False)
    detail: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[str | None] = mapped_column(String(24))
    resolution: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        CheckConstraint(f"exception_id {ULID_CHECK}", name="ck_exceptions_ulid"),
        CheckConstraint(f"severity IN {_in(EXCEPTION_SEVERITIES)}", name="ck_exceptions_severity"),
        CheckConstraint(f"resolved_by IS NULL OR resolved_by IN {_in(E.Role)}", name="ck_exceptions_resolver"),
        CheckConstraint("(resolved_at IS NULL) = (resolved_by IS NULL)", name="ck_exceptions_resolution_pair"),
        Index("ix_exceptions_open", "kind", "opened_at", postgresql_where="resolved_at IS NULL"),
    )


# Cross-row invariants enforced by PostgreSQL triggers/functions (migration 0002):
#   * audit_log and raw_source_observations are append-only (UPDATE/DELETE rejected)
#   * proof_requests.status may only claim PROOF_READY+ with an artifact, NATIVE_ACCEPTED+ with an ACCEPTED
#     verification, CONSUMED with an evidence_consumptions row (states stay independent facts)
#   * evidence_consumptions must reference an ACCEPTED verification of the same method/profile; PRODUCTION
#     consumptions can never reference LOCAL_MOCK verifications
#   * receivable_revisions.revision must exceed the receivable's latest unless out_of_order = true
#   * sum(allocations.received) per cash receipt <= cash_receipts.amount
#   * hcg_lease_job(job_id, worker, seconds) grants an exclusive lease
#   * view v_cash_ownership separates LP-applied cash from borrower-refundable excess
LEDGER_TRIGGER_NAMES = (
    "trg_audit_log_immutable",
    "trg_raw_source_observations_immutable",
    "trg_proof_requests_status_evidence",
    "trg_evidence_consumptions_verified",
    "trg_receivable_revisions_monotonic",
    "trg_allocations_within_receipt",
)
