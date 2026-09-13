"""
Role registry with revocation epochs (GPU-013 §1).

A session snapshots the epoch of every role it carries; revoking a role bumps that role's epoch and the
wallet's membership, so every outstanding session that relied on it stops validating immediately.
"""

from __future__ import annotations

import threading
from typing import Protocol

BORROWER = "borrower"
LP = "lp"
UNDERWRITER = "underwriter"
OPERATOR = "operator"
KEEPER = "keeper"
GUARDIAN = "guardian"
TREASURY = "treasury"
SERVICER = "servicer"
REGISTRAR = "registrar"

ALL_ROLES = frozenset({BORROWER, LP, UNDERWRITER, OPERATOR, KEEPER, GUARDIAN, TREASURY, SERVICER, REGISTRAR})
# Separation of duties mirrored from ProtocolRoles: no wallet may hold two of these.
EXCLUSIVE = frozenset({UNDERWRITER, TREASURY, GUARDIAN})


class RoleRegistry(Protocol):
    def roles_of(self, wallet: str) -> frozenset[str]: ...

    def epoch(self, role: str) -> int: ...


class InMemoryRoleRegistry:
    def __init__(self) -> None:
        self._roles: dict[str, set[str]] = {}
        self._epochs: dict[str, int] = {r: 0 for r in ALL_ROLES}
        self._lock = threading.Lock()

    def grant(self, wallet: str, role: str) -> None:
        if role not in ALL_ROLES:
            raise ValueError(f"unknown role {role}")
        with self._lock:
            held = self._roles.setdefault(wallet.lower(), set())
            if role in EXCLUSIVE and (held & EXCLUSIVE) - {role}:
                raise ValueError(f"{wallet} already holds an exclusive role {sorted(held & EXCLUSIVE)}")
            held.add(role)

    def revoke(self, wallet: str, role: str) -> None:
        with self._lock:
            self._roles.get(wallet.lower(), set()).discard(role)
            self._epochs[role] = self._epochs.get(role, 0) + 1

    def rotate(self, role: str) -> None:
        with self._lock:
            self._epochs[role] = self._epochs.get(role, 0) + 1

    def roles_of(self, wallet: str) -> frozenset[str]:
        with self._lock:
            return frozenset(self._roles.get(wallet.lower(), set()))

    def epoch(self, role: str) -> int:
        with self._lock:
            return self._epochs.get(role, 0)
