"""GPU-023 service checkpoints on real PostgreSQL; all business inputs are LOCAL fixtures."""

from dataclasses import replace
from datetime import timedelta

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from hashcredit_gpu.db.ledgers import (
    ExceptionCase,
    Outbox,
    RawSourceObservation,
    Receivable,
    ReceivableRevision,
)
from hashcredit_gpu.db.models import CreditDecision, Facility, Provider
from hashcredit_gpu.domain import AssetRef
from hashcredit_gpu.receivables import (
    ObligationInput,
    RevenueKind,
    apply_revision,
    evaluate_receivable,
    record_obligation,
)
from hashcredit_gpu.receivables.service import ReceivableError

from .test_event_ledger import (
    MANIFEST,
    NOW,
    USDC,
    consumption_params,
    consumption_sql,
    h32,
    pipeline_to_accepted,
    seed_facility,
    ulid,
)
from .test_schema import ULID_D, run

ACCOUNT = "mockdepin-testonly:acct-A"
ASSET = AssetRef(chain_id=11155111, address=USDC, symbol="USDC", decimals=6)


@pytest.fixture
def db(conn, migrated_db_url):
    seed_facility(conn, principal=1000)
    engine = create_engine(migrated_db_url)
    yield engine
    engine.dispose()


def observe(session, tag="obs1", origin="API"):
    oid = ulid(tag)
    session.add(
        RawSourceObservation(
            observation_id=oid,
            provider_id="mockdepin-testonly",
            origin=origin,
            schema_id="gpu023-local",
            schema_revision=1,
            payload_hash=h32(tag),
            payload_ref="blob://fixtures/gpu023",
            trust="ASSERTED",
            observed_at=NOW,
        )
    )
    session.flush()
    return oid


def command(observation_id, **overrides):
    return replace(
        ObligationInput(
            receivable_id=ulid("recv1"),
            provider_account_id=ACCOUNT,
            obligation_ref="invoice-A",
            observation_id=observation_id,
            asset=ASSET,
            gross=1100,
            net=1000,
            paid_amount=0,
            revision=1,
            kind=RevenueKind.OPERATING_RECEIVABLE,
            period_from=NOW - timedelta(days=30),
            period_to=NOW - timedelta(days=1),
            due_at=NOW + timedelta(days=15),
            execution_profile="NATIVE_TESTNET",
        ),
        **overrides,
    )


def record(session, **overrides):
    cmd = command(observe(session), **overrides)
    return record_obligation(session, cmd, as_of=NOW)


def test_three_observers_one_economic_receivable_with_all_raw_links(db):
    with Session(db) as s, s.begin():
        first = record(s)
        for tag, origin in [("obs2", "MANUAL"), ("obs3", "CHAIN")]:
            result = record_obligation(s, command(observe(s, tag, origin)), as_of=NOW)
            assert result.reason == "DUPLICATE_OBSERVATION"
        assert s.scalar(select(func.count()).select_from(Receivable)) == 1
        assert s.scalar(select(func.count()).select_from(ReceivableRevision)) == 1
        assert s.scalar(select(func.count()).select_from(Outbox)) == 3
        assert first.created
        assert s.get(Facility, ULID_D).principal == 1000


@pytest.mark.parametrize("kind", [k for k in RevenueKind if k != RevenueKind.OPERATING_RECEIVABLE])
def test_non_operating_money_never_creates_a_receivable(db, kind):
    with Session(db) as s, s.begin():
        result = record(s, kind=kind)
        assert result.receivable_id is None
        assert s.scalar(select(func.count()).select_from(Receivable)) == 0
        assert s.scalar(select(func.count()).select_from(ExceptionCase)) == 1


def test_future_utilization_or_service_period_cannot_create_credit(db):
    with Session(db) as s, s.begin():
        result = record(s, period_to=NOW + timedelta(days=1))
        assert result.reason == "FUTURE_REVENUE"
        assert s.scalar(select(func.count()).select_from(Receivable)) == 0


@pytest.mark.parametrize("bad", [True, 1.5, "1000", -1])
def test_money_rejects_coercion_and_negative_values(db, bad):
    with Session(db) as s, s.begin(), pytest.raises(ReceivableError):
        record(s, net=bad)


def test_conflicting_same_revision_and_overlapping_periods_are_quarantined(db):
    with Session(db) as s, s.begin():
        first = record(s)
        conflict = record_obligation(s, command(observe(s, "obs2"), net=900), as_of=NOW)
        assert conflict.reason == "AMOUNT_OR_BINDING_CONFLICT"
        assert s.get(Receivable, first.receivable_id).net == 1000
        second = record_obligation(
            s,
            command(observe(s, "obs3"), receivable_id=ulid("recv2"), obligation_ref="invoice-B"),
            as_of=NOW,
        )
        for rid in (first.receivable_id, second.receivable_id):
            result = evaluate_receivable(s, rid, ULID_D, as_of=NOW)
            assert "RECONCILIATION_EXCEPTION" in result.reasons
            assert result.eligible_source_units == 0


def test_delta_does_not_double_deduct_fees_or_reduce_debt_and_revokes_decision(db):
    with Session(db) as s, s.begin():
        result = record(s)
        row = s.get(Receivable, result.receivable_id)
        row.facility_id = ULID_D
        s.add(
            CreditDecision(
                credit_decision_id=ulid("decision"),
                facility_id=ULID_D,
                decided_by="system",
                policy_version_id="pol-test",
                inputs={},
                limit_amount=500,
                decided_at=NOW,
                valid_until=NOW + timedelta(days=1),
                status="APPROVED",
                execution_profile="NATIVE_TESTNET",
            )
        )
        apply_revision(
            s,
            receivable_id=row.receivable_id,
            observation_id=observe(s, "obs2"),
            revision=2,
            kind="CORRECTION",
            delta=-100,
        )
        assert (row.gross, row.net, row.unpaid_amount) == (1100, 900, 900)
        assert s.get(Facility, ULID_D).principal == 1000
        assert s.get(CreditDecision, ulid("decision")).status == "REVOKED"
        assert row.checkpoint_consumption_id is None


def test_partial_payout_cancellation_and_full_payment_never_repay_facility(db):
    with Session(db) as s, s.begin():
        rid = record(s).receivable_id
        for revision, kind, delta, unpaid in [
            (2, "PAYOUT", 400, 600),
            (3, "CANCELLATION", 100, 700),
            (4, "PAYOUT", 700, 0),
        ]:
            apply_revision(
                s,
                receivable_id=rid,
                observation_id=observe(s, f"obs{revision}"),
                revision=revision,
                kind=kind,
                delta=delta,
            )
            assert s.get(Receivable, rid).unpaid_amount == unpaid
            assert s.get(Facility, ULID_D).principal == 1000
        assert s.get(Receivable, rid).state == "PAID"
        assert (
            "NO_ELIGIBLE_UNPAID_BALANCE" in evaluate_receivable(s, rid, ULID_D, as_of=NOW).reasons
        )


def test_duplicate_and_out_of_order_revision_do_not_change_balance(db):
    with Session(db) as s, s.begin():
        rid = record(s).receivable_id
        oid = observe(s, "obs2")
        apply_revision(
            s, receivable_id=rid, observation_id=oid, revision=2, kind="PAYOUT", delta=100
        )
        duplicate = apply_revision(
            s, receivable_id=rid, observation_id=oid, revision=2, kind="PAYOUT", delta=100
        )
        assert duplicate.reason == "DUPLICATE_REVISION"
        skipped = apply_revision(
            s,
            receivable_id=rid,
            observation_id=observe(s, "obs3"),
            revision=4,
            kind="CORRECTION",
            delta=-50,
        )
        assert skipped.reason == "REVISION_OUT_OF_ORDER"
        assert (s.get(Receivable, rid).revision, s.get(Receivable, rid).unpaid_amount) == (2, 900)


def test_invalid_reversal_is_quarantined_not_silently_clamped(db):
    with Session(db) as s, s.begin():
        rid = record(s).receivable_id
        result = apply_revision(
            s,
            receivable_id=rid,
            observation_id=observe(s, "obs2"),
            revision=2,
            kind="CANCELLATION",
            delta=1,
        )
        assert result.reason == "REVISION_BALANCE_CONFLICT"
        assert s.get(Receivable, rid).unpaid_amount == 1000


def test_same_raw_payout_cannot_be_replayed_as_a_new_revision(db):
    with Session(db) as s, s.begin():
        rid = record(s).receivable_id
        oid = observe(s, "obs2")
        apply_revision(
            s, receivable_id=rid, observation_id=oid, revision=2, kind="PAYOUT", delta=100
        )
        replay = apply_revision(
            s, receivable_id=rid, observation_id=oid, revision=3, kind="PAYOUT", delta=100
        )
        assert replay.reason == "OBSERVATION_ALREADY_APPLIED"
        assert s.get(Receivable, rid).unpaid_amount == 900


def test_even_native_checkpoint_row_cannot_fabricate_business_or_current_unpaid_binding(db, conn):
    _, _, vid = pipeline_to_accepted(conn)
    cid = ulid("checkpoint")
    run(
        conn,
        consumption_sql(),
        consumption_params(
            cid,
            h32("cp-source"),
            "mockdepin-testonly/acct-A/OBLIGATION/checkpoint",
            vid,
            meaning="CHECKPOINT",
        ),
    )
    with Session(db) as s, s.begin():
        rid = record(s).receivable_id
        row = s.get(Receivable, rid)
        row.facility_id, row.checkpoint_consumption_id, row.checkpoint_seq = ULID_D, cid, 1
        provider = s.get(Provider, "mockdepin-testonly")
        provider.manifest_hash = MANIFEST
        provider.capabilities = {"source_support": "SUPPORTED"}
        s.flush()
        report = evaluate_receivable(s, rid, ULID_D, as_of=NOW)
        assert not report.eligible and report.eligible_source_units == 0
        assert "NATIVE_CHECKPOINT_MISSING_OR_INVALID" not in report.reasons
        assert "DECODED_BUSINESS_BINDING_NOT_IMPLEMENTED" in report.reasons
        assert "CURRENT_UNPAID_PROTECTION_NOT_IMPLEMENTED" in report.reasons
        expired = evaluate_receivable(s, rid, ULID_D, as_of=NOW + timedelta(days=8))
        assert "NATIVE_CHECKPOINT_EXPIRED" in expired.reasons


def test_paid_historical_obligation_remains_ineligible_and_rollback_is_atomic(db):
    with Session(db) as s:
        with pytest.raises(RuntimeError), s.begin():
            rid = record(s, paid_amount=1000).receivable_id
            report = evaluate_receivable(s, rid, ULID_D, as_of=NOW)
            assert "NO_ELIGIBLE_UNPAID_BALANCE" in report.reasons
            raise RuntimeError("crash before commit")
        assert s.scalar(select(func.count()).select_from(Receivable)) == 0
        assert s.scalar(select(func.count()).select_from(Outbox)) == 0
