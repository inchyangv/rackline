"""
MockProviderAdapter (GPU-019) — LOCAL harness fed by a de-identified JSON fixture.

Tagged `is_mock=True`, slug must start with `mock-` (or be `mockdepin-testonly`), execution profile
LOCAL_MOCK unless the fixture says NATIVE_TESTNET (which is still not production). Write operations are
UNSUPPORTED unless the fixture enables them. It can never pass `assert_production_admissible`.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hashcredit_gpu.domain import AssetKind, AssetRef, EarningsProvenance, ExecutionProfile, Money

from .base import ProviderAdapter, check_freshness, is_mock_slug
from .errors import (
    MalformedResponse,
    MissingUnit,
    RateLimited,
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

_ISO = "%Y-%m-%dT%H:%M:%S%z"


def _dt(v: Any) -> datetime:
    if not isinstance(v, str):
        raise MalformedResponse(f"timestamp must be a string, got {type(v).__name__}")
    try:
        d = datetime.fromisoformat(v)  # 3.11+: accepts "Z"
    except ValueError as e:
        raise MalformedResponse(f"bad timestamp {v!r}") from e
    if d.tzinfo is None:
        raise MalformedResponse(f"naive timestamp {v!r}")
    return d.astimezone(UTC)


class MockProviderAdapter(ProviderAdapter):
    PAGE_SIZE = 2

    def __init__(self, fixture: dict[str, Any] | str | Path, *, page_size: int | None = None):
        fx: dict[str, Any] = (
            fixture if isinstance(fixture, dict) else json.loads(Path(fixture).read_text())
        )
        self._fx = fx
        fixture = fx
        self._page_size = page_size or self.PAGE_SIZE
        slug = str(fixture.get("providerSlug", ""))
        if not is_mock_slug(slug):
            raise ValueError(
                "mock adapter slug must start with 'mock-' (separate provider namespace)"
            )
        profile = ExecutionProfile(fixture.get("executionProfile", "LOCAL_MOCK"))
        if profile is ExecutionProfile.PRODUCTION:
            raise ValueError("a mock adapter cannot run under the PRODUCTION profile")
        assets = tuple(AssetRef(**a) for a in fixture.get("supportedAssets", []))
        self._identity = AdapterIdentity(
            provider_slug=slug,
            execution_profile=profile,
            is_mock=True,
            partner_revenue=fixture.get("partnerRevenue", "SIMULATED"),
            source_chain_ids=tuple(int(c) for c in fixture.get("sourceChainIds", [])),
            supported_assets=assets,
        )
        self._assets_by_key = {a.key: a for a in assets}
        caps = fixture.get("capabilities", {})
        self._caps = Capabilities(**{k: Support(v) for k, v in caps.items()})
        self._claims: dict[str, ClaimResult] = {}
        self._control_changes: dict[str, ControlChangeResult] = {}
        self._calls = 0
        self._rate_limit_every = int(fixture.get("rateLimitEvery", 0))

    # ------------------------------------------------------------------ identity

    def identity(self) -> AdapterIdentity:
        return self._identity

    def capabilities(self) -> Capabilities:
        return self._caps

    # ------------------------------------------------------------------ helpers

    def _tick(self) -> None:
        self._calls += 1
        if self._rate_limit_every and self._calls % self._rate_limit_every == 0:
            raise RateLimited(retry_after_seconds=1)

    def _asset(self, raw: Any) -> AssetRef:
        if not isinstance(raw, dict):
            raise MissingUnit("amount without asset reference")
        for k in ("chainId", "decimals", "symbol"):
            if k not in raw:
                raise MissingUnit(f"asset missing {k}")
        chain_id = int(raw["chainId"])
        self._require_chain(chain_id)
        key = (chain_id, (raw.get("address") or "").lower(), int(raw["decimals"]))
        if key not in self._assets_by_key:
            raise UnsupportedChainError(
                f"asset {raw.get('symbol')} on chain {chain_id} not admitted"
            )
        return self._assets_by_key[key]

    def _money(self, raw: Any) -> Money:
        if not isinstance(raw, dict) or "amount" not in raw:
            raise MissingUnit("money must be {amount, asset}")
        amount = raw["amount"]
        if (
            isinstance(amount, float)
            or not isinstance(amount, (str, int))
            or isinstance(amount, bool)
        ):
            raise MissingUnit("amount must be an integer string of base units, never a float")
        return Money(amount=str(amount), asset=self._asset(raw.get("asset")))

    def _account_rows(self, section: str, account: AccountRef) -> list[dict[str, Any]]:
        self._require_account(account)
        rows = self._fx.get(section, {}).get(account.external_account_id)
        if rows is None:
            raise MalformedResponse(f"unknown account {account.external_account_id!r}")
        return list(rows)

    def _page(self, rows: list[Any], cursor: Cursor | None) -> tuple[list[Any], Cursor]:
        start = 0
        if cursor and cursor.token is not None:
            try:
                start = int(cursor.token.split(":")[1])
            except (IndexError, ValueError) as e:
                raise MalformedResponse(f"bad cursor {cursor.token!r}") from e
            if start > len(rows):
                raise MalformedResponse("cursor beyond end")
        end = min(start + self._page_size, len(rows))
        nxt = (
            Cursor(token=f"off:{end}", has_more=end < len(rows))
            if end < len(rows)
            else Cursor(token=f"off:{end}", has_more=False)
        )
        return rows[start:end], nxt

    def _observed(self) -> datetime:
        v = self._fx.get("observedAt")
        return _dt(v) if v else datetime.now(UTC)

    # ------------------------------------------------------------------ reads

    def list_assets(self, account: AccountRef, cursor: Cursor | None = None) -> Page[AssetListing]:
        self._require("list_assets")
        self._tick()
        rows, nxt = self._page(self._account_rows("assets", account), cursor)
        items = tuple(
            AssetListing(
                provider_slug=self._identity.provider_slug,
                observed_at=self._observed(),
                as_of=_dt(r["asOf"]),
                account=account,
                external_asset_id=str(r["externalAssetId"]),
                kind=AssetKind(r["kind"]),
                parent_external_id=r.get("parentExternalId"),
                attributes={str(k): str(v) for k, v in r.get("attributes", {}).items()},
            )
            for r in rows
        )
        return Page(items=items, next=nxt)

    def fetch_revenue(
        self, account: AccountRef, window: Window, cursor: Cursor | None = None
    ) -> Page[RevenueObservation]:
        self._require("fetch_revenue")
        self._tick()
        rows = [r for r in self._account_rows("revenue", account) if self._in_window(r, window)]
        rows, nxt = self._page(rows, cursor)
        items = []
        seen: dict[str, int] = {}
        for r in rows:
            try:
                as_of = _dt(r["asOf"])
                check_freshness(as_of, window)
                obs = RevenueObservation(
                    provider_slug=self._identity.provider_slug,
                    observed_at=self._observed(),
                    as_of=as_of,
                    account=account,
                    provider_event_ref=str(r["providerEventRef"]),
                    revision=int(r["revision"]),
                    period_start=_dt(r["periodStart"]),
                    period_end=_dt(r["periodEnd"]),
                    gross=self._money(r["gross"]),
                    deductions=self._money(r["deductions"]),
                    net=self._money(r["net"]),
                    earnings_provenance=EarningsProvenance(r["earningsProvenance"]),
                    settlement_ref=r.get("settlementRef"),
                )
            except KeyError as e:
                raise MalformedResponse(f"revenue row missing {e}") from e
            except ValueError as e:
                raise MalformedResponse(str(e)) from e
            prev = seen.get(obs.provider_event_ref)
            if prev is not None and obs.revision <= prev:
                raise MalformedResponse(
                    f"revision not monotonic for {obs.provider_event_ref}: {obs.revision} after {prev}"
                )
            seen[obs.provider_event_ref] = obs.revision
            items.append(obs)
        return Page(items=tuple(items), next=nxt)

    def fetch_settlements(
        self, account: AccountRef, window: Window, cursor: Cursor | None = None
    ) -> Page[SettlementObservation]:
        self._require("fetch_settlements")
        self._tick()
        rows = [r for r in self._account_rows("settlements", account) if self._in_window(r, window)]
        rows, nxt = self._page(rows, cursor)
        items = []
        for r in rows:
            try:
                as_of = _dt(r["asOf"])
                check_freshness(as_of, window)
                items.append(
                    SettlementObservation(
                        provider_slug=self._identity.provider_slug,
                        observed_at=self._observed(),
                        as_of=as_of,
                        account=account,
                        settlement_ref=str(r["settlementRef"]),
                        revision=int(r["revision"]),
                        amount=self._money(r["amount"]),
                        payer=r.get("payer"),
                        payee=r.get("payee"),
                        paid_at=_dt(r["paidAt"]) if r.get("paidAt") else None,
                        status=r["status"],
                        tx_ref=r.get("txRef"),
                    )
                )
            except KeyError as e:
                raise MalformedResponse(f"settlement row missing {e}") from e
            except ValueError as e:
                raise MalformedResponse(str(e)) from e
        return Page(items=tuple(items), next=nxt)

    def get_control_state(self, account: AccountRef) -> ControlStateObservation:
        self._require("get_control_state")
        self._tick()
        self._require_account(account)
        r = self._fx.get("controlState", {}).get(account.external_account_id)
        if r is None:
            raise MalformedResponse(f"unknown account {account.external_account_id!r}")
        if r.get("receiverChainId") is not None:
            self._require_chain(int(r["receiverChainId"]))
        return ControlStateObservation(
            provider_slug=self._identity.provider_slug,
            observed_at=self._observed(),
            as_of=_dt(r["asOf"]),
            account=account,
            receiver=r.get("receiver"),
            receiver_chain_id=r.get("receiverChainId"),
            borrower_can_change_receiver=r.get("borrowerCanChangeReceiver"),
            observed_grade=r.get("observedGrade", "E0"),
        )

    # ------------------------------------------------------------------ writes (UNSUPPORTED unless enabled)

    def claim_revenue(self, request: ClaimRequest) -> ClaimResult:
        self._require("claim_revenue")
        self._tick()
        self._require_account(request.account)
        if request.idempotency_key in self._claims:
            return self._claims[request.idempotency_key]
        res = ClaimResult(
            provider_slug=self._identity.provider_slug,
            observed_at=self._observed(),
            as_of=self._observed(),
            account=request.account,
            idempotency_key=request.idempotency_key,
            accepted=True,
            provider_ref=f"mock-claim-{len(self._claims) + 1}",
        )
        self._claims[request.idempotency_key] = res
        return res

    def request_control_change(self, request: ControlChangeRequest) -> ControlChangeResult:
        self._require("request_control_change")
        self._tick()
        self._require_account(request.account)
        self._require_chain(request.new_receiver_chain_id)
        if request.idempotency_key in self._control_changes:
            return self._control_changes[request.idempotency_key]
        res = ControlChangeResult(
            provider_slug=self._identity.provider_slug,
            observed_at=self._observed(),
            as_of=self._observed(),
            account=request.account,
            idempotency_key=request.idempotency_key,
            accepted=True,
            provider_ref=f"mock-control-{len(self._control_changes) + 1}",
        )
        self._control_changes[request.idempotency_key] = res
        return res

    # ------------------------------------------------------------------ internals

    @staticmethod
    def _in_window(r: dict[str, Any], window: Window) -> bool:
        try:
            as_of = _dt(r["asOf"])
        except KeyError as e:
            raise MalformedResponse("row missing asOf") from e
        return window.start <= as_of <= window.end


__all__ = ["MockProviderAdapter", "UnsupportedOperation"]
