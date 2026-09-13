"""One-time login challenges. The store interface is what GPU-016's DB-backed store will implement."""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Challenge:
    nonce: bytes  # 32 bytes, single use
    wallet: str  # checksum address
    chain_id: int
    app_domain: str
    borrower_hint: str
    issued_at: int
    expires_at: int


class ChallengeStore(Protocol):
    def put(self, challenge: Challenge) -> None: ...

    def take(self, nonce: bytes) -> Challenge | None:
        """Atomically remove and return the challenge; None if unknown or already taken (replay)."""


class InMemoryChallengeStore:
    def __init__(self, max_entries: int = 10_000) -> None:
        self._entries: dict[bytes, Challenge] = {}
        self._lock = threading.Lock()
        self._max = max_entries

    def put(self, challenge: Challenge) -> None:
        with self._lock:
            now = int(time.time())
            if len(self._entries) >= self._max:
                for k in [k for k, c in self._entries.items() if c.expires_at <= now]:
                    del self._entries[k]
            self._entries[challenge.nonce] = challenge

    def take(self, nonce: bytes) -> Challenge | None:
        with self._lock:
            return self._entries.pop(nonce, None)


def new_nonce() -> bytes:
    return secrets.token_bytes(32)
