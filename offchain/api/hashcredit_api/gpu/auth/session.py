"""
HMAC-signed bearer sessions.

Bearer-only by design: no cookies, therefore no CSRF surface; the token lives in the Authorization header
and browsers never attach it automatically. The signing secret comes from a secret ref (GPU_SESSION_SECRET
env) and is registered with the log redactor; it is never returned or logged.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode((s + pad).encode("ascii"))


@dataclass(frozen=True)
class SessionPayload:
    wallet: str
    chain_id: int
    borrower_id: str | None
    roles: tuple[str, ...]
    role_epochs: dict[str, int]
    issued_at: int
    expires_at: int
    jti: str

    def to_json(self) -> bytes:
        return json.dumps(
            {
                "sub": self.wallet,
                "cid": self.chain_id,
                "brw": self.borrower_id,
                "roles": list(self.roles),
                "ep": self.role_epochs,
                "iat": self.issued_at,
                "exp": self.expires_at,
                "jti": self.jti,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    @staticmethod
    def from_json(raw: bytes) -> "SessionPayload":
        d = json.loads(raw)
        return SessionPayload(
            wallet=str(d["sub"]),
            chain_id=int(d["cid"]),
            borrower_id=d.get("brw"),
            roles=tuple(str(r) for r in d["roles"]),
            role_epochs={str(k): int(v) for k, v in d["ep"].items()},
            issued_at=int(d["iat"]),
            expires_at=int(d["exp"]),
            jti=str(d["jti"]),
        )


def issue_session(*, secret: str, payload_fields: dict, ttl_seconds: int) -> tuple[str, SessionPayload]:
    now = int(time.time())
    payload = SessionPayload(
        issued_at=now,
        expires_at=now + ttl_seconds,
        jti=secrets.token_hex(16),
        **payload_fields,
    )
    body = payload.to_json()
    mac = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    return f"{_b64e(body)}.{_b64e(mac)}", payload


def parse_session(*, secret: str, token: str, now: int | None = None) -> SessionPayload | None:
    """Return the payload if the MAC and expiry check out, else None (role epochs are checked by the caller)."""
    try:
        body_b64, mac_b64 = token.split(".", 1)
        body = _b64d(body_b64)
        mac = _b64d(mac_b64)
    except Exception:
        return None
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    if not hmac.compare_digest(mac, expected):
        return None
    try:
        payload = SessionPayload.from_json(body)
    except Exception:
        return None
    if payload.expires_at <= (now if now is not None else int(time.time())):
        return None
    return payload
