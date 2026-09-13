"""
Priority / lien / lease flags with document references, facility encumbrances and the eligibility decision.

`eligibility()` is the only place that may set `gpu_assets.eligible`, and it is false unless: the asset is
ACTIVE, ownership review is VERIFIED (and ownership is OWNED, or LEASED with a lease-consent document), no
review flag is open, no third-party lien/pledge/assignment is open ahead of us, and no *other* facility holds
an open encumbrance on it. Documents are pointers + hashes (never contents) and are review inputs only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import AssetEncumbrance, CustodyDocument, Facility
from . import registry
from .errors import InvalidState, NotFound
from .roles import REGISTER_ROLES, REVIEW_ROLES, require

OUR_HOLDER_PREFIX = "facility:"
THIRD_PARTY_KINDS = ("LIEN", "PLEDGE", "ASSIGNMENT")


def _now() -> datetime:
    return datetime.now(UTC)


def open_encumbrances(session: Session, asset_id: str) -> list[AssetEncumbrance]:
    return list(
        session.scalars(
            select(AssetEncumbrance)
            .where(AssetEncumbrance.asset_id == asset_id, AssetEncumbrance.status == "OPEN")
            .order_by(AssetEncumbrance.priority, AssetEncumbrance.encumbrance_id)
        )
    )


def open_facility_encumbrance(session: Session, asset_id: str) -> AssetEncumbrance | None:
    return session.scalar(
        select(AssetEncumbrance).where(
            AssetEncumbrance.asset_id == asset_id,
            AssetEncumbrance.status == "OPEN",
            AssetEncumbrance.facility_id.is_not(None),
        )
    )


def record_third_party_right(
    session: Session,
    *,
    encumbrance_id: str,
    asset_id: str,
    holder: str,
    kind: str,
    priority: int,
    document_ref: str,
    by_role: str,
    valid_from: datetime | None = None,
) -> AssetEncumbrance:
    """A lien/lease/pledge held by someone else, as reviewed from documents. Makes the asset ineligible."""
    require(by_role, REVIEW_ROLES, "record a third-party right")
    if holder.startswith(OUR_HOLDER_PREFIX):
        raise InvalidState("use assign_to_facility for our own encumbrances")
    registry._get(session, asset_id)
    row = AssetEncumbrance(
        encumbrance_id=encumbrance_id,
        asset_id=asset_id,
        holder=holder,
        priority=priority,
        kind=kind,
        document_ref=document_ref,
        valid_from=valid_from or _now(),
    )
    session.add(row)
    session.flush()
    registry.raise_flag(
        session,
        asset_id,
        "PRIORITY_CONFLICT" if kind in THIRD_PARTY_KINDS else "LEASE_UNVERIFIED",
        {"encumbranceId": encumbrance_id, "holder": holder, "kind": kind, "priority": priority},
    )
    return row


def attach_document(
    session: Session, *, asset_id: str, kind: str, document_ref: str, document_hash: str | None, by_role: str
) -> CustodyDocument:
    """Store a pointer + hash to a custody/lease/ownership document. Storing it decides nothing."""
    require(by_role, REGISTER_ROLES | REVIEW_ROLES, "attach a document")
    registry._get(session, asset_id)
    doc = CustodyDocument(asset_id=asset_id, kind=kind, document_ref=document_ref, document_hash=document_hash)
    session.add(doc)
    session.flush()
    return doc


def has_document(session: Session, asset_id: str, kind: str) -> bool:
    return session.scalar(select(CustodyDocument.id).where(CustodyDocument.asset_id == asset_id, CustodyDocument.kind == kind)) is not None


@dataclass
class Eligibility:
    asset_id: str
    eligible: bool
    reasons: list[str] = field(default_factory=list)


def eligibility(session: Session, asset_id: str, *, for_facility_id: str | None = None) -> Eligibility:
    """Compute and persist eligibility. Reasons list every blocking fact (none are silently overridden)."""
    asset = registry._get(session, asset_id)
    reasons: list[str] = []
    if asset.status != "ACTIVE":
        reasons.append(f"status={asset.status}")
    if asset.ownership_review != "VERIFIED":
        reasons.append(f"ownershipReview={asset.ownership_review}")
    if asset.ownership == "UNKNOWN":
        reasons.append("ownership=UNKNOWN")
    if asset.ownership == "LEASED" and not has_document(session, asset_id, "LEASE_CONSENT"):
        reasons.append("leased without LEASE_CONSENT document")
    for flag in registry.open_flags(session, asset_id):
        reasons.append(f"openFlag={flag.flag}")
    for enc in open_encumbrances(session, asset_id):
        if enc.facility_id is not None:
            if for_facility_id is None or enc.facility_id != for_facility_id:
                reasons.append(f"financedByFacility={enc.facility_id}")
        elif enc.kind in THIRD_PARTY_KINDS:
            reasons.append(f"thirdParty{enc.kind}={enc.holder}@{enc.priority}")
    if asset.parent_asset_id is not None:
        parent_enc = open_facility_encumbrance(session, asset.parent_asset_id)
        if parent_enc is not None and parent_enc.facility_id != for_facility_id:
            reasons.append(f"parentFinancedByFacility={parent_enc.facility_id}")
    for child in registry.children(session, asset_id):
        child_enc = open_facility_encumbrance(session, child.asset_id)
        if child_enc is not None and child_enc.facility_id != for_facility_id:
            reasons.append(f"partitionFinancedByFacility={child_enc.facility_id}")
    ok = not reasons
    asset.eligible = ok
    session.flush()
    return Eligibility(asset_id=asset_id, eligible=ok, reasons=reasons)


def assign_to_facility(
    session: Session, *, encumbrance_id: str, asset_id: str, facility_id: str, by_role: str, document_ref: str | None = None
) -> AssetEncumbrance:
    """
    Take the asset as collateral for a facility (kind ASSIGNMENT, holder `facility:<id>`). Refused when the
    asset (or its parent/partition) is already financed elsewhere, or is not eligible — the duplicate
    receivable/collateral guard.
    """
    require(by_role, REVIEW_ROLES, "assign an asset to a facility")
    if session.get(Facility, facility_id) is None:
        raise NotFound(f"facility {facility_id}")
    result = eligibility(session, asset_id, for_facility_id=facility_id)
    if not result.eligible:
        raise InvalidState("asset not eligible: " + "; ".join(result.reasons))
    if open_facility_encumbrance(session, asset_id) is not None:
        raise InvalidState("asset already financed")
    row = AssetEncumbrance(
        encumbrance_id=encumbrance_id,
        asset_id=asset_id,
        holder=f"{OUR_HOLDER_PREFIX}{facility_id}",
        priority=1,
        kind="ASSIGNMENT",
        document_ref=document_ref,
        valid_from=_now(),
        facility_id=facility_id,
    )
    session.add(row)
    session.flush()
    return row


def release(session: Session, *, encumbrance_id: str, by_role: str) -> AssetEncumbrance:
    require(by_role, REVIEW_ROLES, "release an encumbrance")
    row = session.get(AssetEncumbrance, encumbrance_id)
    if row is None:
        raise NotFound(f"encumbrance {encumbrance_id}")
    if row.status != "OPEN":
        raise InvalidState("already released")
    row.status = "RELEASED"
    row.released_at = _now()
    session.flush()
    return row


def carry_over(session: Session, *, encumbrance: AssetEncumbrance, new_asset_id: str, new_encumbrance_id: str) -> AssetEncumbrance:
    """RMA: move an open facility encumbrance to the replacement asset (release old, open new; never both)."""
    if encumbrance.status != "OPEN" or encumbrance.facility_id is None:
        raise InvalidState("only an open facility encumbrance can be carried over")
    encumbrance.status = "RELEASED"
    encumbrance.released_at = _now()
    session.flush()
    row = AssetEncumbrance(
        encumbrance_id=new_encumbrance_id,
        asset_id=new_asset_id,
        holder=encumbrance.holder,
        priority=encumbrance.priority,
        kind=encumbrance.kind,
        document_ref=encumbrance.document_ref,
        valid_from=_now(),
        facility_id=encumbrance.facility_id,
    )
    session.add(row)
    session.flush()
    return row
