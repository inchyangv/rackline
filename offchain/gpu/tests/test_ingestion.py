"""Durable cursor/page/outbox recovery and webhook authenticity on real PostgreSQL."""

import json

import pytest
from sqlalchemy import create_engine, text

from hashcredit_gpu.ingestion import (
    Collector,
    FileRawStore,
    IngestionConfig,
    IngestionCrash,
    WebhookError,
    WebhookReceiver,
    sign_webhook,
)
from hashcredit_gpu.ingestion.cursors import CursorStore
from hashcredit_gpu.ingestion.proof_candidates import ProofEnv
from hashcredit_gpu.providers import MockProviderAdapter

from .test_event_ledger import MANIFEST
from .test_provider_contract import ACCT, WINDOW, load_fixture
from .test_schema import seed_base


@pytest.fixture
def setup(conn, migrated_db_url, tmp_path):
    seed_base(conn)
    conn.commit()
    engine = create_engine(migrated_db_url)
    adapter = MockProviderAdapter(load_fixture())
    cfg = IngestionConfig(
        "mockdepin-testonly",
        ProofEnv("cc3-testnet", 1, 11155111, MANIFEST, "0.18.0", "NATIVE_TESTNET"),
        max_window_seconds=100 * 86400,
        overlap_seconds=0,
    )
    yield engine, adapter, cfg, FileRawStore(tmp_path)
    engine.dispose()


def collector(setup, **kwargs):
    return Collector(*setup, clock=lambda: WINDOW.as_of, **kwargs)


def counts(engine):
    with engine.connect() as c:
        return {
            name: c.execute(text(f"SELECT count(*) FROM {name}")).scalar()
            for name in ("raw_source_observations", "outbox", "proof_requests", "jobs")
        }


def crash(_):
    raise IngestionCrash("simulated crash")


def test_crash_before_commit_refetches_without_skipping_page(setup):
    c = collector(setup, fault_before_commit=crash)
    with pytest.raises(IngestionCrash):
        c.poll(ACCT, "revenue", initial_start=WINDOW.start)
    assert counts(setup[0])["raw_source_observations"] == 0
    result = collector(setup).poll(ACCT, "revenue")
    assert result.stored == 3 and result.pages == 2
    with setup[0].connect() as cx:
        st = CursorStore.load(cx, "mockdepin-testonly", c.stream_name("revenue", ACCT))
        assert st.high_water == WINDOW.as_of and st.page_token is None


def test_crash_after_commit_resumes_exact_page_and_backfill_dedups(setup):
    c = collector(setup, fault_after_commit=crash)
    with pytest.raises(IngestionCrash):
        c.poll(ACCT, "revenue", initial_start=WINDOW.start)
    assert counts(setup[0])["raw_source_observations"] == 2
    result = collector(setup).poll(ACCT, "revenue")
    assert result.stored == 1
    result = collector(setup).collect_window(
        ACCT, "revenue", WINDOW.start, WINDOW.as_of, tag="historical"
    )
    assert result.stored == 0 and result.duplicates == 3
    assert counts(setup[0])["raw_source_observations"] == 3


def test_settlement_webhook_signature_replay_and_no_native_acceptance(setup):
    c = collector(setup)
    observation = setup[1].fetch_settlements(ACCT, WINDOW).items[0]
    body = json.dumps(
        {"kind": "settlement", "observation": observation.model_dump(mode="json")}
    ).encode()
    secret = b"unit-test-provider-webhook-secret"
    timestamp = int(WINDOW.as_of.timestamp())
    headers = {
        "X-Rackline-Timestamp": str(timestamp),
        "X-Rackline-Signature": sign_webhook(secret, timestamp, body),
    }
    receiver = WebhookReceiver(c, secret)
    first = receiver.receive(headers, body, now=WINDOW.as_of)
    second = receiver.receive(headers, body, now=WINDOW.as_of)
    assert first.stored and not second.stored
    assert first.observation_id == second.observation_id
    with pytest.raises(WebhookError, match="BAD_SIGNATURE"):
        receiver.receive({**headers, "X-Rackline-Signature": "bad"}, body, now=WINDOW.as_of)
    with setup[0].connect() as cx:
        assert set(cx.execute(text("SELECT status FROM proof_requests")).scalars()) <= {"OBSERVED"}
        assert cx.execute(text("SELECT count(*) FROM native_verifications")).scalar() == 0


def test_durable_blob_detects_corruption_and_missing_initial_cursor(setup):
    from hashcredit_gpu.ingestion import MissingCursorError
    from hashcredit_gpu.ingestion.collector import payload_hash_of

    store = setup[3]
    digest = payload_hash_of(b"raw")
    ref = store.put(digest, b"raw")
    assert store.put(digest, b"raw") == ref
    with pytest.raises(ValueError, match="match hash"):
        store.put(digest, b"different")
    with pytest.raises(MissingCursorError):
        collector(setup).poll(ACCT, "revenue")
