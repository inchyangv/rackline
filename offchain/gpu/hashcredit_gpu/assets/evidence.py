"""
R2 regression (R2-D04/D05): a natively verified NFT mint, hash anchor or token transfer proves only that
that log occurred. It is stored as a custody document *reference* and can never flip ownership review,
encumbrances or control grade. Callers who try to derive ownership from it get NotOwnershipEvidence.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..db.models import CustodyDocument, GpuAsset
from . import registry
from .errors import InvalidState, NotOwnershipEvidence
from .roles import REGISTER_ROLES, REVIEW_ROLES, require

NATIVE_EVIDENCE_KINDS = ("NFT_MINT", "HASH_ANCHOR", "TOKEN_TRANSFER")
_REQUIRED = ("sourceEventId", "verificationMethod", "nativeStatus", "kind", "dataHash")


def attach_native_evidence(session: Session, *, asset_id: str, evidence: dict, by_role: str) -> CustodyDocument:
    """Store the reference. Snapshot of ownership/encumbrance/eligibility before == after (asserted)."""
    require(by_role, REGISTER_ROLES | REVIEW_ROLES, "attach native evidence")
    missing = [k for k in _REQUIRED if k not in evidence]
    if missing:
        raise InvalidState(f"evidence missing {missing}")
    if evidence["kind"] not in NATIVE_EVIDENCE_KINDS:
        raise InvalidState(f"unknown native evidence kind {evidence['kind']!r}")
    for forbidden in ("ownership", "ownershipReview", "controlGrade", "eligible", "encumbrance", "unencumbered"):
        if forbidden in evidence:
            raise NotOwnershipEvidence(f"native evidence cannot carry a {forbidden!r} claim")
    asset = registry._get(session, asset_id)
    before = _snapshot(session, asset)
    doc = CustodyDocument(
        asset_id=asset_id,
        kind=f"NATIVE_EVIDENCE_{evidence['kind']}",
        document_ref=f"doc://native-evidence/{evidence['sourceEventId']}",
        document_hash=evidence["dataHash"],
    )
    session.add(doc)
    session.flush()
    after = _snapshot(session, asset)
    if before != after:  # defensive: this module must never move rights
        raise NotOwnershipEvidence("attaching evidence changed rights state")
    return doc


def ownership_from_evidence(evidence: dict) -> None:
    """There is no path from native evidence to ownership, unencumbrance or E2 (R2-D05)."""
    raise NotOwnershipEvidence(
        f"{evidence.get('kind')} with nativeStatus={evidence.get('nativeStatus')} proves the log occurred, "
        "not ownership / unencumbrance / E2; run the document review (GPU-013) instead"
    )


def _snapshot(session: Session, asset: GpuAsset) -> tuple:
    from .encumbrance import open_encumbrances

    return (
        asset.ownership,
        asset.ownership_review,
        asset.eligible,
        asset.status,
        tuple((e.encumbrance_id, e.status) for e in open_encumbrances(session, asset.asset_id)),
    )
