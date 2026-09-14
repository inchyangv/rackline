"""
Operator alerts for the background services (indexer crash / stall, monitor findings).

Delivery is a webhook (`GPU_ALERT_WEBHOOK_URL`): the payload carries both Slack's `text` and Discord's
`content`, so an incoming-webhook URL of either kind works unchanged. Without a URL every alert is only
logged — the services never fail because alerting is unconfigured. Alerts are deduplicated per key for
`GPU_ALERT_REPEAT_SECONDS` (default 15 min) so a crash loop produces one message, not one per restart cycle;
a `resolved` alert clears the key so the next occurrence is reported again.

No secrets, keys or customer identifiers are ever placed in an alert: messages name services, deployment
ids, block numbers and exception classes only.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

SEVERITIES = ("info", "warning", "critical")


@dataclass
class Alerter:
    service: str
    webhook_url: str | None = None
    repeat_seconds: float = 900.0
    timeout_seconds: float = 5.0
    _last_sent: dict[str, float] = field(default_factory=dict)
    _transport = None  # test seam: callable(url, body: bytes) -> None

    @classmethod
    def from_env(cls, service: str, environ: dict | None = None) -> "Alerter":
        env = os.environ if environ is None else environ
        url = (env.get("GPU_ALERT_WEBHOOK_URL") or "").strip() or None
        if url and not url.startswith("https://"):
            log.warning("GPU_ALERT_WEBHOOK_URL ignored: only https webhooks are accepted")
            url = None
        repeat = float(env.get("GPU_ALERT_REPEAT_SECONDS") or 900)
        return cls(service=service, webhook_url=url, repeat_seconds=max(0.0, repeat))

    @property
    def configured(self) -> bool:
        return self.webhook_url is not None

    def alert(self, key: str, message: str, *, severity: str = "warning", resolved: bool = False, now: float | None = None) -> bool:
        """Send one deduplicated alert; returns True when a message was actually delivered (or logged as such)."""
        if severity not in SEVERITIES:
            raise ValueError("unknown alert severity")
        at = time.time() if now is None else now
        if resolved:
            if key not in self._last_sent:
                return False  # nothing was reported, nothing to resolve
            self._last_sent.pop(key, None)
        else:
            last = self._last_sent.get(key)
            if last is not None and at - last < self.repeat_seconds:
                return False
            self._last_sent[key] = at
        marker = {"info": "ℹ️", "warning": "⚠️", "critical": "🚨"}[severity]
        text = f"{'✅' if resolved else marker} [{self.service}] {message}"
        log.log(logging.INFO if resolved or severity == "info" else logging.ERROR, "ALERT %s", text)
        if self.webhook_url is None:
            return True
        body = json.dumps({"text": text, "content": text, "service": self.service, "key": key, "severity": severity, "resolved": resolved}).encode()
        try:
            (self._transport or self._post)(self.webhook_url, body)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            # Alerting must never take a service down; the failure itself is logged for the operator.
            log.warning("alert webhook delivery failed (%s)", type(exc).__name__)
        return True

    def _post(self, url: str, body: bytes) -> None:
        request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:  # noqa: S310 - https enforced above
            if response.status >= 300:
                raise ValueError(f"webhook status {response.status}")
