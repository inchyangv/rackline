"""Observation failure never defaults debt, spends reserves, or blocks repayment."""

from datetime import timedelta

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from hashcredit_gpu.db.ledgers import ExceptionCase, Outbox
from hashcredit_gpu.db.models import ControlAgreement, Facility
from hashcredit_gpu.monitoring.service import Finding, assess_facility, record_findings

from .test_event_ledger import NOW, seed_facility, ulid
from .test_schema import ULID_C, ULID_D


@pytest.fixture
def db(conn, migrated_db_url):
    seed_facility(conn, principal=1000)
    conn.commit()
    engine = create_engine(migrated_db_url)
    yield engine
    engine.dispose()


def test_proof_delay_recovery_is_idempotent_without_default_or_debt_mutation(db):
    finding = (Finding("NATIVE_PROOF_PENDING", False, "OBSERVABILITY"),)
    with Session(db) as s, s.begin():
        first = record_findings(s, ULID_D, finding, now=NOW)
        assert record_findings(s, ULID_D, finding, now=NOW) == first
        assert s.get(Facility, ULID_D).state == "ACTIVE"
        assert s.get(Facility, ULID_D).principal == 1000
    with Session(db) as s, s.begin():
        record_findings(s, ULID_D, (), now=NOW + timedelta(seconds=60))
        case = s.get(ExceptionCase, first[0])
        assert case.resolved_at is not None
        assert case.detail["repaymentPermitted"] is True
        assert case.detail["defaultApplied"] is False
        assert s.scalar(select(func.count()).select_from(Outbox)) == 2


def test_control_expiry_requires_review_and_not_automatic_shutdown(db):
    with Session(db) as s, s.begin():
        agreement = s.get(ControlAgreement, ULID_C)
        agreement.effective_from = NOW - timedelta(days=30)
        agreement.effective_to = NOW - timedelta(seconds=1)
        findings = assess_facility(s, ULID_D, now=NOW, deployment_id=ulid("missing"))
        assert {f.code for f in findings} >= {"CONTROL_NOT_CURRENT", "PROJECTION_STALE"}
        record_findings(s, ULID_D, findings, now=NOW)
        assert s.get(Facility, ULID_D).state == "ACTIVE"
        assert s.get(Facility, ULID_D).principal == 1000


def test_observation_recovery_does_not_auto_resolve_control_breach(db):
    with Session(db) as s, s.begin():
        ids = record_findings(
            s, ULID_D, (Finding("CONTROL_RECEIVER_CHANGED", True, "CONTROL"),), now=NOW
        )
        record_findings(s, ULID_D, (), now=NOW + timedelta(seconds=60))
        assert s.get(ExceptionCase, ids[0]).resolved_at is None
