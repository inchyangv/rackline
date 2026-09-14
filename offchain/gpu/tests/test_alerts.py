"""Operator alerts: deduplicated, resolved once, webhook-agnostic, never fatal."""

import json

from hashcredit_gpu.monitoring.alerts import Alerter


def capture():
    sent = []
    alerter = Alerter(service="gpu-indexer", webhook_url="https://hooks.example.test/x", repeat_seconds=900)
    alerter._transport = lambda url, body: sent.append((url, json.loads(body)))
    return alerter, sent


def test_alert_is_deduplicated_until_resolved_and_carries_slack_and_discord_fields():
    alerter, sent = capture()
    assert alerter.alert("indexer-stalled", "no sync for 130 s", now=1000) is True
    assert alerter.alert("indexer-stalled", "no sync for 250 s", now=1100) is False  # inside the repeat window
    assert alerter.alert("indexer-stalled", "no sync for 1000 s", now=2000) is True  # window elapsed
    assert alerter.alert("indexer-stalled", "recovered", resolved=True, now=2100) is True
    assert alerter.alert("indexer-stalled", "recovered again", resolved=True, now=2200) is False  # nothing open
    assert alerter.alert("indexer-stalled", "no sync for 5 s", now=2300) is True  # reported afresh after resolve
    first = sent[0][1]
    assert first["text"] == first["content"] == "⚠️ [gpu-indexer] no sync for 130 s"
    assert (first["service"], first["key"], first["severity"], first["resolved"]) == ("gpu-indexer", "indexer-stalled", "warning", False)
    assert sent[2][1]["text"].startswith("✅ [gpu-indexer] recovered") and sent[2][1]["resolved"] is True
    assert len(sent) == 4


def test_unconfigured_or_failing_webhook_never_raises():
    quiet = Alerter.from_env("gpu-monitor", environ={})
    assert quiet.configured is False
    assert quiet.alert("k", "logged only", severity="critical") is True
    insecure = Alerter.from_env("gpu-monitor", environ={"GPU_ALERT_WEBHOOK_URL": "http://plain.example.test/hook"})
    assert insecure.configured is False  # https only
    failing = Alerter(service="gpu-monitor", webhook_url="https://hooks.example.test/x")

    def boom(url, body):
        raise OSError("connection refused")

    failing._transport = boom
    assert failing.alert("k", "delivery failure is logged, not raised") is True
    configured = Alerter.from_env("gpu-monitor", environ={"GPU_ALERT_WEBHOOK_URL": "https://hooks.example.test/y", "GPU_ALERT_REPEAT_SECONDS": "60"})
    assert configured.configured and configured.repeat_seconds == 60
