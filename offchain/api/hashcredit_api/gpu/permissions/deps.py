"""
FastAPI dependencies: bearer session → Principal, role gates, object-level access.

Denial semantics (domain-model §11 ErrorCode):
  - no/invalid/expired session, or a session whose role epochs are stale → 401 UNAUTHENTICATED
  - authenticated but role missing for a role-gated mutation           → 403 FORBIDDEN_SCOPE
  - object read/write on an id the principal does not own              → 404 NOT_FOUND (same as missing)
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Request

from ..errors import forbidden_scope, not_configured, not_found, unauthenticated
from ..auth import roles as R
from ..auth.session import SessionPayload, parse_session

STAFF_READ_ROLES = frozenset({R.UNDERWRITER, R.OPERATOR, R.KEEPER, R.SERVICER, R.GUARDIAN, R.TREASURY})


@dataclass(frozen=True)
class Principal:
    wallet: str
    chain_id: int
    borrower_id: str | None
    roles: frozenset[str]
    session: SessionPayload

    def has(self, role: str) -> bool:
        return role in self.roles


def _runtime(request: Request):
    rt = getattr(request.app.state, "gpu", None)
    if rt is None:
        raise not_configured("GPU API runtime not mounted")
    return rt


def current_principal(request: Request) -> Principal:
    rt = _runtime(request)
    if rt.session_secret is None:
        raise not_configured("session auth not configured")
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise unauthenticated()
    payload = parse_session(secret=rt.session_secret, token=header[7:].strip())
    if payload is None:
        raise unauthenticated("invalid or expired session")
    if payload.chain_id != rt.chain_id:
        raise unauthenticated("session chain mismatch")
    # Revocation: every role the session carries must still be held at the same epoch.
    live_roles = rt.roles.roles_of(payload.wallet)
    for role in payload.roles:
        if role == R.BORROWER:
            continue  # derived from the wallet link, checked below
        if role not in live_roles or rt.roles.epoch(role) != payload.role_epochs.get(role, -1):
            raise unauthenticated("session role revoked")
    # Borrower identity is re-resolved live so a released wallet link ends access.
    borrower_id = rt.ownership.borrower_of_wallet(payload.wallet)
    if payload.borrower_id is not None and borrower_id != payload.borrower_id:
        raise unauthenticated("wallet link changed")
    if R.BORROWER in payload.roles and borrower_id is None:
        raise unauthenticated("wallet link released")
    return Principal(
        wallet=payload.wallet,
        chain_id=payload.chain_id,
        borrower_id=borrower_id,
        roles=frozenset(payload.roles),
        session=payload,
    )


def require_role(*allowed: str):
    def _dep(p: Principal = Depends(current_principal)) -> Principal:
        if not (p.roles & set(allowed)):
            raise forbidden_scope(f"requires one of {sorted(allowed)}")
        return p

    return _dep


def _owned_or_staff(p: Principal, owner: str | None) -> None:
    if p.roles & STAFF_READ_ROLES:
        if owner is None:
            raise not_found()
        return
    if owner is None or p.borrower_id is None or owner != p.borrower_id:
        raise not_found()


def borrower_access(borrowerId: str, request: Request, p: Principal = Depends(current_principal)) -> str:
    rt = _runtime(request)
    known = borrowerId in rt.known_borrowers
    _owned_or_staff(p, borrowerId if known else None)
    return borrowerId


def account_access(accountKey: str, request: Request, p: Principal = Depends(current_principal)) -> str:
    rt = _runtime(request)
    _owned_or_staff(p, rt.ownership.borrower_of_account(accountKey))
    return accountKey


def facility_access(facilityId: str, request: Request, p: Principal = Depends(current_principal)) -> str:
    rt = _runtime(request)
    _owned_or_staff(p, rt.ownership.borrower_of_facility(facilityId))
    return facilityId
