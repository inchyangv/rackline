"""ERC-1271 checker protocol. Production binds an RPC-backed checker; tests inject a fake (no live RPC)."""

from __future__ import annotations

from typing import Protocol


class Erc1271Checker(Protocol):
    async def is_valid_signature(self, wallet: str, digest: bytes, signature: bytes) -> bool:
        """True iff `wallet` (a contract) returns the ERC-1271 magic value for (digest, signature)."""


class RejectAllErc1271Checker:
    """Default when no RPC checker is configured: contract wallets cannot log in (fail closed)."""

    async def is_valid_signature(self, wallet: str, digest: bytes, signature: bytes) -> bool:
        return False


class FakeErc1271Checker:
    """TEST_ONLY: accepts exactly the (wallet, digest, signature) triples registered in advance."""

    def __init__(self) -> None:
        self._accepted: set[tuple[str, bytes, bytes]] = set()
        self.calls = 0

    def accept(self, wallet: str, digest: bytes, signature: bytes) -> None:
        self._accepted.add((wallet.lower(), digest, signature))

    async def is_valid_signature(self, wallet: str, digest: bytes, signature: bytes) -> bool:
        self.calls += 1
        return (wallet.lower(), digest, signature) in self._accepted
