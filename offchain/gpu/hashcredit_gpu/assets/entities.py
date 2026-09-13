"""
Provider account ↔ borrower / legal entity linkage with review state and history.

A link is registration only. It never changes `borrowers.underwriting_status`, never creates a facility and
never raises a control grade. Re-linking to another borrower requires the live link to be released first;
the new link records `previous_link_id` so the from/to/at chain is auditable.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.assets_models import ProviderAccountLink
from ..db.models import Borrower, ProviderAccount
from .errors import InvalidState, NotFound
from .roles import REGISTER_ROLES, RELEASE_ROLES, REVIEW_ROLES, require


def _now() -> datetime:
    return datetime.now(UTC)


def active_link(session: Session, provider_account_id: str) -> ProviderAccountLink | None:
    return session.scalar(
        select(ProviderAccountLink).where(
            ProviderAccountLink.provider_account_id == provider_account_id,
            ProviderAccountLink.released_at.is_(None),
        )
    )


def link_history(session: Session, provider_account_id: str) -> list[ProviderAccountLink]:
    return list(
        session.scalars(
            select(ProviderAccountLink)
            .where(ProviderAccountLink.provider_account_id == provider_account_id)
            .order_by(ProviderAccountLink.id)
        )
    )


def link_account(
    session: Session,
    *,
    provider_account_id: str,
    borrower_id: str,
    by_role: str,
    provenance: dict | None = None,
) -> ProviderAccountLink:
    """Register the current borrower binding of a provider account (state REGISTERED)."""
    require(by_role, REGISTER_ROLES, "link a provider account")
    account = session.get(ProviderAccount, provider_account_id)
    if account is None:
        raise NotFound(f"provider account {provider_account_id}")
    borrower = session.get(Borrower, borrower_id)
    if borrower is None:
        raise NotFound(f"borrower {borrower_id}")
    if account.borrower_id != borrower_id:
        raise InvalidState("provider account is bound to another borrower; release and relink instead")
    if active_link(session, provider_account_id) is not None:
        raise InvalidState("provider account already has a live link")
    link = ProviderAccountLink(
        provider_account_id=provider_account_id,
        borrower_id=borrower_id,
        legal_entity_id=borrower.legal_entity_id,
        linked_by=by_role,
        provenance=provenance or {},
    )
    session.add(link)
    session.flush()
    return link


def review_link(
    session: Session, *, link_id: int, verdict: str, by_role: str, review_ref: str | None = None
) -> ProviderAccountLink:
    """Underwriter verdict on the linkage evidence. Verifying a link is not borrower approval."""
    require(by_role, REVIEW_ROLES, "review a provider account link")
    if verdict not in ("VERIFIED", "REJECTED"):
        raise InvalidState(f"verdict must be VERIFIED or REJECTED, got {verdict!r}")
    link = session.get(ProviderAccountLink, link_id)
    if link is None:
        raise NotFound(f"link {link_id}")
    if link.released_at is not None:
        raise InvalidState("released link cannot be reviewed")
    if link.review_state != "REGISTERED":
        raise InvalidState(f"link already reviewed ({link.review_state})")
    link.review_state = verdict
    link.reviewed_by = by_role
    link.reviewed_at = _now()
    link.review_ref = review_ref
    session.flush()
    return link


def release_link(session: Session, *, provider_account_id: str, by_role: str, reason: str) -> ProviderAccountLink:
    require(by_role, RELEASE_ROLES, "release a provider account link")
    link = active_link(session, provider_account_id)
    if link is None:
        raise NotFound(f"no live link for {provider_account_id}")
    link.released_at = _now()
    link.release_reason = reason
    session.flush()
    return link


def relink_account(
    session: Session,
    *,
    provider_account_id: str,
    new_borrower_id: str,
    by_role: str,
    provenance: dict | None = None,
) -> ProviderAccountLink:
    """Move an account to another borrower: the previous link must already be released (from/to/at kept)."""
    require(by_role, REGISTER_ROLES, "relink a provider account")
    if active_link(session, provider_account_id) is not None:
        raise InvalidState("release the live link before relinking to another borrower")
    history = link_history(session, provider_account_id)
    previous = history[-1] if history else None
    account = session.get(ProviderAccount, provider_account_id)
    if account is None:
        raise NotFound(f"provider account {provider_account_id}")
    borrower = session.get(Borrower, new_borrower_id)
    if borrower is None:
        raise NotFound(f"borrower {new_borrower_id}")
    account.borrower_id = new_borrower_id
    link = ProviderAccountLink(
        provider_account_id=provider_account_id,
        borrower_id=new_borrower_id,
        legal_entity_id=borrower.legal_entity_id,
        linked_by=by_role,
        previous_link_id=previous.id if previous else None,
        provenance={
            **(provenance or {}),
            "from": previous.borrower_id if previous else None,
            "to": new_borrower_id,
            "at": _now().isoformat(),
        },
    )
    session.add(link)
    session.flush()
    return link
