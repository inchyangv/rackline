"""The indexer worker retries transient chain movement, alerts on stalls and crashes, and resolves on recovery."""

import json

import pytest

from hashcredit_gpu.monitoring.alerts import Alerter
from hashcredit_gpu.projections.indexer import FinalizedReorg, TransientChainChange
from hashcredit_prover.gpu.chain_indexer import run_loop


class FakeIndexer:
    def __init__(self, outcomes):
        self.outcomes, self.calls, self.rpc = list(outcomes), 0, None

    def sync(self, deployment_id):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def harness():
    sent = []
    alerter = Alerter(service="gpu-indexer", webhook_url="https://hooks.example.test/x")
    alerter._transport = lambda url, body: sent.append(json.loads(body))
    sleeps, emitted = [], []
    clock = {"t": 0.0}

    def sleep(seconds):
        sleeps.append(seconds)
        clock["t"] += seconds

    return alerter, sent, sleeps, emitted, sleep, (lambda: clock["t"])


def test_transient_chain_change_is_retried_with_backoff_then_alerted_and_resolved():
    alerter, sent, sleeps, emitted, sleep, clock = harness()
    indexer = FakeIndexer([TransientChainChange("chain changed before index commit")] * 6 + [{"lag": 0}, {"lag": 0}])
    with pytest.raises(IndexError):  # outcomes exhausted: the loop kept running after recovery
        run_loop(indexer, "dep", interval=10, alerter=alerter, alert_after=120, sleep=sleep, clock=clock,
                 emit=lambda result, flush: emitted.append(result))
    assert sleeps[:6] == [10, 20, 40, 60, 60, 60]  # exponential, capped at 60 s
    assert emitted == [{"lag": 0}, {"lag": 0}]
    # one stall alert (after 120 s of failures, deduplicated afterwards), one resolve, then the crash alert for the exhausted fake
    assert [(a["key"], a["resolved"]) for a in sent] == [("indexer-stalled", False), ("indexer-stalled", True), ("indexer-crash", False)]
    assert sent[0]["text"].startswith("⚠️ [gpu-indexer] indexer has not completed a sync for 130 s (5 attempts")


def test_finalized_reorg_and_integrity_failures_alert_critical_and_exit():
    alerter, sent, sleeps, emitted, sleep, clock = harness()
    with pytest.raises(FinalizedReorg):
        run_loop(FakeIndexer([FinalizedReorg("canonical chain changed at finalized block 7")]), "dep", alerter=alerter, sleep=sleep, clock=clock, emit=lambda *a, **k: None)
    with pytest.raises(ValueError):
        run_loop(FakeIndexer([ValueError("debt event conservation discrepancy")]), "dep", alerter=alerter, sleep=sleep, clock=clock, emit=lambda *a, **k: None)
    assert sent[0]["severity"] == "critical" and "finalized reorg" in sent[0]["text"] and sent[0]["key"] == "indexer-finalized-reorg"
    assert sent[1]["severity"] == "critical" and "conservation" in sent[1]["text"] and sent[1]["key"] == "indexer-crash"
    assert sleeps == []  # no retry: the process exits and the platform restart policy brings it back


def test_once_mode_raises_transient_errors_for_the_operator():
    alerter, sent, sleeps, emitted, sleep, clock = harness()
    with pytest.raises(TransientChainChange):
        run_loop(FakeIndexer([TransientChainChange("chain changed while indexing; retry atomically")]), "dep", once=True, alerter=alerter, sleep=sleep, clock=clock)
    assert run_loop(FakeIndexer([{"lag": 3}]), "dep", once=True, alerter=alerter, sleep=sleep, clock=clock, emit=lambda *a, **k: None) == {"lag": 3}
