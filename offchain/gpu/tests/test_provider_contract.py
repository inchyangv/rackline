"""
GPU-019: ProviderAdapter contract tests. Parametrized over adapter factories so real adapters (GPU-020/021)
plug into the same suite later. Today only the LOCAL mock exists. No PostgreSQL needed.
"""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from hashcredit_gpu.domain import NativeStatus, Trust, VerificationMethod
from hashcredit_gpu.providers import (
    AccountRef,
    Capabilities,
    ClaimRequest,
    ControlChangeRequest,
    Cursor,
    ExpiredData,
    MalformedResponse,
    MissingUnit,
    MockProviderAdapter,
    NotNativeCapable,
    NotProductionAdmissible,
    ProviderAdapter,
    RateLimited,
    RevenueObservation,
    Support,
    UnsupportedChainError,
    UnsupportedOperation,
    Window,
    assert_native_capable,
    assert_production_admissible,
)

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "providers" / "mockdepin-testonly.json"
ACCT = AccountRef(provider_slug="mockdepin-testonly", external_account_id="acct-A")
WINDOW = Window(
    start=datetime(2026, 8, 1, tzinfo=UTC),
    end=datetime(2026, 9, 30, tzinfo=UTC),
    max_age_seconds=30 * 86_400,
    as_of=datetime(2026, 9, 14, 12, tzinfo=UTC),
)


def load_fixture() -> dict:
    return json.loads(FIXTURE.read_text())


def make_mock(**overrides) -> MockProviderAdapter:
    fx = load_fixture()
    fx.update(overrides)
    return MockProviderAdapter(fx)


# Real adapters register here once GPU-020/021 exist; each factory must return a fresh instance.
ADAPTER_FACTORIES = {"mock": make_mock}


@pytest.fixture(params=list(ADAPTER_FACTORIES), ids=list(ADAPTER_FACTORIES))
def adapter(request) -> ProviderAdapter:
    return ADAPTER_FACTORIES[request.param]()


# ------------------------------------------------------------------ contract: identity / capabilities


def test_identity_and_namespace(adapter: ProviderAdapter):
    ident = adapter.identity()
    assert ident.provider_slug == ACCT.provider_slug
    assert ident.source_chain_ids == (11155111,)
    caps = adapter.capabilities()
    assert isinstance(caps, Capabilities)
    # read and write are independent: reads on, claim off, control change unknown
    assert caps.fetch_revenue is Support.SUPPORTED
    assert caps.claim_revenue is Support.UNSUPPORTED
    assert caps.request_control_change is Support.UNKNOWN
    assert not Support.UNKNOWN.usable  # unknown == unsupported for callers


def test_other_namespace_account_rejected(adapter: ProviderAdapter):
    foreign = AccountRef(provider_slug="aethir", external_account_id="acct-A")
    with pytest.raises(UnsupportedOperation):
        adapter.list_assets(foreign)


# ------------------------------------------------------------------ contract: pagination / cursors


def test_pagination_cursor_is_stable_and_complete(adapter: ProviderAdapter):
    seen: list[str] = []
    cursor: Cursor | None = None
    pages = 0
    while True:
        page = adapter.list_assets(ACCT, cursor)
        pages += 1
        seen.extend(a.external_asset_id for a in page.items)
        if not page.next.has_more:
            break
        cursor = page.next
        assert pages < 10, "cursor never terminates"
    assert seen == ["gpu-0001", "gpu-0001-mig-1", "gpu-0002", "grp-1", "gpu-0003"]
    assert pages == 3
    # replaying a cursor yields the same page (stable)
    first = adapter.list_assets(ACCT, None)
    again = adapter.list_assets(ACCT, None)
    assert [a.external_asset_id for a in first.items] == [a.external_asset_id for a in again.items]
    second_a = adapter.list_assets(ACCT, first.next)
    second_b = adapter.list_assets(ACCT, first.next)
    assert second_a.items == second_b.items


def test_bad_cursor_rejected(adapter: ProviderAdapter):
    with pytest.raises(MalformedResponse):
        adapter.list_assets(ACCT, Cursor(token="garbage"))
    with pytest.raises(MalformedResponse):
        adapter.list_assets(ACCT, Cursor(token="off:999"))


# ------------------------------------------------------------------ contract: observations are assertions only


def test_revenue_observations_are_offchain_assertions_with_exact_money(adapter: ProviderAdapter):
    items = []
    cursor = None
    while True:
        page = adapter.fetch_revenue(ACCT, WINDOW, cursor)
        items.extend(page.items)
        if not page.next.has_more:
            break
        cursor = page.next
    assert len(items) == 3
    for o in items:
        assert o.provenance == "PROVIDER_API"
        assert o.trust is Trust.ASSERTED
        assert o.verification_method is VerificationMethod.OFFCHAIN_ASSERTION
        assert o.native_status is NativeStatus.NOT_REQUIRED
        assert o.net.units == o.gross.units - o.deductions.units
        assert isinstance(o.net.amount, str)
    revs = [(o.provider_event_ref, o.revision, o.net.units) for o in items]
    assert revs == [
        ("inv-2026-08-A", 1, 12_000_000_000),
        ("inv-2026-08-B", 1, 9_000_000_000),
        ("inv-2026-08-A", 2, 11_000_000_000),
    ]


def test_observation_trust_fields_cannot_be_upgraded():
    base = make_mock().fetch_revenue(ACCT, WINDOW).items[0]
    for field, value in (
        ("trust", Trust.PROVEN),
        ("verification_method", VerificationMethod.ATTESTCOIN_NATIVE),
        ("native_status", NativeStatus.NATIVE_ACCEPTED),
        ("provenance", "SOURCE_EVENT_NATIVE"),
    ):
        with pytest.raises(ValidationError):
            RevenueObservation(**{**base.model_dump(), field: value})


def test_control_state_cannot_report_e2(adapter: ProviderAdapter):
    st = adapter.get_control_state(ACCT)
    assert st.observed_grade in ("E0", "E1")
    assert st.borrower_can_change_receiver is True  # the mock is honest: not E2
    fx = load_fixture()
    fx["controlState"]["acct-A"]["observedGrade"] = "E2"
    with pytest.raises(ValidationError):
        MockProviderAdapter(fx).get_control_state(ACCT)


# ------------------------------------------------------------------ contract: writes


def test_unsupported_write_raises(adapter: ProviderAdapter):
    with pytest.raises(UnsupportedOperation):
        adapter.claim_revenue(ClaimRequest(account=ACCT, idempotency_key="c-1"))
    with pytest.raises(UnsupportedOperation):  # UNKNOWN == unsupported
        adapter.request_control_change(
            ControlChangeRequest(
                account=ACCT,
                new_receiver="0x" + "e1" * 20,
                new_receiver_chain_id=11155111,
                idempotency_key="k-1",
            )
        )


def test_enabled_write_is_idempotent_and_never_cash_or_control():
    fx = load_fixture()
    fx["capabilities"]["claim_revenue"] = "SUPPORTED"
    fx["capabilities"]["request_control_change"] = "SUPPORTED"
    a = MockProviderAdapter(fx)
    r1 = a.claim_revenue(ClaimRequest(account=ACCT, idempotency_key="c-1"))
    r2 = a.claim_revenue(ClaimRequest(account=ACCT, idempotency_key="c-1"))
    assert r1 == r2 and r1.accepted and r1.cash_state == "NONE"
    c = a.request_control_change(
        ControlChangeRequest(
            account=ACCT,
            new_receiver="0x" + "e1" * 20,
            new_receiver_chain_id=11155111,
            idempotency_key="k-1",
        )
    )
    assert c.accepted and c.control_grade_effect == "NONE"
    with pytest.raises(UnsupportedChainError):
        a.request_control_change(
            ControlChangeRequest(
                account=ACCT,
                new_receiver="0x" + "e1" * 20,
                new_receiver_chain_id=42161,
                idempotency_key="k-2",
            )
        )


# ------------------------------------------------------------------ contract: freshness / revision / malformed


def test_expired_data_rejected(adapter: ProviderAdapter):
    stale = Window(start=WINDOW.start, end=WINDOW.end, max_age_seconds=3600, as_of=WINDOW.as_of)
    with pytest.raises(ExpiredData):
        adapter.fetch_revenue(ACCT, stale)


def test_window_filters_by_as_of(adapter: ProviderAdapter):
    narrow = Window(
        start=datetime(2026, 9, 6, tzinfo=UTC),
        end=WINDOW.end,
        max_age_seconds=WINDOW.max_age_seconds,
        as_of=WINDOW.as_of,
    )
    page = adapter.fetch_revenue(ACCT, narrow)
    assert [(o.provider_event_ref, o.revision) for o in page.items] == [("inv-2026-08-A", 2)]


def test_revision_must_be_monotonic_per_ref():
    fx = load_fixture()
    rows = fx["revenue"]["acct-A"]
    rows[2]["revision"] = 1  # a second revision-1 for inv-A after revision-1
    fx["revenue"]["acct-A"] = [rows[0], rows[2]]
    with pytest.raises(MalformedResponse, match="revision not monotonic"):
        MockProviderAdapter(fx).fetch_revenue(ACCT, WINDOW)
    fx2 = load_fixture()
    fx2["revenue"]["acct-A"][0]["revision"] = 0
    with pytest.raises(MalformedResponse):
        MockProviderAdapter(fx2).fetch_revenue(ACCT, WINDOW)


@pytest.mark.parametrize(
    "mutate, exc",
    [
        (lambda r: r["net"].pop("asset"), MissingUnit),
        (lambda r: r["net"]["asset"].pop("decimals"), MissingUnit),
        (lambda r: r["net"].__setitem__("amount", 12000.5), MissingUnit),
        (lambda r: r["net"]["asset"].__setitem__("chainId", 42161), UnsupportedChainError),
        (lambda r: r.pop("periodEnd"), MalformedResponse),
        (
            lambda r: r["net"].__setitem__("amount", "1"),
            MalformedResponse,
        ),  # net != gross - deductions
        (
            lambda r: r.__setitem__("asOf", "2026-09-05T00:00:00"),
            MalformedResponse,
        ),  # naive timestamp
    ],
    ids=[
        "missing-asset",
        "missing-decimals",
        "float-amount",
        "unknown-chain",
        "missing-field",
        "inconsistent-net",
        "naive-time",
    ],
)
def test_malformed_response_never_succeeds(mutate, exc):
    fx = load_fixture()
    row = fx["revenue"]["acct-A"][0]
    mutate(row)
    with pytest.raises(exc):
        MockProviderAdapter(fx).fetch_revenue(ACCT, WINDOW)


def test_settlement_tx_ref_is_a_hint_only(adapter: ProviderAdapter):
    page = adapter.fetch_settlements(ACCT, WINDOW)
    s = page.items[0]
    assert s.status == "PAID" and s.native_status is NativeStatus.NOT_REQUIRED
    assert (
        s.trust is Trust.ASSERTED
    )  # "PAID" per provider is not cash at destination nor a proven log


def test_rate_limit_is_typed():
    a = make_mock(rateLimitEvery=2)
    a.list_assets(ACCT)
    with pytest.raises(RateLimited) as ei:
        a.list_assets(ACCT)
    assert ei.value.retry_after_seconds == 1


# ------------------------------------------------------------------ R2: mock / testnet / unsupported source are never production


def test_mock_adapter_is_local_and_separately_namespaced(adapter: ProviderAdapter):
    ident = adapter.identity()
    assert ident.is_mock and ident.provider_slug.startswith("mockdepin-testonly")
    assert ident.execution_profile.value == "LOCAL_MOCK"
    assert ident.partner_revenue == "SIMULATED"


def test_mock_cannot_claim_production_profile_or_real_slug():
    with pytest.raises(ValueError):
        make_mock(executionProfile="PRODUCTION")
    with pytest.raises(ValueError):
        make_mock(providerSlug="aethir")


def test_mock_to_production_path_refused(adapter: ProviderAdapter):
    with pytest.raises(NotProductionAdmissible, match="mock adapter"):
        assert_production_admissible(adapter)


def test_api_healthy_but_official_source_unsupported_is_refused():
    fx = load_fixture()
    fx["capabilities"]["source_support"] = "UNSUPPORTED"
    a = MockProviderAdapter(fx)
    assert a.capabilities().fetch_revenue is Support.SUPPORTED  # business API fine
    assert len(a.fetch_revenue(ACCT, WINDOW).items) > 0
    with pytest.raises(NotProductionAdmissible, match="official source support UNSUPPORTED"):
        assert_production_admissible(a)
    fx["capabilities"]["source_support"] = "UNKNOWN"
    with pytest.raises(NotProductionAdmissible, match="UNKNOWN"):
        assert_production_admissible(MockProviderAdapter(fx))


def test_genuine_testnet_profile_with_simulated_revenue_is_not_production():
    a = make_mock(executionProfile="NATIVE_TESTNET", partnerRevenue="SIMULATED")
    assert a.identity().execution_profile.value == "NATIVE_TESTNET"
    with pytest.raises(NotProductionAdmissible) as ei:
        assert_production_admissible(a)
    msg = str(ei.value)
    assert "execution profile NATIVE_TESTNET" in msg and "partner revenue SIMULATED" in msg


def test_provider_adapter_is_never_native_capable(adapter: ProviderAdapter):
    with pytest.raises(NotNativeCapable):
        assert_native_capable(adapter)


class _RealLookingAdapter(MockProviderAdapter):
    """Only for the admissibility matrix: pretend every business-side flag is production-grade."""

    def identity(self):
        return self._identity.model_copy(
            update={
                "is_mock": False,
                "execution_profile": "PRODUCTION",
                "partner_revenue": "REAL",
                "provider_slug": "partner-x",
            }
        )


def test_admissibility_needs_every_flag_and_still_not_native():
    fx = load_fixture()
    a = _RealLookingAdapter(fx)  # slug is still mock-derived → refused even with production flags
    with pytest.raises(NotProductionAdmissible):
        assert_production_admissible(a)
    with pytest.raises(NotNativeCapable):
        assert_native_capable(a)


def test_fixture_is_deidentified():
    text = FIXTURE.read_text()
    fx = json.loads(text)
    assert fx["kind"] == "DEIDENTIFIED_PROVIDER_FIXTURE"
    for word in ("aethir", "gpu.net", "@", "sk_", "Bearer"):
        assert word not in text.lower(), word

    # no float money anywhere
    def walk(v):
        if isinstance(v, float):
            raise TypeError("float amount in fixture")
        if isinstance(v, dict):
            for x in v.values():
                walk(x)
        if isinstance(v, list):
            for x in v:
                walk(x)

    walk(fx)
    assert copy.deepcopy(fx) == fx
