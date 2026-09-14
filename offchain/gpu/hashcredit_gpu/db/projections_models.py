"""
SQLAlchemy 2.0 models for the GPU-073 on-chain projector (PostgreSQL): per-deployment cursors, the canonical
block journal, a reorg journal, the deduplicated raw log store and the projected read models.

Mirror of migration `0004_projections`; `hashcredit-gpu-db check` asserts no drift.

Tiers: `PENDING` rows are recomputed from `FINALIZED` rows + pending logs after every ingest; a destination
reorg deletes pending logs above the fork point and replays (GPU-076 §3 — ids are unchanged, so re-inclusion
re-creates identical rows). `FINALIZED` rows only move forward.

R2 (D02/D05/D12): a projected evidence row exists only for a mined `EvidenceBook.SourceEventConsumed` app
event. `AttestcoinRevenueVerifier.SourceEventVerified` alone (a public probe) projects nothing economic, and
dispatcher/API status never feeds these tables. A deployment carries exactly one execution profile; rows
never mix profiles (`ck_*_profile`), and the reconciliation table records discrepancies without "fixing" them.
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
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..domain import enums as E
from .models import ADDR_CHECK, HEX32, HEX32_CHECK, MONEY, ULID, ULID_CHECK, Base, _in

TIERS = ["PENDING", "FINALIZED"]
TIER_CHECK = f"tier IN {_in(TIERS)}"
DISCREPANCY_KINDS = ["EXPECTED_LAG", "DISCREPANCY", "EXTERNAL_SUBMITTER"]


class ChainDeployment(Base):
    """One projected app deployment: chain, profile, manifest, contract address set, deployment block."""

    __tablename__ = "chain_deployments"
    deployment_id: Mapped[str] = mapped_column(ULID, primary_key=True)
    chain_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    execution_profile: Mapped[str] = mapped_column(String(32), nullable=False)
    env_id: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest_hash: Mapped[str] = mapped_column(String(71), nullable=False)
    deployment_block: Mapped[int] = mapped_column(BigInteger, nullable=False)
    contracts: Mapped[dict] = mapped_column(JSONB, nullable=False)  # {contractName: address}
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    finality_depth: Mapped[int] = mapped_column(Integer, nullable=False, server_default="12")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        CheckConstraint(f"deployment_id {ULID_CHECK}", name="ck_chain_deployments_ulid"),
        CheckConstraint("chain_id > 0", name="ck_chain_deployments_chain"),
        CheckConstraint(f"execution_profile IN {_in(E.ExecutionProfile)}", name="ck_chain_deployments_profile"),
        CheckConstraint("manifest_hash ~ '^sha256:[0-9a-f]{64}$'", name="ck_chain_deployments_manifest"),
        CheckConstraint("deployment_block >= 0 AND finality_depth >= 0", name="ck_chain_deployments_blocks"),
        # a LOCAL_MOCK deployment never lives on a public Creditcoin chain id and vice versa
        CheckConstraint(
            "(execution_profile = 'LOCAL_MOCK') = (chain_id NOT IN (102030, 102031, 102032))",
            name="ck_chain_deployments_mock_chain",
        ),
        UniqueConstraint("chain_id", "manifest_hash", "deployment_block", name="uq_chain_deployments_identity"),
    )


class ChainCursor(Base):
    """Persistent high-water mark per deployment (never re-initialised to 'last N blocks')."""

    __tablename__ = "chain_cursors"
    deployment_id: Mapped[str] = mapped_column(ULID, ForeignKey("chain_deployments.deployment_id", ondelete="RESTRICT"), primary_key=True)
    last_block_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    last_block_hash: Mapped[str] = mapped_column(HEX32, nullable=False)
    finalized_block_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        CheckConstraint(f"last_block_hash {HEX32_CHECK}", name="ck_chain_cursors_hash"),
        CheckConstraint("finalized_block_number <= last_block_number", name="ck_chain_cursors_order"),
    )


class ChainBlock(Base):
    """Canonical block journal for parent-hash continuity and reorg detection."""

    __tablename__ = "chain_blocks"
    deployment_id: Mapped[str] = mapped_column(ULID, ForeignKey("chain_deployments.deployment_id", ondelete="RESTRICT"), primary_key=True)
    number: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    hash: Mapped[str] = mapped_column(HEX32, nullable=False)
    parent_hash: Mapped[str] = mapped_column(HEX32, nullable=False)
    timestamp: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tier: Mapped[str] = mapped_column(String(10), nullable=False, server_default="PENDING")
    __table_args__ = (
        CheckConstraint(f"hash {HEX32_CHECK} AND parent_hash {HEX32_CHECK}", name="ck_chain_blocks_hashes"),
        CheckConstraint(TIER_CHECK, name="ck_chain_blocks_tier"),
    )


class ReorgJournal(Base):
    __tablename__ = "reorg_journal"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    deployment_id: Mapped[str] = mapped_column(ULID, ForeignKey("chain_deployments.deployment_id", ondelete="RESTRICT"), nullable=False)
    fork_block: Mapped[int] = mapped_column(BigInteger, nullable=False)
    old_hash: Mapped[str] = mapped_column(HEX32, nullable=False)
    new_hash: Mapped[str] = mapped_column(HEX32, nullable=False)
    logs_rolled_back: Mapped[int] = mapped_column(Integer, nullable=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (CheckConstraint(f"old_hash {HEX32_CHECK} AND new_hash {HEX32_CHECK}", name="ck_reorg_journal_hashes"),)


class ChainLog(Base):
    """Deduplicated raw + decoded logs of the deployment's contracts (the replay source of every read model)."""

    __tablename__ = "chain_logs"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    deployment_id: Mapped[str] = mapped_column(ULID, ForeignKey("chain_deployments.deployment_id", ondelete="RESTRICT"), nullable=False)
    block_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    block_hash: Mapped[str] = mapped_column(HEX32, nullable=False)
    tx_hash: Mapped[str] = mapped_column(HEX32, nullable=False)
    tx_index: Mapped[int] = mapped_column(Integer, nullable=False)
    log_index: Mapped[int] = mapped_column(Integer, nullable=False)
    tx_status: Mapped[int] = mapped_column(Integer, nullable=False)
    address: Mapped[str] = mapped_column(String(42), nullable=False)
    contract_name: Mapped[str] = mapped_column(String(48), nullable=False)
    event_name: Mapped[str] = mapped_column(String(64), nullable=False)
    topics: Mapped[list] = mapped_column(JSONB, nullable=False)
    data: Mapped[str] = mapped_column(Text, nullable=False)
    decoded: Mapped[dict] = mapped_column(JSONB, nullable=False)
    tier: Mapped[str] = mapped_column(String(10), nullable=False, server_default="PENDING")
    __table_args__ = (
        CheckConstraint(f"block_hash {HEX32_CHECK} AND tx_hash {HEX32_CHECK}", name="ck_chain_logs_hashes"),
        CheckConstraint(f"address {ADDR_CHECK}", name="ck_chain_logs_address"),
        CheckConstraint("tx_status IN (0, 1)", name="ck_chain_logs_tx_status"),
        CheckConstraint("block_number >= 0 AND tx_index >= 0 AND log_index >= 0", name="ck_chain_logs_position"),
        CheckConstraint(TIER_CHECK, name="ck_chain_logs_tier"),
        UniqueConstraint("deployment_id", "block_hash", "tx_hash", "log_index", name="uq_chain_logs_position"),
        Index("ix_chain_logs_block", "deployment_id", "block_number"),
    )


class ProjectedFacility(Base):
    """Facility read model from ledger + manager events (debt components as recorded by events)."""

    __tablename__ = "proj_facilities"
    deployment_id: Mapped[str] = mapped_column(ULID, ForeignKey("chain_deployments.deployment_id", ondelete="RESTRICT"), primary_key=True)
    tier: Mapped[str] = mapped_column(String(10), primary_key=True)
    facility_key: Mapped[str] = mapped_column(HEX32, primary_key=True)  # on-chain bytes32 FacilityId
    borrower_key: Mapped[str | None] = mapped_column(HEX32)
    execution_profile: Mapped[str] = mapped_column(String(32), nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    principal: Mapped[int] = mapped_column(MONEY, nullable=False, server_default="0")
    fees: Mapped[int] = mapped_column(MONEY, nullable=False, server_default="0")
    unpaid_interest_recorded: Mapped[int] = mapped_column(MONEY, nullable=False, server_default="0")
    rate_bps: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_accrual_at: Mapped[int | None] = mapped_column(BigInteger)
    accrual_frozen: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    last_decision_hash: Mapped[str | None] = mapped_column(HEX32)
    authorization_valid_until: Mapped[int | None] = mapped_column(BigInteger)
    last_block: Mapped[int] = mapped_column(BigInteger, nullable=False)
    __table_args__ = (
        CheckConstraint(f"facility_key {HEX32_CHECK}", name="ck_proj_facilities_key"),
        CheckConstraint(f"execution_profile IN {_in(E.ExecutionProfile)}", name="ck_proj_facilities_profile"),
        CheckConstraint(f"state IN {_in(E.FacilityState)}", name="ck_proj_facilities_state"),
        CheckConstraint("principal >= 0 AND fees >= 0 AND unpaid_interest_recorded >= 0", name="ck_proj_facilities_amounts"),
        CheckConstraint(TIER_CHECK, name="ck_proj_facilities_tier"),
    )


class ProjectedEvidence(Base):
    """Mined EvidenceBook consumptions — the only on-chain source of a projected evidence row (R2-D02)."""

    __tablename__ = "proj_evidence"
    deployment_id: Mapped[str] = mapped_column(ULID, ForeignKey("chain_deployments.deployment_id", ondelete="RESTRICT"), primary_key=True)
    tier: Mapped[str] = mapped_column(String(10), primary_key=True)
    source_event_id: Mapped[str] = mapped_column(HEX32, primary_key=True)
    economic_event_key: Mapped[str] = mapped_column(HEX32, nullable=False)
    consumer_address: Mapped[str] = mapped_column(String(42), nullable=False)
    meaning: Mapped[str] = mapped_column(String(32), nullable=False)
    manifest_hash: Mapped[str] = mapped_column(HEX32, nullable=False)  # bytes32 as emitted
    verification_method: Mapped[str] = mapped_column(String(32), nullable=False)
    execution_profile: Mapped[str] = mapped_column(String(32), nullable=False)
    verified_in_same_tx: Mapped[bool] = mapped_column(Boolean, nullable=False)
    proven_height: Mapped[int | None] = mapped_column(BigInteger)
    proven_tx_index: Mapped[int | None] = mapped_column(Integer)
    proven_log_ordinal: Mapped[int | None] = mapped_column(Integer)
    consumption_tx_hash: Mapped[str] = mapped_column(HEX32, nullable=False)
    block_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    block_hash: Mapped[str] = mapped_column(HEX32, nullable=False)
    log_index: Mapped[int] = mapped_column(Integer, nullable=False)
    __table_args__ = (
        CheckConstraint(f"source_event_id {HEX32_CHECK} AND economic_event_key {HEX32_CHECK}", name="ck_proj_evidence_ids"),
        CheckConstraint(f"consumer_address {ADDR_CHECK}", name="ck_proj_evidence_consumer"),
        CheckConstraint(f"verification_method IN {_in(E.VerificationMethod)}", name="ck_proj_evidence_method"),
        CheckConstraint(f"execution_profile IN {_in(E.ExecutionProfile)}", name="ck_proj_evidence_profile"),
        CheckConstraint("(verification_method = 'LOCAL_MOCK') = (execution_profile = 'LOCAL_MOCK')", name="ck_proj_evidence_mock_profile"),
        CheckConstraint(TIER_CHECK, name="ck_proj_evidence_tier"),
        UniqueConstraint("deployment_id", "tier", "economic_event_key", name="uq_proj_evidence_economic"),
    )


class ProjectedEntity(Base):
    """Generic keyed read model: vault, reservations, control agreements, roles, providers, policy, admin."""

    __tablename__ = "proj_entities"
    deployment_id: Mapped[str] = mapped_column(ULID, ForeignKey("chain_deployments.deployment_id", ondelete="RESTRICT"), primary_key=True)
    tier: Mapped[str] = mapped_column(String(10), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), primary_key=True)
    entity_key: Mapped[str] = mapped_column(String(160), primary_key=True)
    state: Mapped[dict] = mapped_column(JSONB, nullable=False)
    last_block: Mapped[int] = mapped_column(BigInteger, nullable=False)
    __table_args__ = (
        CheckConstraint(
            "kind IN ('VAULT','RESERVATION','CONTROL_AGREEMENT','ROLE','PROVIDER','POLICY','VERIFIER_BINDING','RECEIVABLE','ESCROW','ADMIN')",
            name="ck_proj_entities_kind",
        ),
        CheckConstraint(TIER_CHECK, name="ck_proj_entities_tier"),
    )


class ProjectedReceivable(Base):
    """Receivable read model replayed from ReceivableBook events (GPU-QA-0915: history mirrors were import-only).

    The book only writes after the immutable verifier accepted the source log in the same transaction, so a row
    here is finalized chain fact — but it carries no proof-request lifecycle; the ledger `receivables` table keeps
    that when an import exists. Amounts are the event-carried values; `unpaid_after` is checked against them.
    """

    __tablename__ = "proj_receivables"
    deployment_id: Mapped[str] = mapped_column(ULID, ForeignKey("chain_deployments.deployment_id", ondelete="RESTRICT"), primary_key=True)
    tier: Mapped[str] = mapped_column(String(10), primary_key=True)
    receivable_key: Mapped[str] = mapped_column(HEX32, primary_key=True)  # on-chain bytes32 receivable id
    account_key: Mapped[str] = mapped_column(HEX32, nullable=False)
    obligation_ref: Mapped[str] = mapped_column(HEX32, nullable=False)
    facility_key: Mapped[str | None] = mapped_column(HEX32)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    net: Mapped[int] = mapped_column(MONEY, nullable=False, server_default="0")
    paid: Mapped[int] = mapped_column(MONEY, nullable=False, server_default="0")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    disputed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    recognition_tx_hash: Mapped[str] = mapped_column(HEX32, nullable=False)
    last_tx_hash: Mapped[str] = mapped_column(HEX32, nullable=False)
    first_block: Mapped[int] = mapped_column(BigInteger, nullable=False)
    last_block: Mapped[int] = mapped_column(BigInteger, nullable=False)
    history: Mapped[list] = mapped_column(JSONB, nullable=False)  # [{event, txHash, blockNumber, logIndex, args}]
    __table_args__ = (
        CheckConstraint(f"receivable_key {HEX32_CHECK} AND account_key {HEX32_CHECK} AND obligation_ref {HEX32_CHECK}", name="ck_proj_receivables_keys"),
        CheckConstraint(f"recognition_tx_hash {HEX32_CHECK} AND last_tx_hash {HEX32_CHECK}", name="ck_proj_receivables_hashes"),
        CheckConstraint("state IN ('OPEN','ASSIGNED','PAID','CANCELLED')", name="ck_proj_receivables_state"),
        CheckConstraint("net >= 0 AND paid >= 0 AND paid <= net AND revision >= 1", name="ck_proj_receivables_amounts"),
        CheckConstraint(TIER_CHECK, name="ck_proj_receivables_tier"),
        Index("ix_proj_receivables_account", "deployment_id", "tier", "account_key"),
        Index("ix_proj_receivables_facility", "deployment_id", "tier", "facility_key"),
    )


class ProjectedRepayment(Base):
    """One direct repayment leg per Repaid event, paired with its DebtLedger.Allocated and vault receipt."""

    __tablename__ = "proj_repayments"
    deployment_id: Mapped[str] = mapped_column(ULID, ForeignKey("chain_deployments.deployment_id", ondelete="RESTRICT"), primary_key=True)
    tier: Mapped[str] = mapped_column(String(10), primary_key=True)
    tx_hash: Mapped[str] = mapped_column(HEX32, primary_key=True)
    log_index: Mapped[int] = mapped_column(Integer, primary_key=True)  # the Repaid log
    facility_key: Mapped[str] = mapped_column(HEX32, nullable=False)
    repaid_contract: Mapped[str] = mapped_column(String(48), nullable=False)
    payer: Mapped[str] = mapped_column(String(42), nullable=False)
    settlement_ref: Mapped[str | None] = mapped_column(HEX32)
    requested: Mapped[int] = mapped_column(MONEY, nullable=False)
    received: Mapped[int] = mapped_column(MONEY, nullable=False)
    fee_paid: Mapped[int] = mapped_column(MONEY, nullable=False)
    interest_paid: Mapped[int] = mapped_column(MONEY, nullable=False)
    principal_paid: Mapped[int] = mapped_column(MONEY, nullable=False)
    excess: Mapped[int] = mapped_column(MONEY, nullable=False)
    new_debt: Mapped[int] = mapped_column(MONEY, nullable=False)
    block_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    block_hash: Mapped[str] = mapped_column(HEX32, nullable=False)
    block_timestamp: Mapped[int] = mapped_column(BigInteger, nullable=False)
    __table_args__ = (
        CheckConstraint(f"tx_hash {HEX32_CHECK} AND facility_key {HEX32_CHECK} AND block_hash {HEX32_CHECK}", name="ck_proj_repayments_hashes"),
        CheckConstraint(f"payer {ADDR_CHECK}", name="ck_proj_repayments_payer"),
        CheckConstraint("repaid_contract IN ('RepaymentRouter','CreditFacilityManager')", name="ck_proj_repayments_contract"),
        CheckConstraint("requested >= 0 AND received >= 0 AND fee_paid >= 0 AND interest_paid >= 0 AND principal_paid >= 0 AND excess >= 0 AND new_debt >= 0 AND fee_paid + interest_paid + principal_paid + excess = received", name="ck_proj_repayments_amounts"),
        CheckConstraint(TIER_CHECK, name="ck_proj_repayments_tier"),
        Index("ix_proj_repayments_facility", "deployment_id", "tier", "facility_key"),
    )


class ProjectionDiscrepancy(Base):
    """Reconciliation findings (projected vs canonical eth_call at the same block); never auto-corrected."""

    __tablename__ = "projection_discrepancies"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    deployment_id: Mapped[str] = mapped_column(ULID, ForeignKey("chain_deployments.deployment_id", ondelete="RESTRICT"), nullable=False)
    block_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    projected: Mapped[str] = mapped_column(Text, nullable=False)
    canonical: Mapped[str] = mapped_column(Text, nullable=False)
    classification: Mapped[str] = mapped_column(String(24), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (CheckConstraint(f"classification IN {_in(DISCREPANCY_KINDS)}", name="ck_projection_discrepancies_kind"),)
