"""Partner effects must be observed independently of a successful acknowledgement."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from hashcredit_gpu.control.executor import ControlExecutor, EffectObservation, WriteBinding
from hashcredit_gpu.db.ledgers import Outbox
from hashcredit_gpu.db.models import ProviderAccount
from hashcredit_gpu.jobs import TerminalError, Worker
from hashcredit_gpu.providers import MockProviderAdapter

from .test_provider_contract import ACCT, load_fixture
from .test_schema import seed_base


class Effects:
    applied = False
    release = False

    def observe(self, _):
        return EffectObservation(self.applied, "doc://effect" if self.applied else None)

    def release_permitted(self, _):
        return self.release


@pytest.fixture
def setup(conn, migrated_db_url):
    seed_base(conn, provider_profile="LOCAL_MOCK")
    conn.commit()
    engine = create_engine(migrated_db_url)
    with Session(engine) as s, s.begin():
        s.get(ProviderAccount, ACCT.account_key).auth_scope = [
            "claim_revenue",
            "request_control_change",
        ]
    fixture = load_fixture()
    fixture["capabilities"].update(claim_revenue="SUPPORTED", request_control_change="SUPPORTED")
    adapter, effects = MockProviderAdapter(fixture), Effects()
    binding = WriteBinding(
        "mockdepin-testonly",
        "LOCAL_MOCK",
        "UNCONFIGURED",
        frozenset(["claim_revenue", "request_control_change"]),
        frozenset(["0x" + "12" * 20]),
        11155111,
        1000,
        "doc://approved-local",
        True,
    )
    executor = ControlExecutor(engine, adapter, binding, effects)
    action = {
        "actionId": "claim-1",
        "kind": "CLAIM",
        "providerAccountId": ACCT.account_key,
        "amount": {"amount": "10", "asset": adapter.identity().supported_assets[0].model_dump()},
        "reason": "approved recovery claim",
        "approvedBy": "local-treasury",
        "approvedRole": "treasury",
        "approvalRef": binding.approval_ref,
        "deadline": int(datetime.now(UTC).timestamp()) + 300,
    }
    yield engine, executor, action, effects
    engine.dispose()


def enqueue(engine, executor, action):
    with Session(engine) as s, s.begin():
        return executor.enqueue(s, action)


def retry(engine):
    with engine.begin() as cx:
        cx.execute(text("UPDATE jobs SET next_run_at = now()"))


def worker(engine, executor):
    return Worker(
        engine, executor.queue, {"PROVIDER_ACTION": executor.handle}, worker_id="effect-worker"
    )


def test_ack_not_effect_and_duplicate_request_does_not_repeat_write(setup):
    engine, executor, action, effects = setup
    assert enqueue(engine, executor, action) == enqueue(engine, executor, action)
    w = worker(engine, executor)
    assert w.run_once() == "PENDING"
    with Session(engine) as s:
        assert (
            s.scalar(
                select(func.count())
                .select_from(Outbox)
                .where(Outbox.event_type == "PROVIDER_ACTION_EFFECT_OBSERVED")
            )
            == 0
        )
    effects.applied = True
    retry(engine)
    assert w.run_once() == "SUCCEEDED"
    with Session(engine) as s:
        assert (
            s.scalar(
                select(func.count())
                .select_from(Outbox)
                .where(Outbox.event_type == "PROVIDER_ACTION_EFFECT_OBSERVED")
            )
            == 1
        )


def test_timeout_after_effect_reconciles_without_second_claim(setup):
    engine, executor, action, effects = setup
    count = []
    original = executor.adapter.claim_revenue

    def send(request):
        count.append(1)
        original(request)
        effects.applied = True
        raise TimeoutError("ack lost after provider applied request")

    executor.adapter.claim_revenue = send
    enqueue(engine, executor, action)
    w = worker(engine, executor)
    assert w.run_once() == "PENDING"
    retry(engine)
    assert w.run_once() == "SUCCEEDED"
    assert len(count) == 1


def test_revoked_scope_and_unauthorized_release_never_write(setup):
    engine, executor, action, _effects = setup
    enqueue(engine, executor, action)
    with Session(engine) as s, s.begin():
        s.get(ProviderAccount, ACCT.account_key).auth_scope = []
    assert worker(engine, executor).run_once() == "DEAD"
    with Session(engine) as s, s.begin():
        s.get(ProviderAccount, ACCT.account_key).auth_scope = ["request_control_change"]
        with pytest.raises(TerminalError, match="release blocked"):
            executor.enqueue(
                s,
                {
                    **action,
                    "kind": "RELEASE",
                    "receiver": "0x" + "12" * 20,
                    "receiverChainId": 11155111,
                },
            )


def test_read_credential_cannot_enqueue_claim(setup):
    engine, executor, action, effects = setup
    readonly = ControlExecutor(
        engine, executor.adapter, replace(executor.binding, credential_scope=frozenset()), effects
    )
    with Session(engine) as s, s.begin(), pytest.raises(TerminalError, match="scope"):
        readonly.enqueue(s, action)
