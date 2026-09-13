"""
ProviderAdapter input/output types (GPU-019; PIVOT §8.1; domain-model.md §3).

Every observation an adapter returns is business data asserted by the provider's API:
`provenance=PROVIDER_API`, `trust=ASSERTED`, `verificationMethod=OFFCHAIN_ASSERTION`,
`nativeStatus=NOT_REQUIRED`. Those four fields are frozen `Literal`s — a caller cannot construct an
adapter observation that claims PROVEN/ATTESTCOIN_NATIVE/NATIVE_ACCEPTED (R2-D04/D05, GPU-076 §8).
Money is always `Money` (integer base-unit string + explicit AssetRef); floats are rejected upstream.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, Field, field_validator, model_validator

from hashcredit_gpu.domain import (
    AssetKind,
    AssetRef,
    ControlGrade,
    EarningsProvenance,
    ExecutionProfile,
    Money,
    NativeStatus,
    Trust,
    VerificationMethod,
)


class Support(StrEnum):
    SUPPORTED = "SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"
    UNKNOWN = "UNKNOWN"  # treated as UNSUPPORTED by every caller

    @property
    def usable(self) -> bool:
        return self is Support.SUPPORTED


class Capabilities(BaseModel, frozen=True):
    """Per-operation support. Read and write are independent; a read adapter implies no write."""

    list_assets: Support = Support.UNKNOWN
    fetch_revenue: Support = Support.UNKNOWN
    fetch_settlements: Support = Support.UNKNOWN
    get_control_state: Support = Support.UNKNOWN
    claim_revenue: Support = Support.UNKNOWN
    request_control_change: Support = Support.UNKNOWN
    # Whether the provider's *payout/obligation source chain* is in the official Attestcoin support
    # table (GPU-075 manifest). Business API health says nothing about this (R2-D08).
    source_support: Support = Support.UNKNOWN

    def require(self, op: str) -> None:
        if getattr(self, op) is not Support.SUPPORTED:
            from .errors import UnsupportedOperation

            raise UnsupportedOperation(f"{op}: {getattr(self, op)}")


class Cursor(BaseModel, frozen=True):
    token: str | None = None  # opaque; None == start
    has_more: bool = False


T = TypeVar("T")


class Page(BaseModel, Generic[T], frozen=True):
    items: tuple[T, ...]
    next: Cursor


class Window(BaseModel, frozen=True):
    start: datetime
    end: datetime
    # Observations older than this (relative to `as_of`) are rejected with ExpiredData.
    max_age_seconds: int = Field(default=86_400, ge=0)
    as_of: datetime | None = None

    @model_validator(mode="after")
    def _ordered(self) -> Window:
        if self.end < self.start:
            raise ValueError("window end before start")
        return self


class AccountRef(BaseModel, frozen=True):
    provider_slug: str
    external_account_id: str

    @property
    def account_key(self) -> str:
        return f"{self.provider_slug}:{self.external_account_id}"


class _AssertedObservation(BaseModel, frozen=True):
    """Fields callers cannot upgrade: an adapter observation is never a source fact."""

    provenance: Literal["PROVIDER_API"] = "PROVIDER_API"
    trust: Literal[Trust.ASSERTED] = Trust.ASSERTED
    verification_method: Literal[VerificationMethod.OFFCHAIN_ASSERTION] = (
        VerificationMethod.OFFCHAIN_ASSERTION
    )
    native_status: Literal[NativeStatus.NOT_REQUIRED] = NativeStatus.NOT_REQUIRED
    provider_slug: str
    observed_at: datetime
    as_of: datetime  # provider-stated time of the fact (CLAIMED; never a proven time)

    @field_validator("observed_at", "as_of")
    @classmethod
    def _tz(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware")
        return v.astimezone(UTC)


class AssetListing(_AssertedObservation, frozen=True):
    account: AccountRef
    external_asset_id: str
    kind: AssetKind
    parent_external_id: str | None = None
    attributes: dict[str, str] = Field(default_factory=dict)  # de-identified, string-only


class RevenueObservation(_AssertedObservation, frozen=True):
    account: AccountRef
    provider_event_ref: str  # provider's stable ref (invoice/obligation/statement id)
    revision: int = Field(ge=1)
    period_start: datetime
    period_end: datetime
    gross: Money
    deductions: Money
    net: Money
    earnings_provenance: EarningsProvenance
    settlement_ref: str | None = None

    @model_validator(mode="after")
    def _consistent(self) -> RevenueObservation:
        if (
            self.gross.asset.key != self.net.asset.key
            or self.gross.asset.key != self.deductions.asset.key
        ):
            raise ValueError("gross/deductions/net must share one asset")
        if self.gross.units - self.deductions.units != self.net.units:
            raise ValueError("net must equal gross - deductions")
        if self.net.units < 0 or self.deductions.units < 0:
            raise ValueError("negative revenue components")
        return self


class SettlementObservation(_AssertedObservation, frozen=True):
    account: AccountRef
    settlement_ref: str
    revision: int = Field(ge=1)
    amount: Money
    payer: str | None
    payee: str | None
    paid_at: datetime | None  # CLAIMED
    status: Literal["ANNOUNCED", "PAID", "REVERSED"]
    tx_ref: str | None = None  # provider-claimed tx hash; a hint for GPU-079, never a proof


class ControlStateObservation(_AssertedObservation, frozen=True):
    account: AccountRef
    receiver: str | None
    receiver_chain_id: int | None
    borrower_can_change_receiver: bool | None  # None == unknown → treated as "can" by callers
    # The provider-reported state. A registry grade is set only by GPU-032 with PoC evidence;
    # the adapter cannot output E2 by itself (it reports the *observed* facts, at most E1).
    observed_grade: Literal[ControlGrade.E0, ControlGrade.E1] = ControlGrade.E0


class ClaimRequest(BaseModel, frozen=True):
    account: AccountRef
    amount: Money | None = None  # None == claim all claimable
    idempotency_key: str


class ClaimResult(_AssertedObservation, frozen=True):
    account: AccountRef
    idempotency_key: str
    accepted: bool
    provider_ref: str | None
    # Success here is a provider API acknowledgement, never destination cash (R2-D07).
    cash_state: Literal["NONE"] = "NONE"


class ControlChangeRequest(BaseModel, frozen=True):
    account: AccountRef
    new_receiver: str
    new_receiver_chain_id: int
    idempotency_key: str


class ControlChangeResult(_AssertedObservation, frozen=True):
    account: AccountRef
    idempotency_key: str
    accepted: bool
    provider_ref: str | None
    # Acceptance of a change request is not E2 (GPU-032 records grade with PoC evidence only).
    control_grade_effect: Literal["NONE"] = "NONE"


class AdapterIdentity(BaseModel, frozen=True):
    provider_slug: str
    execution_profile: ExecutionProfile
    is_mock: bool
    partner_revenue: Literal["REAL", "SIMULATED", "UNKNOWN"]
    source_chain_ids: tuple[
        int, ...
    ]  # chains the adapter is allowed to report; others → UnsupportedChainError
    supported_assets: tuple[AssetRef, ...]


__all__ = [
    "AccountRef",
    "AdapterIdentity",
    "AssetListing",
    "Capabilities",
    "ClaimRequest",
    "ClaimResult",
    "ControlChangeRequest",
    "ControlChangeResult",
    "ControlStateObservation",
    "Cursor",
    "Page",
    "RevenueObservation",
    "SettlementObservation",
    "Support",
    "Window",
]
