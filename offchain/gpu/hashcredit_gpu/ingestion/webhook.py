"""
Signed webhook ingress (transport-agnostic). Verification happens before any DB work:

    signature = hex(HMAC-SHA256(secret, f"{timestamp}.{body}"))         (header `X-Rackline-Signature`)
    timestamp = unix seconds (header `X-Rackline-Timestamp`), |now - timestamp| <= max_skew
    len(body) <= max_bytes

Replay protection is DB-backed, not in memory: the raw observation's (provider, origin, payload_hash) unique key
makes a re-delivered body a no-op (no second raw row, outbox event, proof candidate or job). Accepted payloads
go through exactly the collector's transactional path. A webhook is a provider assertion (OFFCHAIN_ASSERTION);
it never advances a native status and never touches receivables.

The HTTP route itself (FastAPI, GPU-018 middleware/limits) is mounted by GPU-045; this module is what that
route calls.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from ..providers.types import RevenueObservation, SettlementObservation
from .collector import Collector
from .proof_candidates import candidate_from_settlement, emit_candidate

SIGNATURE_HEADER = "x-rackline-signature"
TIMESTAMP_HEADER = "x-rackline-timestamp"
DEFAULT_MAX_BYTES = 256 * 1024
DEFAULT_MAX_SKEW_SECONDS = 300


class WebhookError(ValueError):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


def sign_webhook(secret: bytes, timestamp: int, body: bytes) -> str:
    return hmac.new(secret, f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()


def verify_webhook(
    secret: bytes,
    headers: Mapping[str, str],
    body: bytes,
    *,
    now: datetime | None = None,
    max_skew_seconds: int = DEFAULT_MAX_SKEW_SECONDS,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> dict[str, Any]:
    """Return the parsed JSON payload or raise WebhookError. Size → timestamp → signature → JSON, in that order."""
    if len(body) > max_bytes:
        raise WebhookError("PAYLOAD_TOO_LARGE", f"{len(body)} > {max_bytes}")
    hdr = {k.lower(): v for k, v in headers.items()}
    ts_raw = hdr.get(TIMESTAMP_HEADER)
    sig = hdr.get(SIGNATURE_HEADER)
    if not ts_raw or not sig:
        raise WebhookError("MISSING_HEADERS")
    try:
        ts = int(ts_raw)
    except ValueError as e:
        raise WebhookError("BAD_TIMESTAMP") from e
    now_s = int((now or datetime.now(UTC)).timestamp())
    if abs(now_s - ts) > max_skew_seconds:
        raise WebhookError("STALE_TIMESTAMP", f"skew {abs(now_s - ts)}s > {max_skew_seconds}s")
    expected = sign_webhook(secret, ts, body)
    if not hmac.compare_digest(expected, sig.lower()):
        raise WebhookError("BAD_SIGNATURE")
    try:
        payload = json.loads(body)
    except ValueError as e:
        raise WebhookError("BAD_JSON") from e
    if not isinstance(payload, dict):
        raise WebhookError("BAD_JSON", "top-level object required")
    return payload


@dataclass(frozen=True)
class WebhookOutcome:
    observation_id: str
    stored: bool  # False == replay / duplicate (no side effects)
    proof_request_id: str | None


class WebhookReceiver:
    """Verifies, parses into the provider observation types, and stores via the collector's transactional path."""

    def __init__(
        self,
        collector: Collector,
        secret: bytes,
        *,
        max_skew_seconds: int = DEFAULT_MAX_SKEW_SECONDS,
        max_bytes: int = DEFAULT_MAX_BYTES,
    ) -> None:
        self.collector = collector
        self.secret = secret
        self.max_skew = max_skew_seconds
        self.max_bytes = max_bytes

    def receive(
        self, headers: Mapping[str, str], body: bytes, *, now: datetime | None = None
    ) -> WebhookOutcome:
        payload = verify_webhook(
            self.secret,
            headers,
            body,
            now=now,
            max_skew_seconds=self.max_skew,
            max_bytes=self.max_bytes,
        )
        kind = payload.get("kind")
        data = payload.get("observation")
        if kind not in ("revenue", "settlement") or not isinstance(data, dict):
            raise WebhookError(
                "BAD_KIND", "kind must be revenue|settlement with an observation object"
            )
        slug = self.collector.cfg.provider_id
        try:
            obs = RevenueObservation(**data) if kind == "revenue" else SettlementObservation(**data)
        except ValidationError as e:
            raise WebhookError("BAD_OBSERVATION", str(e)) from e
        if obs.provider_slug != slug or obs.account.provider_slug != slug:
            raise WebhookError("PROVIDER_MISMATCH", f"{obs.provider_slug} != {slug}")
        stream = "revenue" if kind == "revenue" else "settlements"
        with self.collector.engine.begin() as cx:
            oid, new = self.collector.store_observation(cx, obs, origin="WEBHOOK", stream=stream)
            rid = None
            if new and isinstance(obs, SettlementObservation):
                cand = candidate_from_settlement(obs, self.collector.cfg.proof_env, slug)
                if cand:
                    rid = emit_candidate(
                        cx,
                        cand,
                        self.collector.cfg.proof_env,
                        self.collector.queue,
                        raw_observation_id=oid,
                    )
        return WebhookOutcome(observation_id=oid, stored=new, proof_request_id=rid)
