"""Versioned read DTOs. Missing financial facts are null, never invented zero balances."""

from datetime import datetime
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict


class DTO(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AssetRef(DTO):
    chainId: int
    address: str | None
    decimals: int


class Money(DTO):
    amount: str
    asset: AssetRef


class CanonicalBlock(DTO):
    number: int
    hash: str
    timestamp: int


class ReadMeta(DTO):
    executionProfile: str
    source: Literal["DATABASE_LEDGER", "CHAIN_PROJECTION"] = "DATABASE_LEDGER"
    chainId: int
    deploymentId: str
    manifestHash: str
    observedAt: datetime
    canonicalBlock: CanonicalBlock
    freshness: Literal["FRESH", "STALE"]
    # This is an indexer watermark, NOT a claim that every offchain row is canonical.
    canonicalScope: Literal["INDEXER_WATERMARK_ONLY"] = "INDEXER_WATERMARK_ONLY"
    financialAuthorization: Literal[False] = False


class Pagination(DTO):
    limit: int
    nextCursor: str | None


T = TypeVar("T")


class Page(DTO, Generic[T]):
    schemaVersion: Literal["1.0"] = "1.0"
    data: list[T]
    meta: ReadMeta
    pagination: Pagination


class Item(DTO, Generic[T]):
    schemaVersion: Literal["1.0"] = "1.0"
    data: T
    meta: ReadMeta


class ProviderDTO(DTO):
    providerId: str
    displayName: str
    executionProfile: str
    environmentStatus: str
    requiredVerification: str
    sourceEnvId: str
    sourceChainKey: int
    sourceChainId: int
    manifestHash: str | None
    testOnly: bool
    capabilities: dict[str, Literal["SUPPORTED", "UNSUPPORTED", "UNCONFIRMED"]]


class ConnectionDTO(DTO):
    providerAccountId: str
    providerId: str
    borrowerId: str
    externalAccountId: str
    credentialConfigured: bool
    controlVersion: int
    lastVerifiedAt: datetime | None
    accountReviewState: str | None
    createdAt: datetime


class AssetDTO(DTO):
    assetId: str
    kind: str
    sku: str | None
    unitCount: int
    ownership: str
    ownershipReview: str
    identityConfidence: str
    status: str
    parentAssetId: str | None
    eligible: bool


class CreditTransitionDTO(DTO):
    fromState: str
    toState: str
    trigger: str  # bytes32 as emitted
    triggerText: str | None  # decoded when the trigger is a short ASCII label (e.g. installment_overdue)
    authority: str
    txHash: str
    blockNumber: int
    at: datetime


class CreditScheduleDTO(DTO):
    dueAt: datetime
    graceSeconds: int
    dueAmount: Money
    setAt: datetime
    disputed: bool


class CreditStatusDTO(DTO):
    """Why the facility is in its state, replayed from finalized manager / recovery / vault events."""

    state: str
    stateTrigger: str | None
    stateTriggerText: str | None
    stateAuthority: str | None
    stateChangedAt: datetime | None
    stateTxHash: str | None
    accrualFrozen: bool
    schedule: CreditScheduleDTO | None
    defaultReason: str | None
    defaultReasonText: str | None
    defaultApprovedAt: datetime | None
    reserveOwner: str | None
    reservePledged: Money
    reserveApplied: Money
    impairment: Money
    lossId: str | None
    lossAmount: Money | None
    writtenOffAt: datetime | None
    transitions: list[CreditTransitionDTO]
    recordOrigin: Literal["FINALIZED_CHAIN_EVENTS"] = "FINALIZED_CHAIN_EVENTS"


class FacilityDTO(DTO):
    facilityId: str
    borrowerId: str
    vaultId: str
    executionProfile: str
    state: str
    loanAsset: AssetRef
    recordedPrincipal: Money
    recordedUnpaidInterest: Money
    recordedFees: Money
    recordedReservedDraws: Money
    recordedApprovedCap: Money
    rateBps: str
    advanceRateBps: str
    maturityAt: datetime | None
    controlAgreementId: str | None
    updatedAt: datetime
    # A reviewed binding permits event-backed reads; current accrued debt/draw uses transaction-context.
    canonicalFacilityId: str | None = None
    recordOrigin: Literal["DATABASE_METADATA", "FINALIZED_CHAIN_EVENTS"] = "DATABASE_METADATA"
    canonicalFinancials: None = None
    availableDraw: None = None
    financialReadiness: Literal["UNAVAILABLE_ID_BINDING", "TRANSACTION_CONTEXT_AVAILABLE"] = "UNAVAILABLE_ID_BINDING"
    # Present only with finalized chain events (never from database metadata): state triggers, schedule, default,
    # reserve, impairment and write-off — the explanation behind a non-performing state.
    credit: CreditStatusDTO | None = None


class EvidenceStages(DTO):
    proofRequestId: str | None = None
    proofRequestStatus: str | None = None
    proofReadyAt: datetime | None = None
    nativeSubmissionStatus: str | None = None
    nativeStatus: str | None = None
    verificationMethod: str | None = None
    consumptionId: str | None = None
    sourceEventId: str | None = None
    nativeCanonical: bool = False
    earningsProvenance: Literal["UNCLASSIFIED", "SIMULATED"]
    businessEligibility: None = None
    businessEligibilityReason: Literal["AUTHORITATIVE_ASSESSMENT_UNAVAILABLE"] = "AUTHORITATIVE_ASSESSMENT_UNAVAILABLE"


class ReceivableDTO(DTO):
    receivableId: str
    economicEventId: str
    providerAccountId: str
    facilityId: str | None
    state: str
    revision: int
    gross: Money
    net: Money
    paidAmount: Money
    unpaidAmount: Money
    periodFrom: datetime | None
    periodTo: datetime | None
    dueAt: datetime | None
    updatedAt: datetime
    evidence: EvidenceStages
    # LEDGER_IMPORT rows come from the reviewed ledger (with their proof-request lifecycle); FINALIZED_CHAIN_EVENTS
    # rows are replayed from ReceivableBook events on the canonical journal and carry no import-only fields.
    recordOrigin: Literal["LEDGER_IMPORT", "FINALIZED_CHAIN_EVENTS"] = "LEDGER_IMPORT"
    canonicalReceivableId: str | None = None


class CashDTO(DTO):
    cashReceiptId: str
    amount: Money
    cashState: str
    sourceKind: str
    txHash: str
    logIndex: int
    receivedAt: datetime


class SettlementDTO(DTO):
    settlementId: str
    providerAccountId: str
    state: str
    sourceAmount: Money
    payoutConsumptionId: str | None
    destinationReceipts: list[CashDTO]
    # A source-paid state cannot become destination cash by serialization.
    destinationCashRecorded: bool
    updatedAt: datetime


class ControlDTO(DTO):
    controlAgreementId: str
    borrowerId: str
    providerAccountId: str
    controlGrade: str
    version: int
    changeAuthority: str
    receiverChainId: int | None
    receiverAddress: str | None
    agreementHash: str | None
    effectiveFrom: datetime | None
    effectiveTo: datetime | None
    lastObservedAt: datetime | None
    observationFreshness: Literal["FRESH", "STALE", "UNAVAILABLE"]
    observationIsEnforcementApproval: Literal[False] = False


class RepaymentDTO(DTO):
    repaymentAllocationId: str
    facilityId: str
    cashReceiptId: str | None
    received: Money
    feePaid: Money
    interestPaid: Money
    principalPaid: Money
    excess: Money
    recordedNewDebt: Money
    onchainTxHash: str | None
    allocatedAt: datetime
    repaymentApplied: bool | None
    applicationEvidence: Literal["FINALIZED_MANAGER_EVENT", "FINALIZED_ROUTER_EVENT", "UNCONFIRMED_LEDGER_RECORD"]
    recordOrigin: Literal["LEDGER_IMPORT", "FINALIZED_CHAIN_EVENTS"] = "LEDGER_IMPORT"
    payerAddress: str | None = None
    settlementRef: str | None = None


class RecoveryDTO(DTO):
    recoveryEventId: str
    facilityId: str
    kind: str
    amount: Money
    cashReceiptId: str | None
    occurredAt: datetime


class OperationDTO(DTO):
    exceptionId: str
    kind: str
    severity: str
    state: str
    entityType: str
    entityId: str
    createdAt: datetime
    resolvedAt: datetime | None
    version: int = 0
    assignee: str | None = None
    owner: str | None = None
    dueAt: datetime | None = None
    runbook: str = "/docs/operations"
    audit: list[dict] = []
