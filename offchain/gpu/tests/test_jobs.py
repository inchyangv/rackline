"""
GPU-025: durable jobs, transactional outbox, worker loop and the proof lifecycle over migration 0002 tables.
Real PostgreSQL (ephemeral cluster from conftest). Two-worker races use two engines/threads.
"""

from __future__ import annotations

import random
import threading

import psycopg2
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from hashcredit_gpu.jobs import (
    PROOF_JOB_KINDS,
    BackoffPolicy,
    FailureKind,
    JobQueue,
    LeaseLost,
    Outcome,
    ProofLifecycle,
    ResumeRequiresReason,
    TerminalError,
    TransientError,
    Worker,
    dispatch_outbox,
    emit,
)
from hashcredit_gpu.jobs.outbox import pending_outbox
from hashcredit_gpu.jobs.proof import SIGNER_FALLBACK_TERMS, job_key
from hashcredit_gpu.jobs.queue import new_ulid, payload_hash

from .conftest import _dsn
from .test_event_ledger import (
    consumption_params,
    consumption_sql,
    h32,
    insert_artifact,
    insert_proof_request,
    insert_verification,
    ulid,
)
from .test_schema import run, seed_base


@pytest.fixture
def engine(migrated_db_url):
    eng = create_engine(migrated_db_url, future=True)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture
def queue(engine):
    return JobQueue(engine, BackoffPolicy(base_seconds=1.0, factor=2.0, cap_seconds=64.0, jitter_fraction=0.0))


def _expire_lease(engine, job_id):
    with engine.begin() as c:
        c.execute(text("UPDATE jobs SET lease_until = now() - interval '1 second' WHERE job_id = :id"), {"id": job_id})


def _state(engine, job_id):
    with engine.connect() as c:
        return c.execute(text("SELECT state, attempt, leased_by, last_error FROM jobs WHERE job_id = :id"), {"id": job_id}).one()


# ---------------------------------------------------------------- basics


def test_ulid_and_payload_hash_shapes():
    u = new_ulid(rng=random.Random(1))
    assert len(u) == 26 and all(ch in "0123456789ABCDEFGHJKMNPQRSTVWXYZ" for ch in u)
    assert payload_hash({"b": 1, "a": "x"}) == payload_hash({"a": "x", "b": 1})
    assert payload_hash({"a": 1}).startswith("0x") and len(payload_hash({"a": 1})) == 66


def test_enqueue_is_idempotent_on_semantic_key(engine, queue):
    j1 = queue.enqueue("PROOF_WAIT_ATTESTATION", {"req": "r1"}, "proof:PROOF_WAIT_ATTESTATION:r1")
    j2 = queue.enqueue("PROOF_WAIT_ATTESTATION", {"req": "r1", "extra": 1}, "proof:PROOF_WAIT_ATTESTATION:r1")
    assert j1 == j2
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM jobs")).scalar_one() == 1
    with pytest.raises(ValueError):
        queue.enqueue("X", {}, "")


def test_two_workers_compete_exactly_one_claims(migrated_db_url, engine, queue):
    job_id = queue.enqueue("K", {"n": 1}, "k:1")
    results: list = [None, None]
    barrier = threading.Barrier(2)

    def worker(i):
        eng = create_engine(migrated_db_url, future=True)
        q = JobQueue(eng)
        barrier.wait()
        results[i] = q.claim(f"worker-{i}", ["K"], lease_seconds=60)
        eng.dispose()

    ts = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    claimed = [r for r in results if r is not None]
    assert len(claimed) == 1 and claimed[0].job_id == job_id and claimed[0].attempt == 1
    assert _state(engine, job_id)[0] == "LEASED"


def test_claim_explicit_ids_preserves_kind_filter_and_empty_selection(engine, queue):
    excluded_id = queue.enqueue("K", {}, "k:excluded")
    selected_id = queue.enqueue("K", {}, "k:selected")
    assert queue.claim("worker-a", ["K"], job_ids=[]) is None
    assert queue.claim("worker-a", ["OTHER"], job_ids=[selected_id]) is None
    selected = queue.claim("worker-a", ["K"], job_ids=[selected_id])
    assert selected is not None and selected.job_id == selected_id
    assert _state(engine, excluded_id)[0] == "PENDING"
    unrestricted = queue.claim("worker-b", ["K"])
    assert unrestricted is not None and unrestricted.job_id == excluded_id


def test_lease_expiry_allows_reclaim_and_stale_worker_cannot_complete_or_fail(engine, queue):
    job_id = queue.enqueue("K", {}, "k:2", max_attempts=5)
    a = queue.claim("worker-a", ["K"], lease_seconds=60)
    assert a is not None and a.attempt == 1
    assert queue.claim("worker-b", ["K"]) is None, "held lease is exclusive"
    _expire_lease(engine, job_id)
    b = queue.claim("worker-b", ["K"], lease_seconds=60)
    assert b is not None and b.attempt == 2 and b.worker_id == "worker-b"
    # the late worker A (lost lease) can neither complete nor fail the job
    with pytest.raises(LeaseLost):
        queue.complete(a)
    with pytest.raises(LeaseLost):
        queue.fail(a, FailureKind.TRANSIENT, "late")
    assert _state(engine, job_id)[:3] == ("LEASED", 2, "worker-b")
    queue.renew_lease(b, 120)
    queue.complete(b)
    assert _state(engine, job_id)[0] == "SUCCEEDED"
    with pytest.raises(LeaseLost):
        queue.complete(b)  # already completed: fenced


def test_crash_before_commit_rolls_back_effect_and_job_is_reclaimable(engine, queue):
    job_id = queue.enqueue("K", {}, "k:3", max_attempts=5)
    job = queue.claim("worker-a", ["K"])
    assert job is not None
    # handler transaction: effect + completion, then "crash" (rollback) before commit
    with engine.connect() as c:
        tx = c.begin()
        emit(c, aggregate_type="t", aggregate_id="1", event_type="E", payload={}, idempotency_key="k:3:effect")
        queue.complete(job, cx=c)
        tx.rollback()
    assert pending_outbox(engine) == 0, "effect rolled back with the crash"
    assert _state(engine, job_id)[0] == "LEASED", "completion rolled back too"
    _expire_lease(engine, job_id)
    again = queue.claim("worker-b", ["K"])
    assert again is not None and again.attempt == 2


def test_crash_after_commit_no_duplicate_economic_effect(engine, queue):
    """Effect committed in its own tx, crash before completion: the re-run hits the idempotency key and is a no-op."""
    job_id = queue.enqueue("K", {}, "k:4", max_attempts=5)
    job = queue.claim("worker-a", ["K"])
    assert job is not None
    with engine.begin() as c:
        assert emit(c, aggregate_type="t", aggregate_id="1", event_type="E", payload={"amt": "1"}, idempotency_key="k:4:effect") is not None
    # crash here (no completion) -> lease expires -> re-claim -> handler re-runs
    _expire_lease(engine, job_id)
    job2 = queue.claim("worker-b", ["K"])
    assert job2 is not None
    with engine.begin() as c:
        assert emit(c, aggregate_type="t", aggregate_id="1", event_type="E", payload={"amt": "1"}, idempotency_key="k:4:effect") is None
        queue.complete(job2, cx=c)
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM outbox WHERE idempotency_key = 'k:4:effect'")).scalar_one() == 1
    assert _state(engine, job_id)[0] == "SUCCEEDED"


# ---------------------------------------------------------------- failure classification / backoff / dead-letter


def test_backoff_schedule_exponential_capped_with_jitter():
    p = BackoffPolicy(base_seconds=2, factor=2, cap_seconds=100, jitter_fraction=0.0)
    assert [p.delay(a) for a in (1, 2, 3, 4, 5, 6, 7)] == [2, 4, 8, 16, 32, 64, 100]
    j = BackoffPolicy(base_seconds=10, factor=2, cap_seconds=100, jitter_fraction=0.5)
    rng = random.Random(7)
    samples = {round(j.delay(1, rng), 3) for _ in range(20)}
    assert all(5 <= s <= 15 for s in samples) and len(samples) > 1


def test_transient_failure_schedules_retry_then_dead_letters_when_exhausted(engine, queue):
    job_id = queue.enqueue("K", {}, "k:5", max_attempts=2)
    j = queue.claim("w", ["K"])
    assert queue.fail(j, FailureKind.TRANSIENT, "not ready") == "PENDING"
    st = _state(engine, job_id)
    assert st[0] == "PENDING" and st[1] == 1 and st[3].startswith("TRANSIENT: not ready")
    assert queue.claim("w", ["K"]) is None, "next_run_at is in the future (backoff)"
    with engine.begin() as c:
        c.execute(text("UPDATE jobs SET next_run_at = now() WHERE job_id = :id"), {"id": job_id})
    j = queue.claim("w", ["K"])
    assert j is not None and j.attempt == 2
    assert queue.fail(j, FailureKind.TRANSIENT, "still not ready") == "DEAD"
    st = _state(engine, job_id)
    assert st[0] == "DEAD" and "attempts exhausted" in st[3]
    assert queue.claim("w", ["K"]) is None, "DEAD jobs are never auto-claimed"


def test_terminal_failure_dead_letters_immediately_and_is_not_auto_resumed(engine, queue):
    job_id = queue.enqueue("K", {}, "k:6", max_attempts=10)
    j = queue.claim("w", ["K"])
    assert queue.fail(j, FailureKind.TERMINAL, "unsupported source") == "DEAD"
    with engine.begin() as c:
        c.execute(text("UPDATE jobs SET next_run_at = now() - interval '1 day' WHERE job_id = :id"), {"id": job_id})
    assert queue.claim("w", ["K"]) is None
    assert [r.job_id for r in queue.list_jobs("DEAD")] == [job_id]


def test_resume_requires_actor_role_reason_and_writes_audit(engine, queue):
    job_id = queue.enqueue("K", {}, "k:7", max_attempts=1)
    j = queue.claim("w", ["K"])
    queue.fail(j, FailureKind.TRANSIENT, "boom")
    assert _state(engine, job_id)[0] == "DEAD"
    for kwargs in (
        {"actor": "", "actor_role": "operator", "reason": "x"},
        {"actor": "ops-1", "actor_role": "operator", "reason": "   "},
        {"actor": "ops-1", "actor_role": "not-a-role", "reason": "x"},
    ):
        with pytest.raises(ResumeRequiresReason):
            queue.resume(job_id, **kwargs)
    assert _state(engine, job_id)[0] == "DEAD"
    queue.resume(job_id, actor="ops-1", actor_role="operator", reason="upstream outage resolved, ticket OPS-42")
    st = _state(engine, job_id)
    assert st[0] == "PENDING" and st[1] == 1
    assert queue.get(job_id).max_attempts == 2
    with engine.connect() as c:
        row = c.execute(
            text("SELECT actor, actor_role, action, entity_table, entity_id, before, after, entry_hash FROM audit_log ORDER BY id DESC LIMIT 1")
        ).one()
    assert (row.actor, row.actor_role, row.action, row.entity_table, row.entity_id) == ("ops-1", "operator", "job.resume", "jobs", job_id)
    assert row.before["state"] == "DEAD" and row.after["reason"].startswith("upstream outage")
    assert row.after["attempt"] == 1 and row.after["max_attempts"] == 2
    assert row.entry_hash.startswith("0x")
    # a second resume on a non-DEAD job is refused; audit rows are immutable
    with pytest.raises(ValueError):
        queue.resume(job_id, actor="ops-1", actor_role="operator", reason="again")
    with pytest.raises(DBAPIError, match="append-only"), engine.begin() as c:
        c.execute(text("DELETE FROM audit_log"))
    # resumed job is claimable again
    assert queue.claim("w", ["K"]) is not None


def test_resume_never_reuses_stale_lease_token_for_same_worker(engine, queue):
    job_id = queue.enqueue("K", {}, "k:resume-fence", max_attempts=5)
    stale = queue.claim("worker-a", ["K"])
    assert stale is not None and stale.attempt == 1
    _expire_lease(engine, job_id)
    replacement = queue.claim("worker-b", ["K"])
    assert replacement is not None and replacement.attempt == 2
    queue.fail(replacement, FailureKind.TERMINAL, "upstream configuration rejected")

    queue.resume(job_id, actor="ops-1", actor_role="operator", reason="upstream configuration corrected")
    current = queue.claim("worker-a", ["K"])
    assert current is not None and current.attempt == 3 and current.max_attempts == 7
    with pytest.raises(LeaseLost):
        queue.complete(stale)
    with pytest.raises(LeaseLost):
        queue.fail(stale, FailureKind.TERMINAL, "late failure")
    with pytest.raises(LeaseLost):
        queue.renew_lease(stale)
    assert _state(engine, job_id)[:3] == ("LEASED", 3, "worker-a")
    queue.renew_lease(current, 120)
    queue.complete(current)
    assert _state(engine, job_id)[0] == "SUCCEEDED"


# ---------------------------------------------------------------- outbox


def test_outbox_duplicate_insert_refused_and_double_publish_harmless(engine):
    with engine.begin() as c:
        assert emit(c, aggregate_type="facility", aggregate_id="f1", event_type="Approved", payload={"v": 1}, idempotency_key="f1:approve") is not None
        assert emit(c, aggregate_type="facility", aggregate_id="f1", event_type="Approved", payload={"v": 1}, idempotency_key="f1:approve") is None
        with pytest.raises(ValueError):
            emit(c, aggregate_type="facility", aggregate_id="f1", event_type="Approved", payload={}, idempotency_key="")
    # raw duplicate insert (bypassing emit) is a unique violation
    with pytest.raises(IntegrityError), engine.begin() as c:
        c.execute(text("INSERT INTO outbox (aggregate_type, aggregate_id, event_type, idempotency_key) VALUES ('facility','f1','Approved','f1:approve')"))
    delivered: list[str] = []
    calls = {"n": 0}

    def flaky_publisher(ev):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionError("broker down")
        delivered.append(ev.idempotency_key)

    assert dispatch_outbox(engine, flaky_publisher) == (0, 1)
    assert pending_outbox(engine) == 1
    assert dispatch_outbox(engine, flaky_publisher) == (1, 0)
    assert pending_outbox(engine) == 0
    # simulate "published but commit lost": re-open the row and dispatch again -> consumer sees the same key twice
    with engine.begin() as c:
        c.execute(text("UPDATE outbox SET published_at = NULL WHERE idempotency_key = 'f1:approve'"))
    assert dispatch_outbox(engine, flaky_publisher) == (1, 0)
    assert delivered == ["f1:approve", "f1:approve"], "at-least-once: consumers dedup on idempotency_key"


def test_outbox_emit_is_transactional_with_business_change(engine, queue):
    with engine.connect() as c:
        tx = c.begin()
        queue.enqueue("K", {}, "k:8", cx=c)
        emit(c, aggregate_type="job", aggregate_id="k:8", event_type="Enqueued", payload={}, idempotency_key="k:8:enq")
        tx.rollback()
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM jobs")).scalar_one() == 0
        assert c.execute(text("SELECT count(*) FROM outbox")).scalar_one() == 0


# ---------------------------------------------------------------- worker loop


def test_worker_runs_handler_atomically_and_classifies_exceptions(engine, queue):
    seen: list[tuple[str, int]] = []

    def ok(cx, job):
        seen.append((job.kind, job.attempt))
        emit(cx, aggregate_type="t", aggregate_id=job.job_id, event_type="Done", payload={}, idempotency_key=f"{job.job_id}:done")

    def transient(cx, job):
        raise TransientError("upstream 503")

    def terminal(cx, job):
        raise TerminalError("unsupported chain")

    def unexpected(cx, job):
        raise RuntimeError("bug")

    def half_done(cx, job):
        emit(cx, aggregate_type="t", aggregate_id=job.job_id, event_type="Partial", payload={}, idempotency_key=f"{job.job_id}:partial")
        raise TransientError("crashed after writing")

    j_ok = queue.enqueue("OK", {}, "ok:1")
    j_tr = queue.enqueue("TR", {}, "tr:1", max_attempts=3)
    j_te = queue.enqueue("TE", {}, "te:1")
    j_un = queue.enqueue("UN", {}, "un:1", max_attempts=3)
    j_hd = queue.enqueue("HD", {}, "hd:1", max_attempts=3)
    w = Worker(engine, queue, {"OK": ok, "TR": transient, "TE": terminal, "UN": unexpected, "HD": half_done}, worker_id="w1", sleep=lambda s: None)
    states = {}
    for _ in range(5):
        job = queue.claim("w1", w.kinds)
        assert job is not None
        states[job.job_id] = w.run_one(job)
    assert states == {j_ok: "SUCCEEDED", j_tr: "PENDING", j_te: "DEAD", j_un: "PENDING", j_hd: "PENDING"}
    assert _state(engine, j_un)[3].startswith("TRANSIENT: RuntimeError: bug")
    assert _state(engine, j_te)[3].startswith("TERMINAL: unsupported chain")
    with engine.connect() as c:
        keys = set(c.execute(text("SELECT idempotency_key FROM outbox")).scalars())
    assert keys == {f"{j_ok}:done"}, "a failing handler's partial writes are rolled back with its transaction"
    assert seen == [("OK", 1)]
    assert w.run_once() is None, "nothing runnable now (backoff / dead)"


def test_worker_lease_lost_mid_handler_is_not_recorded_as_success(engine, queue):
    job_id = queue.enqueue("SLOW", {}, "slow:1", max_attempts=5)

    def slow(cx, job):
        _expire_lease(engine, job.job_id)  # lease expires while the handler runs
        other = queue.claim("w2", ["SLOW"])  # another worker takes over
        assert other is not None and other.attempt == 2

    w = Worker(engine, queue, {"SLOW": slow}, worker_id="w1")
    job = queue.claim("w1", ["SLOW"])
    assert w.run_one(job) == "LEASE_LOST"
    assert _state(engine, job_id)[:3] == ("LEASED", 2, "w2")


# ---------------------------------------------------------------- proof lifecycle (R2)


def test_no_signer_or_fallback_job_kind_exists():
    assert PROOF_JOB_KINDS == ("PROOF_WAIT_ATTESTATION", "PROOF_FETCH_ARTIFACT", "PROOF_SUBMIT", "PROOF_CONFIRM", "EVIDENCE_CONSUME")
    assert not ProofLifecycle.has_signer_fallback()
    assert ProofLifecycle.has_signer_fallback(PROOF_JOB_KINDS + ("PROOF_SIGN_FALLBACK",))
    for k in PROOF_JOB_KINDS:
        assert not any(term in k for term in SIGNER_FALLBACK_TERMS), k


def _seed_request(migrated_db_url, rid="req-1", *, seed=True):
    conn = psycopg2.connect(_dsn(migrated_db_url))
    try:
        if seed:
            seed_base(conn)
        insert_proof_request(conn, ulid(rid), h32(rid), status="OBSERVED")
    finally:
        conn.close()
    return ulid(rid)


def test_proof_lifecycle_not_ready_loops_then_unsupported_is_terminal(migrated_db_url, engine, queue):
    rid = _seed_request(migrated_db_url)
    kind = "PROOF_WAIT_ATTESTATION"
    job_id = queue.enqueue(kind, {"proof_request_id": rid}, job_key(kind, rid), max_attempts=5)

    outcomes = iter([Outcome.NOT_READY, Outcome.NOT_READY, Outcome.NETWORK_ERROR, Outcome.UNSUPPORTED])

    def handler(cx, job):
        ProofLifecycle.apply(cx, job.payload["proof_request_id"], job.kind, next(outcomes))

    w = Worker(engine, queue, {kind: handler}, worker_id="w1")
    trail = []
    for _ in range(4):
        with engine.begin() as c:
            c.execute(text("UPDATE jobs SET next_run_at = now() WHERE job_id = :id"), {"id": job_id})
        job = queue.claim("w1", [kind])
        assert job is not None
        trail.append(w.run_one(job))
        with engine.connect() as c:
            status = c.execute(text("SELECT status FROM proof_requests WHERE proof_request_id = :id"), {"id": rid}).scalar_one()
        trail.append(status)
    assert trail == ["PENDING", "WAITING_ATTESTATION", "PENDING", "WAITING_ATTESTATION", "PENDING", "WAITING_ATTESTATION", "DEAD", "UNSUPPORTED"]
    # terminal request: even a later OK is refused
    with engine.connect() as c, pytest.raises(TerminalError), c.begin():
        ProofLifecycle.apply(c, rid, kind, Outcome.OK)


def test_proof_ok_transitions_need_the_evidence_rows_api200_is_not_acceptance(migrated_db_url, engine):
    rid = _seed_request(migrated_db_url, "req-2")
    with engine.begin() as c:
        t = ProofLifecycle.apply(c, rid, "PROOF_WAIT_ATTESTATION", Outcome.OK)
        assert (t.status_after, t.next_kind) == ("WAITING_ATTESTATION", "PROOF_FETCH_ARTIFACT")
    # "artifact fetched" without a stored artifact row: the DB trigger refuses PROOF_READY
    with pytest.raises(IntegrityError, match="without a stored proof artifact"), engine.begin() as c:
        c.execute(text("UPDATE proof_requests SET api_ready_at = now() WHERE proof_request_id = :id"), {"id": rid})
        ProofLifecycle.apply(c, rid, "PROOF_FETCH_ARTIFACT", Outcome.OK)
    conn = psycopg2.connect(_dsn(migrated_db_url))
    try:
        insert_artifact(conn, ulid("art-2"), rid)
    finally:
        conn.close()
    with engine.begin() as c:
        assert ProofLifecycle.apply(c, rid, "PROOF_FETCH_ARTIFACT", Outcome.OK).status_after == "PROOF_READY"
        assert ProofLifecycle.apply(c, rid, "PROOF_SUBMIT", Outcome.OK).status_after == "SUBMITTED"
    # eth_call precheck ok is not native acceptance: NATIVE_ACCEPTED needs an ACCEPTED verification row
    with pytest.raises(IntegrityError, match="API 200 / eth_call are not acceptance"), engine.begin() as c:
        c.execute(text("UPDATE proof_requests SET precheck_ok_at = now() WHERE proof_request_id = :id"), {"id": rid})
        ProofLifecycle.apply(c, rid, "PROOF_CONFIRM", Outcome.OK)
    conn = psycopg2.connect(_dsn(migrated_db_url))
    try:
        insert_verification(conn, ulid("ver-2"), rid, ulid("art-2"))
    finally:
        conn.close()
    with engine.begin() as c:
        assert ProofLifecycle.apply(c, rid, "PROOF_CONFIRM", Outcome.OK).status_after == "NATIVE_ACCEPTED"


def test_retry_never_reconsumes_economic_event(migrated_db_url, engine, queue):
    rid = _seed_request(migrated_db_url, "req-4")
    conn = psycopg2.connect(_dsn(migrated_db_url))
    try:
        insert_artifact(conn, ulid("art-4"), rid)
        insert_verification(conn, ulid("ver-4"), rid, ulid("art-4"))
        run(conn, "UPDATE proof_requests SET status = 'NATIVE_ACCEPTED' WHERE proof_request_id = %s", (rid,))
    finally:
        conn.close()
    kind = "EVIDENCE_CONSUME"
    job_id = queue.enqueue(kind, {"proof_request_id": rid}, job_key(kind, rid), max_attempts=5)
    consumed_calls = {"n": 0}

    def consume(cx, job):
        """Insert the consumption (idempotent on the unique keys), then advance; crash once after the insert."""
        consumed_calls["n"] += 1
        params = consumption_params(ulid("con-4"), h32("src-4"), "mockdepin-testonly/acct-A/OBLIGATION/inv-4", ulid("ver-4"))
        # positional -> named binding for SQLAlchemy text()
        sql = consumption_sql()
        for i in range(sql.count("%s")):
            sql = sql.replace("%s", f":p{i}", 1)
        try:
            with cx.begin_nested():
                cx.execute(text(sql), {f"p{i}": v for i, v in enumerate(params)})
        except IntegrityError:
            pass  # already consumed by an earlier attempt: economic dedup by unique key, not by the queue
        if consumed_calls["n"] == 1:
            raise TransientError("crashed after consuming")  # rolls back this attempt entirely
        ProofLifecycle.apply(cx, job.payload["proof_request_id"], job.kind, Outcome.OK)

    w = Worker(engine, queue, {kind: consume}, worker_id="w1")
    job = queue.claim("w1", [kind])
    assert w.run_one(job) == "PENDING"
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM evidence_consumptions")).scalar_one() == 0, "attempt 1 rolled back atomically"
    # simulate the variant where the consumption committed separately before the crash
    conn = psycopg2.connect(_dsn(migrated_db_url))
    try:
        run(conn, consumption_sql(), consumption_params(ulid("con-4"), h32("src-4"), "mockdepin-testonly/acct-A/OBLIGATION/inv-4", ulid("ver-4")))
    finally:
        conn.close()
    with engine.begin() as c:
        c.execute(text("UPDATE jobs SET next_run_at = now() WHERE job_id = :id"), {"id": job_id})
    job = queue.claim("w1", [kind])
    assert job is not None and job.attempt == 2
    assert w.run_one(job) == "SUCCEEDED"
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM evidence_consumptions")).scalar_one() == 1, "retry did not re-consume"
        assert c.execute(text("SELECT status FROM proof_requests WHERE proof_request_id = :id"), {"id": rid}).scalar_one() == "CONSUMED"
    assert consumed_calls["n"] == 2


def test_proof_invalid_and_expired_are_terminal_and_dead_letter_the_job(migrated_db_url, engine, queue):
    for i, (tag, outcome) in enumerate((("req-5", Outcome.INVALID), ("req-6", Outcome.EXPIRED))):
        rid = _seed_request(migrated_db_url, tag, seed=(i == 0))
        job_id = queue.enqueue("PROOF_WAIT_ATTESTATION", {"proof_request_id": rid}, job_key("PROOF_WAIT_ATTESTATION", rid))
        w = Worker(engine, queue, {"PROOF_WAIT_ATTESTATION": lambda cx, job, o=outcome: ProofLifecycle.apply(cx, job.payload["proof_request_id"], job.kind, o)}, worker_id="w")
        assert w.run_one(queue.claim("w", ["PROOF_WAIT_ATTESTATION"])) == "DEAD"
        with engine.connect() as c:
            assert c.execute(text("SELECT status FROM proof_requests WHERE proof_request_id = :id"), {"id": rid}).scalar_one() == str(outcome)
        assert _state(engine, job_id)[0] == "DEAD"
    with pytest.raises(ValueError), engine.begin() as c:
        ProofLifecycle.apply(c, rid, "PROOF_SIGN_FALLBACK", Outcome.OK)
