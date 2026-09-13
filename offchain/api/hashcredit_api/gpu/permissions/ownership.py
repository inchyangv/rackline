"""Who owns which object. The DB-backed resolver (GPU-016/017) replaces the in-memory one."""

from __future__ import annotations

import threading
from typing import Protocol


class OwnershipResolver(Protocol):
    def borrower_of_wallet(self, wallet: str) -> str | None: ...

    def borrower_of_account(self, account_key: str) -> str | None: ...

    def borrower_of_facility(self, facility_id: str) -> str | None: ...


class InMemoryOwnership:
    def __init__(self) -> None:
        self._wallets: dict[str, str] = {}
        self._accounts: dict[str, str] = {}
        self._facilities: dict[str, str] = {}
        self._lock = threading.Lock()

    def link_wallet(self, wallet: str, borrower_id: str) -> None:
        with self._lock:
            existing = self._wallets.get(wallet.lower())
            if existing and existing != borrower_id:
                raise ValueError("wallet already linked to another borrower; release first")
            self._wallets[wallet.lower()] = borrower_id

    def set_account(self, account_key: str, borrower_id: str) -> None:
        with self._lock:
            self._accounts[account_key.lower()] = borrower_id

    def set_facility(self, facility_id: str, borrower_id: str) -> None:
        with self._lock:
            self._facilities[facility_id] = borrower_id

    def borrower_of_wallet(self, wallet: str) -> str | None:
        return self._wallets.get(wallet.lower())

    def borrower_of_account(self, account_key: str) -> str | None:
        return self._accounts.get(account_key.lower())

    def borrower_of_facility(self, facility_id: str) -> str | None:
        return self._facilities.get(facility_id)
