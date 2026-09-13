"""
Fixed enumerations (docs/gpu/domain-model.md §6). `tests/test_schema.py` asserts these are identical to
the JSON schema enums so DB, API and Solidity cannot drift apart silently.
"""

from enum import StrEnum


class ExecutionProfile(StrEnum):
    LOCAL_MOCK = "LOCAL_MOCK"
    NATIVE_TESTNET = "NATIVE_TESTNET"
    PRODUCTION = "PRODUCTION"


class VerificationMethod(StrEnum):
    ATTESTCOIN_NATIVE = "ATTESTCOIN_NATIVE"
    LOCAL_MOCK = "LOCAL_MOCK"
    OFFCHAIN_ASSERTION = "OFFCHAIN_ASSERTION"


class NativeStatus(StrEnum):
    NOT_REQUIRED = "NOT_REQUIRED"
    NOT_REQUESTED = "NOT_REQUESTED"
    OBSERVED = "OBSERVED"
    WAITING_ATTESTATION = "WAITING_ATTESTATION"
    PROOF_READY = "PROOF_READY"
    SUBMITTED = "SUBMITTED"
    NATIVE_ACCEPTED = "NATIVE_ACCEPTED"
    CONSUMED = "CONSUMED"
    INVALID = "INVALID"
    UNSUPPORTED = "UNSUPPORTED"
    EXPIRED = "EXPIRED"


class EarningsProvenance(StrEnum):
    UNCLASSIFIED = "UNCLASSIFIED"
    PROVIDER_SETTLEMENT = "PROVIDER_SETTLEMENT"
    PROVIDER_INCENTIVE = "PROVIDER_INCENTIVE"
    SELF_TRANSFER = "SELF_TRANSFER"
    THIRD_PARTY_UNKNOWN = "THIRD_PARTY_UNKNOWN"
    REFUND_OR_REVERSAL = "REFUND_OR_REVERSAL"
    SIMULATED = "SIMULATED"


class ControlGrade(StrEnum):
    E0 = "E0"
    E1 = "E1"
    E2 = "E2"
    E3 = "E3"


class CashState(StrEnum):
    NONE = "NONE"
    SOURCE_ESCROW = "SOURCE_ESCROW"
    IN_FLIGHT = "IN_FLIGHT"
    DESTINATION_RECEIVED = "DESTINATION_RECEIVED"
    ALLOCATED = "ALLOCATED"
    RETURNED = "RETURNED"


class EnvironmentStatus(StrEnum):
    UNCONFIRMED = "UNCONFIRMED"
    PROBED = "PROBED"
    UNSUPPORTED = "UNSUPPORTED"


class FacilityState(StrEnum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    CONTROL_PENDING = "CONTROL_PENDING"
    ACTIVE = "ACTIVE"
    DRAW_FROZEN = "DRAW_FROZEN"
    DELINQUENT = "DELINQUENT"
    DEFAULTED = "DEFAULTED"
    RECOVERY = "RECOVERY"
    REPAID = "REPAID"
    RELEASED = "RELEASED"
    CLOSED_WITH_LOSS = "CLOSED_WITH_LOSS"


class ReceivableState(StrEnum):
    RECOGNIZED = "RECOGNIZED"
    ASSIGNED = "ASSIGNED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    DISPUTED = "DISPUTED"
    CANCELLED = "CANCELLED"
    WRITTEN_OFF = "WRITTEN_OFF"


class SettlementState(StrEnum):
    ANNOUNCED = "ANNOUNCED"
    PAID_AT_SOURCE = "PAID_AT_SOURCE"
    CONVERTING = "CONVERTING"
    RECEIVED_AT_DESTINATION = "RECEIVED_AT_DESTINATION"
    ALLOCATED = "ALLOCATED"
    REVERSED = "REVERSED"


class AssetKind(StrEnum):
    PHYSICAL_GPU = "PHYSICAL_GPU"
    MIG_PARTITION = "MIG_PARTITION"
    VGPU = "VGPU"
    VM = "VM"
    CONTAINER = "CONTAINER"
    STAKING_GROUP = "STAKING_GROUP"
    NODE_NFT = "NODE_NFT"


class EconomicEventType(StrEnum):
    OBLIGATION = "OBLIGATION"
    ASSIGNMENT = "ASSIGNMENT"
    CORRECTION = "CORRECTION"
    PAYOUT = "PAYOUT"
    CANCELLATION = "CANCELLATION"
    REFUND = "REFUND"


class Trust(StrEnum):
    PROVEN = "PROVEN"
    ASSERTED = "ASSERTED"
    OBSERVED = "OBSERVED"
    CLAIMED = "CLAIMED"


class Role(StrEnum):
    BORROWER = "borrower"
    LP = "lp"
    UNDERWRITER = "underwriter"
    OPERATOR = "operator"
    KEEPER = "keeper"
    GUARDIAN = "guardian"
    TREASURY = "treasury"
    SYSTEM = "system"


# Name of the JSON-schema $def each enum mirrors (used by the parity test).
SCHEMA_DEF_FOR = {
    ExecutionProfile: "ExecutionProfile",
    VerificationMethod: "VerificationMethod",
    NativeStatus: "NativeStatus",
    EarningsProvenance: "EarningsProvenance",
    ControlGrade: "ControlGrade",
    CashState: "CashState",
    EnvironmentStatus: "EnvironmentStatus",
    FacilityState: "FacilityState",
    ReceivableState: "ReceivableState",
    SettlementState: "SettlementState",
    AssetKind: "AssetKind",
    EconomicEventType: "EconomicEventType",
    Trust: "Trust",
    Role: "Role",
}
