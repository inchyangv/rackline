"""
Borrower claim (mainnet-grade mapping) helpers.

We avoid server-side storage by issuing an HMAC-signed token that contains:
- borrower (EVM)
- btc_address
- nonce
- chain_id
- issued_at / expires_at
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_decode(s: str) -> bytes:
    pad = "=" * ((4 - (len(s) % 4)) % 4)
    return base64.urlsafe_b64decode((s + pad).encode("ascii"))


@dataclass(frozen=True)
class ClaimPayload:
    version: int
    borrower: str
    btc_address: str
    nonce: str
    chain_id: int
    issued_at: int
    expires_at: int

    def to_json_bytes(self) -> bytes:
        obj = {
            "v": self.version,
            "borrower": self.borrower,
            "btc_address": self.btc_address,
            "nonce": self.nonce,
            "chain_id": self.chain_id,
            "iat": self.issued_at,
            "exp": self.expires_at,
        }
        # Sort keys to make token deterministic.
        return json.dumps(obj, separators=(",", ":"), sort_keys=True).encode("utf-8")

    @staticmethod
    def from_json_bytes(raw: bytes) -> "ClaimPayload":
        obj = json.loads(raw.decode("utf-8"))
        return ClaimPayload(
            version=int(obj["v"]),
            borrower=str(obj["borrower"]),
            btc_address=str(obj["btc_address"]),
            nonce=str(obj["nonce"]),
            chain_id=int(obj["chain_id"]),
            issued_at=int(obj["iat"]),
            expires_at=int(obj["exp"]),
        )


def build_claim_message(payload: ClaimPayload) -> str:
    # IMPORTANT: this string must remain stable, because both BTC/EVM signatures use it.
    return (
        "HashCredit Borrower Claim\n"
        f"Borrower EVM: {payload.borrower}\n"
        f"BTC Address: {payload.btc_address}\n"
        f"Nonce: {payload.nonce}\n"
        f"Chain ID: {payload.chain_id}\n"
        f"Issued At: {payload.issued_at}\n"
        f"Expires At: {payload.expires_at}\n"
    )


def issue_claim_token(*, secret: str, borrower: str, btc_address: str, chain_id: int, ttl_seconds: int) -> tuple[str, ClaimPayload]:
    now = int(time.time())
    payload = ClaimPayload(
        version=1,
        borrower=borrower,
        btc_address=btc_address,
        nonce=secrets.token_urlsafe(16),
        chain_id=chain_id,
        issued_at=now,
        expires_at=now + max(60, int(ttl_seconds)),
    )

    body = payload.to_json_bytes()
    mac = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    token = f"{_b64url_encode(body)}.{_b64url_encode(mac)}"
    return token, payload


def verify_claim_token(*, secret: str, token: str, now: int | None = None) -> ClaimPayload:
    if "." not in token:
        raise ValueError("Invalid token format")
    body_b64, mac_b64 = token.split(".", 1)
    body = _b64url_decode(body_b64)
    mac = _b64url_decode(mac_b64)

    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    if not hmac.compare_digest(mac, expected):
        raise ValueError("Invalid token signature")

    payload = ClaimPayload.from_json_bytes(body)
    now_ts = int(time.time()) if now is None else int(now)
    if payload.expires_at < now_ts:
        raise ValueError("Token expired")
    if payload.issued_at > now_ts + 60:
        raise ValueError("Token issued in the future")
    return payload

