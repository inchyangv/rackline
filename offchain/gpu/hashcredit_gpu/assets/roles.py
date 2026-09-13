"""Role gates for GPU-017 transitions (GPU-013 §1: operator registers, underwriter reviews)."""

from __future__ import annotations

from ..domain import enums as E
from .errors import Forbidden

REGISTER_ROLES = frozenset({E.Role.OPERATOR.value, E.Role.SYSTEM.value})
REVIEW_ROLES = frozenset({E.Role.UNDERWRITER.value})
RELEASE_ROLES = frozenset({E.Role.UNDERWRITER.value, E.Role.OPERATOR.value})


def require(role: str, allowed: frozenset[str], action: str) -> str:
    if role not in {r.value for r in E.Role}:
        raise Forbidden(f"unknown role {role!r} for {action}")
    if role not in allowed:
        raise Forbidden(f"role {role!r} may not {action}")
    return role
