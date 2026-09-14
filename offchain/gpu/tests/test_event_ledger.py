"""
GPU-016 ledger tests on real PostgreSQL: proof-pipeline state independence, evidence consumption
uniqueness under concurrency, revision monotonicity, allocation sums, audit immutability, cash ownership
split, job leases, EVM nonce index, production/mock isolation, and a backup/restore that preserves totals.
"""

from __future__ import annotations

import subprocess
import threading
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import psycopg2
import pytest
from psycopg2 import errors

from hashcredit_gpu.db.cli import current, downgrade, schema_diff, upgrade
from hashcredit_gpu.db.ledgers import LEDGER_TRIGGER_NAMES

from .conftest import _dsn
from .test_migrations import HEAD
from .test_schema import ADDR1, ADDR2, HASH1, MUSDT, ULID_B, ULID_C, ULID_D, insert_e2_agreement, insert_facility, run, seed_base

NOW = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)
MANIFEST = "sha256:" + "2b" * 32
USDC = "0x" + "e5" * 20
VERIFIER = "0x" + "f6" * 20
CONSUMER = "0x" + "a7" * 20


def ulid(tag: str) -> str:
    """Deterministic Crockford-base32 ULID from a tag (no I/L/O/U; hex of the tag keeps it readable)."""
    return ("01J" + tag.encode().hex().upper()).ljust(26, "0")[:26]


def h32(tag: str) -> str:
    return "0x" + (tag.encode().hex() * 32)[:64]


# ---------------------------------------------------------------- seeding helpers


def seed_facility(conn, fid=ULID_D, principal=0):
    seed_base(conn)
    insert_e2_agreement(conn, ULID_C, 1)
    insert_facility(conn, fid, profile="NATIVE_TESTNET", state="ACTIVE", control=ULID_C, funded_version=1, principal=principal)


def insert_proof_request(conn, rid, tx, status="OBSERVED", profile="NATIVE_TESTNET"):
    run(
        conn,
        "INSERT INTO proof_requests (proof_request_id, env_id, chain_key, tx_hash, provider_id, execution_profile, manifest_hash, sdk_version, status) "
        "VALUES (%s, 'cc3-testnet', 1, %s, 'mockdepin-testonly', %s, %s, '0.18.0', %s)",
        (rid, tx, profile, MANIFEST, status),
    )


def insert_artifact(conn, aid, rid):
    run(
        conn,
        "INSERT INTO proof_artifacts (proof_artifact_id, proof_request_id, artifact_hash, storage_ref, byte_length, sdk_version, claimed_height, claimed_tx_index) "
        "VALUES (%s, %s, %s, 'blob://proofs/x', 4096, '0.18.0', 9100000, 17)",
        (aid, rid, h32(aid)),
    )


def insert_verification(conn, vid, rid, aid, *, status="ACCEPTED", method="ATTESTCOIN_NATIVE", profile="NATIVE_TESTNET", tx=None):
    accepted = (NOW, 1, 1234, 9100000, 17) if status == "ACCEPTED" else (None, None, None, None, None)
    run(
        conn,
        "INSERT INTO native_verifications (native_verification_id, proof_request_id, proof_artifact_id, execution_profile, verification_method, "
        "destination_chain_id, verifier_address, submission_tx_hash, status, accepted_at, receipt_status, verification_block, proven_height, proven_tx_index) "
        "VALUES (%s, %s, %s, %s, %s, 102031, %s, %s, %s, %s, %s, %s, %s, %s)",
        (vid, rid, aid, profile, method, VERIFIER, tx or h32(vid), status, *accepted),
    )


def consumption_sql():
    return (
        "INSERT INTO evidence_consumptions (consumption_id, env_id, source_event_id, economic_event_id, native_verification_id, provider_id, "
        "provider_account_id, meaning, verification_method, trust, execution_profile, consumer_address, consumption_tx_hash, manifest_hash, "
        "proven_at, valid_until, chain_key, height, tx_index, log_ordinal, emitter_address, topic0, data_hash) "
        "VALUES (%s, 'cc3-testnet', %s, %s, %s, 'mockdepin-testonly', 'mockdepin-testonly:acct-A', %s, %s, %s, %s, %s, %s, %s, %s, %s, 1, 9100000, 17, %s, %s, %s, %s)"
    )


def consumption_params(cid, source_event, econ, vid, *, ordinal=0, meaning="OBLIGATION_RECOGNIZED", method="ATTESTCOIN_NATIVE", trust="PROVEN", profile="NATIVE_TESTNET"):
    return (cid, source_event, econ, vid, meaning, method, trust, profile, CONSUMER, h32("ctx" + cid), MANIFEST, NOW, NOW + timedelta(days=7), ordinal, ADDR1, h32("topic"), h32("data" + cid))


def pipeline_to_accepted(conn, *, rid="req-1", aid="art-1", vid="ver-1", tx=None):
    insert_proof_request(conn, ulid(rid), tx or h32(rid))
    insert_artifact(conn, ulid(aid), ulid(rid))
    insert_verification(conn, ulid(vid), ulid(rid), ulid(aid))
    return ulid(rid), ulid(aid), ulid(vid)


def insert_receipt(conn, rcid, amount, *, tx="rcpt", log_index=0, profile="NATIVE_TESTNET"):
    run(
        conn,
        "INSERT INTO cash_receipts (cash_receipt_id, vault_id, chain_id, token_address, decimals, amount, tx_hash, log_index, source_kind, execution_profile, received_at) "
        "VALUES (%s, 'vault-1', 102031, %s, 6, %s, %s, %s, 'DIRECT_REPAYMENT', %s, %s)",
        (rcid, MUSDT, amount, h32(tx), log_index, profile, NOW),
    )


def insert_allocation(conn, alid, rcid, fid, received, fee, interest, principal, excess, new_debt=0):
    run(
        conn,
        "INSERT INTO allocations (allocation_id, cash_receipt_id, facility_id, received, fee_paid, interest_paid, principal_paid, excess, new_debt) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (alid, rcid, fid, received, fee, interest, principal, excess, new_debt),
    )


def expect(conn, exc, sql, params=None, match=None):
    with pytest.raises(exc, match=match):
        with conn.cursor() as cur:
            cur.execute(sql, params)
    conn.rollback()


# ---------------------------------------------------------------- migration


def test_head_is_0002_with_ledger_tables_triggers_view(fresh_db_url):
    upgrade(fresh_db_url, "head")
    assert current(fresh_db_url) == HEAD  # head moves with later migrations (0003 = GPU-017); 0002 tables persist
    assert schema_diff(fresh_db_url) == []
    with psycopg2.connect(_dsn(fresh_db_url)) as c, c.cursor() as cur:
        cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE'")
        tables = {r[0] for r in cur.fetchall()}
        cur.execute("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal")
        triggers = {r[0] for r in cur.fetchall()}
        cur.execute("SELECT table_name FROM information_schema.views WHERE table_schema='public'")
        views = {r[0] for r in cur.fetchall()}
        cur.execute("SELECT proname FROM pg_proc WHERE proname = 'hcg_lease_job'")
        assert cur.fetchone() is not None
    expected = {
        "raw_source_observations", "proof_requests", "proof_artifacts", "native_verifications", "evidence_consumptions",
        "receivables", "receivable_revisions", "settlements", "settlement_receivables", "cash_receipts", "allocations",
        "recovery_events", "writeoffs", "audit_log", "correction_links", "ingest_cursors", "jobs", "outbox", "tx_intents", "exceptions",
    }
    assert expected <= tables
    assert len(tables) == 19 + 20 + 2 + 9 + 7 + 2 + 1  # domain, ledgers, assets, projections, durable API, credit status
    assert set(LEDGER_TRIGGER_NAMES) <= triggers
    assert views == {"v_cash_ownership"}
    # 0002 -> 0001 leaves the core schema intact, then back to head with no drift
    downgrade(fresh_db_url, "0001")
    assert current(fresh_db_url) == "0001"
    with psycopg2.connect(_dsn(fresh_db_url)) as c, c.cursor() as cur:
        cur.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")
        assert cur.fetchone()[0] == 19
        cur.execute("SELECT count(*) FROM pg_trigger WHERE NOT tgisinternal")
        assert cur.fetchone()[0] == 2
        cur.execute("SELECT count(*) FROM pg_proc WHERE proname LIKE 'hcg_%'")
        assert cur.fetchone()[0] == 2
    upgrade(fresh_db_url, "head")
    assert schema_diff(fresh_db_url) == []


# ---------------------------------------------------------------- proof pipeline: independent states


def test_proof_status_cannot_skip_ahead_of_evidence(conn):
    seed_base(conn)
    rid = ulid("req-1")
    insert_proof_request(conn, rid, h32("req-1"))
    # API 200 and eth_call pre-check are just timestamps; they do not make the request PROOF_READY/ACCEPTED
    run(conn, "UPDATE proof_requests SET api_ready_at = %s, precheck_ok_at = %s WHERE proof_request_id = %s", (NOW, NOW, rid))
    expect(conn, errors.CheckViolation, "UPDATE proof_requests SET status = 'PROOF_READY' WHERE proof_request_id = %s", (rid,), match="without a stored proof artifact")
    expect(conn, errors.CheckViolation, "UPDATE proof_requests SET status = 'NATIVE_ACCEPTED' WHERE proof_request_id = %s", (rid,))
    insert_artifact(conn, ulid("art-1"), rid)
    run(conn, "UPDATE proof_requests SET status = 'PROOF_READY' WHERE proof_request_id = %s", (rid,))
    run(conn, "UPDATE proof_requests SET status = 'SUBMITTED' WHERE proof_request_id = %s", (rid,))
    # a SUBMITTED / REJECTED verification is not acceptance
    insert_verification(conn, ulid("ver-0"), rid, ulid("art-1"), status="SUBMITTED", tx=h32("sub-0"))
    expect(conn, errors.CheckViolation, "UPDATE proof_requests SET status = 'NATIVE_ACCEPTED' WHERE proof_request_id = %s", (rid,), match="not acceptance")
    insert_verification(conn, ulid("ver-1"), rid, ulid("art-1"), status="ACCEPTED", tx=h32("sub-1"))
    run(conn, "UPDATE proof_requests SET status = 'NATIVE_ACCEPTED' WHERE proof_request_id = %s", (rid,))
    # accepted is still not consumed
    expect(conn, errors.CheckViolation, "UPDATE proof_requests SET status = 'CONSUMED' WHERE proof_request_id = %s", (rid,), match="without an evidence consumption")
    run(conn, consumption_sql(), consumption_params(ulid("con-1"), h32("se-1"), "mockdepin-testonly/acct-A/OBLIGATION/inv-A", ulid("ver-1")))
    run(conn, "UPDATE proof_requests SET status = 'CONSUMED' WHERE proof_request_id = %s", (rid,))
    with conn.cursor() as cur:
        cur.execute("SELECT status, api_ready_at IS NOT NULL, precheck_ok_at IS NOT NULL FROM proof_requests WHERE proof_request_id = %s", (rid,))
        assert cur.fetchone() == ("CONSUMED", True, True)


def test_accepted_verification_needs_receipt_block_and_position(conn):
    seed_base(conn)
    insert_proof_request(conn, ulid("req-1"), h32("req-1"))
    insert_artifact(conn, ulid("art-1"), ulid("req-1"))
    expect(
        conn, errors.CheckViolation,
        "INSERT INTO native_verifications (native_verification_id, proof_request_id, proof_artifact_id, execution_profile, verification_method, destination_chain_id, verifier_address, submission_tx_hash, status, accepted_at) "
        "VALUES (%s, %s, %s, 'NATIVE_TESTNET', 'ATTESTCOIN_NATIVE', 102031, %s, %s, 'ACCEPTED', %s)",
        (ulid("ver-x"), ulid("req-1"), ulid("art-1"), VERIFIER, h32("tx-x"), NOW),
    )
    # a mock verification cannot claim a native profile, and a native profile cannot use a mock
    expect(
        conn, errors.CheckViolation,
        "INSERT INTO native_verifications (native_verification_id, proof_request_id, proof_artifact_id, execution_profile, verification_method, destination_chain_id, verifier_address, submission_tx_hash) "
        "VALUES (%s, %s, %s, 'NATIVE_TESTNET', 'LOCAL_MOCK', 31337, %s, %s)",
        (ulid("ver-y"), ulid("req-1"), ulid("art-1"), VERIFIER, h32("tx-y")),
    )


def test_consumption_requires_accepted_verification_and_query_key_is_not_consumption_key(conn):
    seed_base(conn)
    rid, aid, vid = pipeline_to_accepted(conn)
    insert_verification(conn, ulid("ver-rej"), rid, aid, status="REJECTED", tx=h32("rej"))
    expect(conn, errors.CheckViolation, consumption_sql(), consumption_params(ulid("con-x"), h32("se-x"), "mockdepin-testonly/acct-A/OBLIGATION/inv-X", ulid("ver-rej")), match="ACCEPTED")
    # two logs of one tx share the proof request (cache key) but are two consumptions (ordinal 0 and 1)
    run(conn, consumption_sql(), consumption_params(ulid("con-0"), h32("se-0"), "mockdepin-testonly/acct-A/OBLIGATION/inv-A", vid, ordinal=0))
    run(conn, consumption_sql(), consumption_params(ulid("con-1"), h32("se-1"), "mockdepin-testonly/acct-A/OBLIGATION/inv-B", vid, ordinal=1))
    # same proof-bound locator again (re-submission with other proof bytes) is rejected
    expect(conn, errors.UniqueViolation, consumption_sql(), consumption_params(ulid("con-2"), h32("se-2"), "mockdepin-testonly/acct-A/OBLIGATION/inv-C", vid, ordinal=1))
    # the same source event id is rejected even with a new economic id
    expect(conn, errors.UniqueViolation, consumption_sql(), consumption_params(ulid("con-3"), h32("se-0"), "mockdepin-testonly/acct-A/OBLIGATION/inv-D", vid, ordinal=5))
    # an assertion must be labeled ASSERTED (our anchors never become PROVEN GPU revenue)
    expect(conn, errors.CheckViolation, consumption_sql(), consumption_params(ulid("con-4"), h32("se-4"), "mockdepin-testonly/acct-A/OBLIGATION/anchor", vid, ordinal=6, method="OFFCHAIN_ASSERTION", trust="PROVEN"))
    run(conn, consumption_sql(), consumption_params(ulid("con-5"), h32("se-5"), "mockdepin-testonly/acct-A/OBLIGATION/anchor", vid, ordinal=6, method="OFFCHAIN_ASSERTION", trust="ASSERTED"))


def test_same_economic_event_concurrent_insert_rejected(migrated_db_url):
    c1 = psycopg2.connect(_dsn(migrated_db_url))
    c2 = psycopg2.connect(_dsn(migrated_db_url))
    try:
        seed_base(c1)
        _, _, vid = pipeline_to_accepted(c1)
        econ = "mockdepin-testonly/acct-A/OBLIGATION/inv-A"
        with c1.cursor() as cur:  # first observer, uncommitted
            cur.execute(consumption_sql(), consumption_params(ulid("con-a"), h32("se-a"), econ, vid, ordinal=0))
        outcome: dict = {}

        def second_observer():
            try:
                with c2.cursor() as cur:  # same economic event via a different source log: blocks, then fails
                    cur.execute(consumption_sql(), consumption_params(ulid("con-b"), h32("se-b"), econ, vid, ordinal=1))
                c2.commit()
                outcome["result"] = "committed"
            except errors.UniqueViolation as e:
                outcome["result"] = "unique_violation"
                outcome["constraint"] = e.diag.constraint_name
                c2.rollback()

        t = threading.Thread(target=second_observer)
        t.start()
        t.join(timeout=1.0)
        assert t.is_alive(), "second insert must block on the uncommitted first one"
        c1.commit()
        t.join(timeout=10)
        assert outcome == {"result": "unique_violation", "constraint": "uq_evidence_consumptions_economic_event"}
        with c1.cursor() as cur:
            cur.execute("SELECT count(*) FROM evidence_consumptions WHERE economic_event_id = %s", (econ,))
            assert cur.fetchone()[0] == 1
    finally:
        c1.close()
        c2.close()


def test_production_consumption_cannot_reference_mock_or_other_profile(conn):
    seed_base(conn, provider_profile="PRODUCTION", provider_test_only=False)
    # LOCAL_MOCK pipeline
    insert_proof_request(conn, ulid("req-m"), h32("req-m"), profile="LOCAL_MOCK")
    insert_artifact(conn, ulid("art-m"), ulid("req-m"))
    insert_verification(conn, ulid("ver-m"), ulid("req-m"), ulid("art-m"), method="LOCAL_MOCK", profile="LOCAL_MOCK")
    # a PRODUCTION consumption row: CHECK forbids LOCAL_MOCK method, trigger forbids the mock verification
    expect(conn, errors.CheckViolation, consumption_sql(), consumption_params(ulid("con-p"), h32("se-p"), "mockdepin-testonly/acct-A/OBLIGATION/inv-P", ulid("ver-m"), method="LOCAL_MOCK", profile="PRODUCTION"))
    expect(conn, errors.CheckViolation, consumption_sql(), consumption_params(ulid("con-q"), h32("se-q"), "mockdepin-testonly/acct-A/OBLIGATION/inv-Q", ulid("ver-m"), method="ATTESTCOIN_NATIVE", profile="PRODUCTION"), match="cannot reference a LOCAL_MOCK")
    # a NATIVE_TESTNET consumption cannot borrow a LOCAL_MOCK verification either (profile mismatch)
    expect(conn, errors.CheckViolation, consumption_sql(), consumption_params(ulid("con-r"), h32("se-r"), "mockdepin-testonly/acct-A/OBLIGATION/inv-R", ulid("ver-m"), method="LOCAL_MOCK", profile="NATIVE_TESTNET"), match="does not match verification profile")
    # the mock consumption is fine under its own profile and stays labeled LOCAL_MOCK
    run(conn, consumption_sql(), consumption_params(ulid("con-s"), h32("se-s"), "mockdepin-testonly/acct-A/OBLIGATION/inv-S", ulid("ver-m"), method="LOCAL_MOCK", profile="LOCAL_MOCK"))


# ---------------------------------------------------------------- receivables / revisions


def _receivable(conn, rid, econ, ref, net, *, state="RECOGNIZED", facility=None, paid=0):
    run(
        conn,
        "INSERT INTO receivables (receivable_id, economic_event_id, provider_account_id, obligation_ref, asset_chain_id, asset_token_address, asset_decimals, gross, net, paid_amount, unpaid_amount, state, facility_id, execution_profile) "
        "VALUES (%s, %s, 'mockdepin-testonly:acct-A', %s, 11155111, %s, 6, %s, %s, %s, %s, %s, %s, 'NATIVE_TESTNET')",
        (rid, econ, ref, USDC, net, net, paid, net - paid, state, facility),
    )


def _revision(conn, rid, rev, kind, net_after, unpaid_after, *, out_of_order=False, consumption=None, observation=None, delta=0):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO receivable_revisions (receivable_id, revision, kind, consumption_id, observation_id, delta, net_after, unpaid_after, out_of_order) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (rid, rev, kind, consumption, observation, delta, net_after, unpaid_after, out_of_order),
        )
    conn.commit()


def test_receivable_revisions_are_monotonic_or_explicitly_out_of_order(conn):
    seed_base(conn)
    _, _, vid = pipeline_to_accepted(conn)
    con1, con2, con4 = ulid("con-1"), ulid("con-2"), ulid("con-4")
    run(conn, consumption_sql(), consumption_params(con1, h32("se-1"), "mockdepin-testonly/acct-A/OBLIGATION/inv-C", vid, ordinal=0))
    run(conn, consumption_sql(), consumption_params(con2, h32("se-2"), "mockdepin-testonly/acct-A/CORRECTION/inv-C:r2", vid, ordinal=1, meaning="CORRECTION"))
    run(conn, consumption_sql(), consumption_params(con4, h32("se-4"), "mockdepin-testonly/acct-A/CORRECTION/inv-C:r4", vid, ordinal=2, meaning="CORRECTION"))
    rid = ulid("rcv-1")
    _receivable(conn, rid, "mockdepin-testonly/acct-A/OBLIGATION/inv-C", "inv-C", 5_000_000_000)
    _revision(conn, rid, 1, "RECOGNIZED", 5_000_000_000, 5_000_000_000, consumption=con1)
    _revision(conn, rid, 2, "CORRECTION", 4_000_000_000, 4_000_000_000, consumption=con2, delta=-1_000_000_000)
    # S-03: revision 4 arrives before revision 3 — it is later, so it is accepted; a subsequent 3 is out of order
    _revision(conn, rid, 4, "CORRECTION", 3_500_000_000, 3_500_000_000, consumption=con4, delta=-500_000_000)
    with conn.cursor() as cur:
        cur.execute("SELECT revision FROM receivables WHERE receivable_id = %s", (rid,))
        assert cur.fetchone()[0] == 4
    with pytest.raises(errors.CheckViolation, match="not after latest 4"):
        _revision(conn, rid, 3, "CORRECTION", 0, 0, consumption=con2, delta=0)
    conn.rollback()
    # duplicate revision with the same kind is a unique violation; explicit out-of-order rows are allowed and flagged
    with pytest.raises(errors.CheckViolation):
        _revision(conn, rid, 2, "CORRECTION", 0, 0, consumption=con2)
    conn.rollback()
    _revision(conn, rid, 3, "CORRECTION", 3_500_000_000, 3_500_000_000, consumption=con2, out_of_order=True)
    with conn.cursor() as cur:
        cur.execute("SELECT revision FROM receivables WHERE receivable_id = %s", (rid,))
        assert cur.fetchone()[0] == 4, "out-of-order rows never move the current revision"
        cur.execute("SELECT count(*) FROM receivable_revisions WHERE receivable_id = %s AND out_of_order", (rid,))
        assert cur.fetchone()[0] == 1
    # a revision without provenance (neither consumption nor raw observation) is rejected
    with pytest.raises(errors.CheckViolation):
        _revision(conn, rid, 5, "CORRECTION", 0, 0)
    conn.rollback()


def test_receivable_balance_invariants_and_economic_uniqueness(conn):
    seed_facility(conn)
    _receivable(conn, ulid("rcv-1"), "mockdepin-testonly/acct-A/OBLIGATION/inv-A", "inv-A", 12_000_000_000, state="ASSIGNED", facility=ULID_D)
    # same economic event / same (account, ref) cannot become a second receivable
    expect(conn, errors.UniqueViolation, "INSERT INTO receivables (receivable_id, economic_event_id, provider_account_id, obligation_ref, asset_chain_id, asset_decimals, gross, net, unpaid_amount, execution_profile) VALUES (%s, %s, 'mockdepin-testonly:acct-A', 'inv-A2', 11155111, 6, 1, 1, 1, 'NATIVE_TESTNET')", (ulid("rcv-2"), "mockdepin-testonly/acct-A/OBLIGATION/inv-A"))
    expect(conn, errors.UniqueViolation, "INSERT INTO receivables (receivable_id, economic_event_id, provider_account_id, obligation_ref, asset_chain_id, asset_decimals, gross, net, unpaid_amount, execution_profile) VALUES (%s, 'mockdepin-testonly/acct-A/OBLIGATION/other', 'mockdepin-testonly:acct-A', 'inv-A', 11155111, 6, 1, 1, 1, 'NATIVE_TESTNET')", (ulid("rcv-3"),))
    # unpaid must equal net - paid; PAID needs unpaid 0; ASSIGNED needs a facility
    expect(conn, errors.CheckViolation, "UPDATE receivables SET paid_amount = 1, unpaid_amount = 12000000000 WHERE receivable_id = %s", (ulid("rcv-1"),))
    expect(conn, errors.CheckViolation, "UPDATE receivables SET state = 'PAID' WHERE receivable_id = %s", (ulid("rcv-1"),))
    expect(conn, errors.CheckViolation, "UPDATE receivables SET facility_id = NULL WHERE receivable_id = %s", (ulid("rcv-1"),))
    run(conn, "UPDATE receivables SET paid_amount = 12000000000, unpaid_amount = 0, state = 'PAID' WHERE receivable_id = %s", (ulid("rcv-1"),))


# ---------------------------------------------------------------- cash receipts / allocations


def test_allocation_split_and_receipt_total(conn):
    seed_facility(conn, principal=5_000_000_000)
    fid2 = "01J000000000000000000000GG"
    insert_facility(conn, fid2, profile="NATIVE_TESTNET", state="ACTIVE", control=ULID_C, funded_version=1, principal=1_000_000_000)
    rc = ulid("rcpt-1")
    insert_receipt(conn, rc, 1_000_000_000)
    # split must add up
    expect(conn, errors.CheckViolation, "INSERT INTO allocations (allocation_id, cash_receipt_id, facility_id, received, fee_paid, interest_paid, principal_paid, excess, new_debt) VALUES (%s, %s, %s, 600000000, 0, 100000000, 400000000, 0, 0)", (ulid("al-x"), rc, ULID_D))
    # one receipt split over two facilities (GPU-014 "1 payment, N receivables") within the total
    insert_allocation(conn, ulid("al-1"), rc, ULID_D, 600_000_000, 0, 100_000_000, 500_000_000, 0, new_debt=4_400_000_000)
    insert_allocation(conn, ulid("al-2"), rc, fid2, 300_000_000, 0, 0, 250_000_000, 50_000_000, new_debt=750_000_000)
    # a third allocation that would exceed the receipt is rejected by the trigger
    fid3 = "01J000000000000000000000HH"
    insert_facility(conn, fid3, profile="NATIVE_TESTNET", state="ACTIVE", control=ULID_C, funded_version=1)
    expect(conn, errors.CheckViolation, "INSERT INTO allocations (allocation_id, cash_receipt_id, facility_id, received, fee_paid, interest_paid, principal_paid, excess, new_debt) VALUES (%s, %s, %s, 200000000, 0, 0, 200000000, 0, 0)", (ulid("al-3"), rc, fid3), match="exceed the received amount")
    # ...and so is growing an existing allocation past it
    expect(conn, errors.CheckViolation, "UPDATE allocations SET received = 500000000, principal_paid = 450000000 WHERE allocation_id = %s", (ulid("al-2"),))
    # the same (receipt, facility) cannot be allocated twice; the same receipt cannot be recorded twice
    expect(conn, errors.UniqueViolation, "INSERT INTO allocations (allocation_id, cash_receipt_id, facility_id, received, fee_paid, interest_paid, principal_paid, excess, new_debt) VALUES (%s, %s, %s, 1, 0, 0, 1, 0, 0)", (ulid("al-4"), rc, ULID_D))
    expect(conn, errors.UniqueViolation, "INSERT INTO cash_receipts (cash_receipt_id, vault_id, chain_id, token_address, decimals, amount, tx_hash, log_index, execution_profile, received_at) VALUES (%s, 'vault-1', 102031, %s, 6, 5, %s, 0, 'NATIVE_TESTNET', %s)", (ulid("rcpt-2"), MUSDT, h32("rcpt"), NOW))
    with conn.cursor() as cur:
        cur.execute("SELECT received, lp_applied, borrower_refundable, borrower_refunded, unallocated FROM v_cash_ownership WHERE cash_receipt_id = %s", (rc,))
        assert cur.fetchone() == (Decimal(1_000_000_000), Decimal(850_000_000), Decimal(50_000_000), Decimal(0), Decimal(100_000_000))
    run(conn, "UPDATE allocations SET excess_refunded_at = %s WHERE allocation_id = %s", (NOW, ulid("al-2")))
    with conn.cursor() as cur:
        cur.execute("SELECT borrower_refundable, borrower_refunded FROM v_cash_ownership WHERE cash_receipt_id = %s", (rc,))
        assert cur.fetchone() == (Decimal(50_000_000), Decimal(50_000_000))


def test_settlement_paid_state_requires_proven_payout_and_cash_receipt_links(conn):
    seed_facility(conn)
    expect(
        conn, errors.CheckViolation,
        "INSERT INTO settlements (settlement_id, provider_account_id, settlement_ref, state, asset_chain_id, asset_token_address, asset_decimals, source_amount, execution_profile) "
        "VALUES (%s, 'mockdepin-testonly:acct-A', 'stl-1', 'PAID_AT_SOURCE', 11155111, %s, 6, 100, 'NATIVE_TESTNET')",
        (ulid("stl-1"), USDC),
    )
    run(
        conn,
        "INSERT INTO settlements (settlement_id, provider_account_id, settlement_ref, state, asset_chain_id, asset_token_address, asset_decimals, source_amount, execution_profile) "
        "VALUES (%s, 'mockdepin-testonly:acct-A', 'stl-1', 'ANNOUNCED', 11155111, %s, 6, 100, 'NATIVE_TESTNET')",
        (ulid("stl-1"), USDC),
    )
    # a SETTLEMENT-kind cash receipt must point at its settlement
    expect(conn, errors.CheckViolation, "INSERT INTO cash_receipts (cash_receipt_id, vault_id, chain_id, token_address, decimals, amount, tx_hash, log_index, source_kind, execution_profile, received_at) VALUES (%s, 'vault-1', 102031, %s, 6, 5, %s, 0, 'SETTLEMENT', 'NATIVE_TESTNET', %s)", (ulid("rcpt-s"), MUSDT, h32("s"), NOW))


def test_writeoff_never_extinguishes_debt_and_recovery_is_role_bound(conn):
    seed_facility(conn, principal=5_000_000_000)
    expect(conn, errors.CheckViolation, "INSERT INTO writeoffs (writeoff_id, facility_id, amount, legal_debt_remaining, extinguishes_debt, approved_by, approved_at, reason) VALUES (%s, %s, 1000, 4000, true, 'underwriter', %s, 'x')", (ulid("wo-1"), ULID_D, NOW))
    expect(conn, errors.CheckViolation, "INSERT INTO writeoffs (writeoff_id, facility_id, amount, legal_debt_remaining, approved_by, approved_at, reason) VALUES (%s, %s, 1000, 4000, 'keeper', %s, 'x')", (ulid("wo-2"), ULID_D, NOW))
    run(conn, "INSERT INTO writeoffs (writeoff_id, facility_id, amount, legal_debt_remaining, approved_by, approved_at, reason) VALUES (%s, %s, 1000, 4000, 'underwriter', %s, 'impairment')", (ulid("wo-3"), ULID_D, NOW))
    expect(conn, errors.CheckViolation, "INSERT INTO recovery_events (recovery_event_id, facility_id, kind, amount, occurred_at, recorded_by) VALUES (%s, %s, 'COLLECTION', 10, %s, 'keeper')", (ulid("rec-1"), ULID_D, NOW))
    run(conn, "INSERT INTO recovery_events (recovery_event_id, facility_id, kind, amount, occurred_at, recorded_by) VALUES (%s, %s, 'COLLECTION', 10, %s, 'operator')", (ulid("rec-2"), ULID_D, NOW))


# ---------------------------------------------------------------- audit / raw observations


def test_audit_log_and_raw_observations_are_append_only(conn):
    seed_base(conn)
    run(conn, "INSERT INTO audit_log (actor, actor_role, action, entity_table, entity_id, entry_hash) VALUES ('ops@rackline', 'operator', 'facility.approve', 'facilities', %s, %s)", (ULID_D, HASH1))
    expect(conn, errors.CheckViolation, "UPDATE audit_log SET action = 'facility.reject'", match="append-only")
    expect(conn, errors.CheckViolation, "DELETE FROM audit_log", match="append-only")
    expect(conn, errors.CheckViolation, "INSERT INTO audit_log (actor, actor_role, action, entity_table, entity_id, entry_hash) VALUES ('x', 'oracle', 'a', 't', 'i', %s)", (HASH1,))
    run(conn, "INSERT INTO raw_source_observations (observation_id, provider_id, origin, schema_id, payload_hash, payload_ref, trust, observed_at) VALUES (%s, 'mockdepin-testonly', 'API', 'aethir.settlement', %s, 'blob://raw/1', 'OBSERVED', %s)", (ulid("obs-1"), h32("p1"), NOW))
    expect(conn, errors.CheckViolation, "UPDATE raw_source_observations SET trust = 'PROVEN'", match="append-only")
    expect(conn, errors.CheckViolation, "DELETE FROM raw_source_observations", match="append-only")
    # the same payload from the same origin is not stored twice; raw payloads are references only
    expect(conn, errors.UniqueViolation, "INSERT INTO raw_source_observations (observation_id, provider_id, origin, schema_id, payload_hash, trust, observed_at) VALUES (%s, 'mockdepin-testonly', 'API', 'aethir.settlement', %s, 'OBSERVED', %s)", (ulid("obs-2"), h32("p1"), NOW))
    expect(conn, errors.CheckViolation, "INSERT INTO raw_source_observations (observation_id, provider_id, origin, schema_id, payload_hash, payload_ref, trust, observed_at) VALUES (%s, 'mockdepin-testonly', 'API', 'x', %s, 'https://api.example/payload', 'OBSERVED', %s)", (ulid("obs-3"), h32("p3"), NOW))


# ---------------------------------------------------------------- jobs / outbox / tx intents


def test_job_idempotency_and_exclusive_lease(migrated_db_url):
    c1 = psycopg2.connect(_dsn(migrated_db_url))
    c2 = psycopg2.connect(_dsn(migrated_db_url))
    try:
        jid = ulid("job-1")
        run(c1, "INSERT INTO jobs (job_id, kind, semantic_idempotency_key, payload_hash, max_attempts) VALUES (%s, 'proof.request', 'proof:cc3-testnet:1:0xabc', %s, 2)", (jid, HASH1))
        expect(c1, errors.UniqueViolation, "INSERT INTO jobs (job_id, kind, semantic_idempotency_key, payload_hash) VALUES (%s, 'proof.request', 'proof:cc3-testnet:1:0xabc', %s)", (ulid("job-2"), HASH1))
        # two workers race for the lease: exactly one wins
        with c1.cursor() as cur:
            cur.execute("SELECT hcg_lease_job(%s, 'worker-a', 60)", (jid,))
            won_a = cur.fetchone()[0]
        c1.commit()
        with c2.cursor() as cur:
            cur.execute("SELECT hcg_lease_job(%s, 'worker-b', 60)", (jid,))
            won_b = cur.fetchone()[0]
        c2.commit()
        assert (won_a, won_b) == (True, False)
        with c1.cursor() as cur:
            cur.execute("SELECT state, leased_by, attempt FROM jobs WHERE job_id = %s", (jid,))
            assert cur.fetchone() == ("LEASED", "worker-a", 1)
        # an expired lease can be taken over (crash recovery); max_attempts then blocks a third attempt
        run(c1, "UPDATE jobs SET lease_until = now() - interval '1 second' WHERE job_id = %s", (jid,))
        with c2.cursor() as cur:
            cur.execute("SELECT hcg_lease_job(%s, 'worker-b', 60)", (jid,))
            assert cur.fetchone()[0] is True
        c2.commit()
        run(c1, "UPDATE jobs SET lease_until = now() - interval '1 second' WHERE job_id = %s", (jid,))
        with c2.cursor() as cur:
            cur.execute("SELECT hcg_lease_job(%s, 'worker-c', 60)", (jid,))
            assert cur.fetchone()[0] is False, "attempt < max_attempts must hold"
        c2.commit()
        # LEASED rows must carry lease fields
        expect(c1, errors.CheckViolation, "UPDATE jobs SET leased_by = NULL WHERE job_id = %s", (jid,))
    finally:
        c1.close()
        c2.close()


def test_outbox_and_tx_intent_uniqueness(conn):
    run(conn, "INSERT INTO outbox (aggregate_type, aggregate_id, event_type, idempotency_key) VALUES ('facility', %s, 'FacilityApproved', 'facility:approve:1')", (ULID_D,))
    expect(conn, errors.UniqueViolation, "INSERT INTO outbox (aggregate_type, aggregate_id, event_type, idempotency_key) VALUES ('facility', %s, 'FacilityApproved', 'facility:approve:1')", (ULID_D,))
    run(conn, "INSERT INTO tx_intents (tx_intent_id, chain_id, signer_address, nonce, purpose, to_address, calldata_hash) VALUES (%s, 102031, %s, 7, 'evidence.consume', %s, %s)", (ulid("tx-1"), ADDR1, ADDR2, HASH1))
    # the EVM nonce index is unique per (chain, signer); a replacement links to the original
    expect(conn, errors.UniqueViolation, "INSERT INTO tx_intents (tx_intent_id, chain_id, signer_address, nonce, purpose, to_address, calldata_hash) VALUES (%s, 102031, %s, 7, 'evidence.consume', %s, %s)", (ulid("tx-2"), ADDR1, ADDR2, HASH1))
    run(conn, "UPDATE tx_intents SET state = 'REPLACED' WHERE tx_intent_id = %s", (ulid("tx-1"),))
    run(conn, "INSERT INTO tx_intents (tx_intent_id, chain_id, signer_address, nonce, purpose, to_address, calldata_hash, replaces_tx_intent_id) VALUES (%s, 102031, %s, 8, 'evidence.consume', %s, %s, %s)", (ulid("tx-3"), ADDR1, ADDR2, HASH1, ulid("tx-1")))
    # SENT/MINED/FINAL need a tx hash; FINAL needs blocks
    expect(conn, errors.CheckViolation, "UPDATE tx_intents SET state = 'SENT' WHERE tx_intent_id = %s", (ulid("tx-3"),))
    run(conn, "UPDATE tx_intents SET state = 'SENT', tx_hash = %s WHERE tx_intent_id = %s", (h32("tx3"), ulid("tx-3")))
    expect(conn, errors.CheckViolation, "UPDATE tx_intents SET state = 'FINAL' WHERE tx_intent_id = %s", (ulid("tx-3"),))
    run(conn, "UPDATE tx_intents SET state = 'FINAL', mined_block = 100, finality_block = 110 WHERE tx_intent_id = %s", (ulid("tx-3"),))


# ---------------------------------------------------------------- backup / restore


def test_backup_restore_preserves_ledger_totals(pg_server_url, fresh_db_url, pg_bindir):
    if pg_bindir is None or not (pg_bindir / "pg_dump").exists():
        pytest.fail("pg_dump/pg_restore not found next to the PostgreSQL binaries")
    upgrade(fresh_db_url, "head")
    c = psycopg2.connect(_dsn(fresh_db_url))
    try:
        seed_facility(c, principal=5_000_000_000)
        _, _, vid = pipeline_to_accepted(c)
        run(c, consumption_sql(), consumption_params(ulid("con-1"), h32("se-1"), "mockdepin-testonly/acct-A/OBLIGATION/inv-A", vid))
        _receivable(c, ulid("rcv-1"), "mockdepin-testonly/acct-A/OBLIGATION/inv-A", "inv-A", 12_000_000_000, state="ASSIGNED", facility=ULID_D)
        _revision(c, ulid("rcv-1"), 1, "RECOGNIZED", 12_000_000_000, 12_000_000_000, consumption=ulid("con-1"))
        insert_receipt(c, ulid("rcpt-1"), 1_000_000_000)
        insert_allocation(c, ulid("al-1"), ulid("rcpt-1"), ULID_D, 1_000_000_000, 0, 100_000_000, 850_000_000, 50_000_000, new_debt=4_150_000_000)
        run(c, "INSERT INTO audit_log (actor, actor_role, action, entity_table, entity_id, entry_hash) VALUES ('sys', 'system', 'allocate', 'allocations', %s, %s)", (ulid("al-1"), HASH1))
    finally:
        c.close()

    def snapshot(url):
        with psycopg2.connect(_dsn(url)) as cc, cc.cursor() as cur:
            cur.execute("SELECT sum(unpaid_amount), count(*) FROM receivables")
            recv = cur.fetchone()
            cur.execute("SELECT sum(lp_applied), sum(borrower_refundable), sum(unallocated) FROM v_cash_ownership")
            cash = cur.fetchone()
            cur.execute("SELECT count(*), max(revision) FROM receivable_revisions")
            revs = cur.fetchone()
            cur.execute("SELECT count(*) FROM evidence_consumptions")
            cons = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM audit_log")
            audit = cur.fetchone()[0]
        return recv, cash, revs, cons, audit

    before = snapshot(fresh_db_url)
    assert before[1] == (Decimal(950_000_000), Decimal(50_000_000), Decimal(0))
    dump = subprocess.run([str(pg_bindir / "pg_dump"), "--format=custom", "--dbname", _dsn(fresh_db_url)], capture_output=True, check=True).stdout
    downgrade(fresh_db_url, "base")
    with psycopg2.connect(_dsn(fresh_db_url)) as cc, cc.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS alembic_version")
        cc.commit()
    subprocess.run([str(pg_bindir / "pg_restore"), "--dbname", _dsn(fresh_db_url), "--no-owner"], input=dump, capture_output=True, check=True)
    assert snapshot(fresh_db_url) == before
    assert current(fresh_db_url) == HEAD
    assert schema_diff(fresh_db_url) == []
    # triggers survive: the audit log is still append-only after restore
    with psycopg2.connect(_dsn(fresh_db_url)) as cc, cc.cursor() as cur:
        with pytest.raises(errors.CheckViolation):
            cur.execute("DELETE FROM audit_log")
        cc.rollback()
