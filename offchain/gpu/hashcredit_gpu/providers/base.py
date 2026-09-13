"""
ProviderAdapter contract (GPU-019). Business-data connectors for partner APIs (PIVOT §8.1).

What an adapter is: a typed, namespaced (`provider_slug`) reader/writer of the provider's *own*
statements — assets, revenue statements, settlements, control state — plus optional write actions.
What it is not: a source of proof. Official source-chain facts travel only through the Attestcoin
native path (GPU-075/078/079/031). `assert_native_capable` therefore always raises for an adapter,
and `assert_production_admissible` refuses mocks, LOCAL/NATIVE_TESTNET profiles, simulated revenue
and unsupported source chains (R2-D04/D05/D08/D12).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC, datetime

from hashcredit_gpu.domain import ExecutionProfile

from .errors import (
    ExpiredData,
    NotNativeCapable,
    NotProductionAdmissible,
    UnsupportedChainError,
    UnsupportedOperation,
)
from .types import (
    AccountRef,
    AdapterIdentity,
    AssetListing,
    Capabilities,
    ClaimRequest,
    ClaimResult,
    ControlChangeRequest,
    ControlChangeResult,
    ControlStateObservation,
    Cursor,
    Page,
    RevenueObservation,
    SettlementObservation,
    Support,
    Window,
)

MOCK_SLUG_PREFIXES = ("mock-", "mockdepin-testonly")


class ProviderAdapter(ABC):
    """Abstract contract. Concrete adapters must not widen return types or relax validation."""

    @abstractmethod
    def identity(self) -> AdapterIdentity: ...

    @abstractmethod
    def capabilities(self) -> Capabilities: ...

    @abstractmethod
    def list_assets(
        self, account: AccountRef, cursor: Cursor | None = None
    ) -> Page[AssetListing]: ...

    @abstractmethod
    def fetch_revenue(
        self, account: AccountRef, window: Window, cursor: Cursor | None = None
    ) -> Page[RevenueObservation]: ...

    @abstractmethod
    def fetch_settlements(
        self, account: AccountRef, window: Window, cursor: Cursor | None = None
    ) -> Page[SettlementObservation]: ...

    @abstractmethod
    def get_control_state(self, account: AccountRef) -> ControlStateObservation: ...

    @abstractmethod
    def claim_revenue(self, request: ClaimRequest) -> ClaimResult: ...

    @abstractmethod
    def request_control_change(self, request: ControlChangeRequest) -> ControlChangeResult: ...

    # ------------------------------------------------------------------ shared guards

    def _require(self, op: str) -> None:
        cap = self.capabilities()
        if getattr(cap, op) is not Support.SUPPORTED:
            raise UnsupportedOperation(f"{self.identity().provider_slug}.{op}: {getattr(cap, op)}")

    def _require_account(self, account: AccountRef) -> None:
        slug = self.identity().provider_slug
        if account.provider_slug != slug:
            raise UnsupportedOperation(
                f"account namespace {account.provider_slug!r} != adapter {slug!r}"
            )

    def _require_chain(self, chain_id: int) -> None:
        if chain_id not in self.identity().source_chain_ids:
            raise UnsupportedChainError(
                f"{self.identity().provider_slug}: chain {chain_id} not declared for this adapter"
            )


def check_freshness(as_of: datetime, window: Window) -> None:
    """Reject observations older than the caller's bound. Expired data is an error, not a value."""
    now = window.as_of or datetime.now(UTC)
    age = (now - as_of).total_seconds()
    if age > window.max_age_seconds:
        raise ExpiredData(
            f"observation as_of={as_of.isoformat()} is {int(age)}s old > {window.max_age_seconds}s"
        )


def is_mock_slug(slug: str) -> bool:
    return any(slug == p or slug.startswith(p) for p in MOCK_SLUG_PREFIXES)


def assert_production_admissible(adapter: ProviderAdapter) -> None:
    """Gate for production admission / credit decisions. Raises NotProductionAdmissible.

    Refuses: mock adapters (by flag or slug), non-PRODUCTION execution profile (a genuine testnet
    proof path is still not production), simulated/unknown partner revenue, and — even when the
    business API is healthy — an unsupported or unknown official source chain (R2-D08).
    """
    ident = adapter.identity()
    cap = adapter.capabilities()
    reasons: list[str] = []
    if ident.is_mock or is_mock_slug(ident.provider_slug):
        reasons.append("mock adapter")
    if ident.execution_profile is not ExecutionProfile.PRODUCTION:
        reasons.append(f"execution profile {ident.execution_profile}")
    if ident.partner_revenue != "REAL":
        reasons.append(f"partner revenue {ident.partner_revenue}")
    if cap.source_support is not Support.SUPPORTED:
        reasons.append(f"official source support {cap.source_support}")
    if reasons:
        raise NotProductionAdmissible(f"{ident.provider_slug}: " + "; ".join(reasons))


def assert_native_capable(adapter: ProviderAdapter) -> None:
    """A ProviderAdapter never has official proof capability. Always raises (GPU-076 §8, R2-D02)."""
    raise NotNativeCapable(
        f"{adapter.identity().provider_slug}: provider business data is OFFCHAIN_ASSERTION; "
        "official proofs come only from the Attestcoin proof worker (GPU-079) + native verifier (GPU-078)"
    )
