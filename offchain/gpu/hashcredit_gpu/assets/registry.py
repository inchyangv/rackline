"""
GPU asset registry: identity keys with lifetimes, MIG partitions, provider assignments, NIC changes, RMA
replacement and duplicate-listing detection.

Identity confidence (how sure we are that keys name one physical device) and ownership review (who owns /
leases it, who has priority) are separate fields and separate decisions; neither is inferred from the other.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.assets_models import AssetReviewFlag
from ..db.models import AssetIdentityKey, AssetProviderAssignment, GpuAsset, ProviderAccount
from .errors import InvalidState, NotFound
from .roles import REGISTER_ROLES, REVIEW_ROLES, require

IdentityKey = tuple[str, str]  # (scheme, value)


def _now() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------- lookups


def active_keys(session: Session, asset_id: str) -> list[AssetIdentityKey]:
    return list(
        session.scalars(
            select(AssetIdentityKey)
            .where(AssetIdentityKey.asset_id == asset_id, AssetIdentityKey.retired_at.is_(None))
            .order_by(AssetIdentityKey.id)
        )
    )


def key_history(session: Session, asset_id: str) -> list[AssetIdentityKey]:
    return list(
        session.scalars(select(AssetIdentityKey).where(AssetIdentityKey.asset_id == asset_id).order_by(AssetIdentityKey.id))
    )


def find_asset_by_key(session: Session, scheme: str, value: str) -> GpuAsset | None:
    key = session.scalar(
        select(AssetIdentityKey).where(
            AssetIdentityKey.scheme == scheme, AssetIdentityKey.value == value, AssetIdentityKey.retired_at.is_(None)
        )
    )
    return session.get(GpuAsset, key.asset_id) if key else None


def open_assignment(session: Session, asset_id: str) -> AssetProviderAssignment | None:
    return session.scalar(
        select(AssetProviderAssignment).where(
            AssetProviderAssignment.asset_id == asset_id, AssetProviderAssignment.ended_at.is_(None)
        )
    )


def open_flags(session: Session, asset_id: str, flag: str | None = None) -> list[AssetReviewFlag]:
    q = select(AssetReviewFlag).where(AssetReviewFlag.asset_id == asset_id, AssetReviewFlag.resolved_at.is_(None))
    if flag:
        q = q.where(AssetReviewFlag.flag == flag)
    return list(session.scalars(q.order_by(AssetReviewFlag.id)))


def children(session: Session, asset_id: str) -> list[GpuAsset]:
    return list(session.scalars(select(GpuAsset).where(GpuAsset.parent_asset_id == asset_id).order_by(GpuAsset.asset_id)))


def _get(session: Session, asset_id: str) -> GpuAsset:
    asset = session.get(GpuAsset, asset_id)
    if asset is None:
        raise NotFound(f"asset {asset_id}")
    return asset


def raise_flag(session: Session, asset_id: str, flag: str, details: dict) -> AssetReviewFlag:
    """Raise a review flag and drop eligibility until an underwriter resolves it."""
    asset = _get(session, asset_id)
    row = AssetReviewFlag(asset_id=asset_id, flag=flag, details=details)
    asset.eligible = False
    session.add(row)
    session.flush()
    return row


def resolve_flag(session: Session, *, flag_id: int, by_role: str, resolution: str) -> AssetReviewFlag:
    require(by_role, REVIEW_ROLES, "resolve an asset review flag")
    row = session.get(AssetReviewFlag, flag_id)
    if row is None:
        raise NotFound(f"flag {flag_id}")
    if row.resolved_at is not None:
        raise InvalidState("flag already resolved")
    row.resolved_at = _now()
    row.resolved_by = by_role
    row.resolution = resolution
    session.flush()
    return row


# ---------------------------------------------------------------- registration


class RegistrationResult:
    """Either a new asset, or an existing asset that the same identity keys already name (duplicate listing)."""

    def __init__(self, asset: GpuAsset, created: bool, conflict: AssetReviewFlag | None):
        self.asset = asset
        self.created = created
        self.conflict = conflict


def register_asset(
    session: Session,
    *,
    asset_id: str,
    kind: str,
    keys: Iterable[IdentityKey],
    by_role: str,
    provider_account_id: str | None = None,
    sku: str | None = None,
    unit_count: int = 1,
    custodian: str | None = None,
    location: str | None = None,
    key_provenance: dict | None = None,
    identity_confidence: str = "LOW",
) -> RegistrationResult:
    """
    Register a physical asset with its identity keys. If any key is already *active* on another asset, no
    second asset is created: the existing asset gets a DUPLICATE_LISTING flag (both provider accounts in
    `details`) and becomes ineligible until reviewed (PIVOT §6.1).
    """
    require(by_role, REGISTER_ROLES, "register an asset")
    keys = list(keys)
    if not keys:
        raise InvalidState("an asset needs at least one identity key")
    for scheme, value in keys:
        existing = find_asset_by_key(session, scheme, value)
        if existing is not None:
            current = open_assignment(session, existing.asset_id)
            flag = raise_flag(
                session,
                existing.asset_id,
                "DUPLICATE_LISTING",
                {
                    "attemptedAssetId": asset_id,
                    "attemptedProviderAccountId": provider_account_id,
                    "existingProviderAccountId": current.provider_account_id if current else None,
                    "key": {"scheme": scheme, "value": value},
                },
            )
            return RegistrationResult(existing, created=False, conflict=flag)
    asset = GpuAsset(
        asset_id=asset_id,
        kind=kind,
        sku=sku,
        unit_count=unit_count,
        custodian=custodian,
        location=location,
        identity_confidence=identity_confidence,
    )
    session.add(asset)
    session.flush()
    for scheme, value in keys:
        session.add(AssetIdentityKey(asset_id=asset_id, scheme=scheme, value=value, provenance=key_provenance or {"by": by_role}))
    session.flush()
    if provider_account_id is not None:
        assign_provider(session, asset_id=asset_id, provider_account_id=provider_account_id, by_role=by_role, reason="ONBOARD", assignment_id=_derive_ulid(asset_id, "AS"))
    return RegistrationResult(asset, created=True, conflict=None)


def _derive_ulid(base: str, tag: str) -> str:
    # deterministic, Crockford-safe (no I/L/O/U): keep 26 chars
    return (base[: 26 - len(tag)] + tag)[:26]


def register_partition(
    session: Session, *, parent_asset_id: str, child_asset_id: str, keys: Iterable[IdentityKey], by_role: str, sku: str | None = None
) -> GpuAsset:
    """A MIG/vGPU partition of an existing physical GPU. Children never add collateral value beyond the parent."""
    require(by_role, REGISTER_ROLES, "register a partition")
    parent = _get(session, parent_asset_id)
    if parent.kind not in ("PHYSICAL_GPU",):
        raise InvalidState("partitions can only be created under a PHYSICAL_GPU")
    if parent.status != "ACTIVE":
        raise InvalidState("cannot partition a retired asset")
    child = GpuAsset(asset_id=child_asset_id, kind="MIG_PARTITION", sku=sku, parent_asset_id=parent_asset_id, ownership=parent.ownership)
    session.add(child)
    session.flush()
    for scheme, value in keys:
        session.add(AssetIdentityKey(asset_id=child_asset_id, scheme=scheme, value=value, provenance={"partitionOf": parent_asset_id}))
    session.flush()
    return child


def collateral_units(session: Session, asset_ids: Iterable[str]) -> dict[str, int]:
    """
    Physical units financeable from a set of assets: partitions collapse into their parent, retired assets
    count 0, duplicates count once. Two listings of the same GPU never become two collateral values.
    """
    units: dict[str, int] = {}
    for asset_id in asset_ids:
        asset = _get(session, asset_id)
        root = asset
        while root.parent_asset_id is not None:
            root = _get(session, root.parent_asset_id)
        if root.status != "ACTIVE":
            units[root.asset_id] = 0
            continue
        units[root.asset_id] = root.unit_count
    return units


# ---------------------------------------------------------------- assignments


def assign_provider(
    session: Session,
    *,
    asset_id: str,
    provider_account_id: str,
    by_role: str,
    reason: str,
    assignment_id: str,
    started_at: datetime | None = None,
    provenance: dict | None = None,
) -> AssetProviderAssignment | AssetReviewFlag:
    """
    Put an asset live on a provider account. If the asset is already live on a *different* provider account,
    no second assignment is created; a DUPLICATE_LISTING flag naming both accounts is raised instead.
    """
    require(by_role, REGISTER_ROLES, "assign an asset to a provider")
    asset = _get(session, asset_id)
    if asset.status != "ACTIVE":
        raise InvalidState("retired asset cannot be assigned")
    if session.get(ProviderAccount, provider_account_id) is None:
        raise NotFound(f"provider account {provider_account_id}")
    current = open_assignment(session, asset_id)
    if current is not None:
        if current.provider_account_id == provider_account_id:
            raise InvalidState("asset already live on this provider account")
        return raise_flag(
            session,
            asset_id,
            "DUPLICATE_LISTING",
            {"existingProviderAccountId": current.provider_account_id, "attemptedProviderAccountId": provider_account_id},
        )
    row = AssetProviderAssignment(
        assignment_id=assignment_id,
        asset_id=asset_id,
        provider_account_id=provider_account_id,
        started_at=started_at or _now(),
        reason=reason,
        provenance=provenance or {"by": by_role},
    )
    session.add(row)
    session.flush()
    return row


def end_assignment(session: Session, *, asset_id: str, by_role: str, reason: str, ended_at: datetime | None = None) -> AssetProviderAssignment:
    require(by_role, REGISTER_ROLES, "end an assignment")
    current = open_assignment(session, asset_id)
    if current is None:
        raise NotFound(f"no open assignment for {asset_id}")
    current.ended_at = ended_at or _now()
    current.provenance = {**current.provenance, "endReason": reason}
    session.flush()
    return current


# ---------------------------------------------------------------- identity changes / RMA


def change_identity_key(
    session: Session, *, asset_id: str, scheme: str, old_value: str | None, new_value: str, by_role: str, provenance: dict | None = None
) -> AssetIdentityKey:
    """NIC/MAC (or any key) change on the same physical asset: retire the old key row, add the new one."""
    require(by_role, REGISTER_ROLES, "change an identity key")
    asset = _get(session, asset_id)
    if asset.status != "ACTIVE":
        raise InvalidState("retired asset")
    if old_value is not None:
        old = session.scalar(
            select(AssetIdentityKey).where(
                AssetIdentityKey.asset_id == asset_id,
                AssetIdentityKey.scheme == scheme,
                AssetIdentityKey.value == old_value,
                AssetIdentityKey.retired_at.is_(None),
            )
        )
        if old is None:
            raise NotFound(f"active key {scheme}={old_value} on {asset_id}")
        old.retired_at = _now()
    if find_asset_by_key(session, scheme, new_value) is not None:
        raise InvalidState(f"{scheme}={new_value} is active on another asset")
    row = AssetIdentityKey(asset_id=asset_id, scheme=scheme, value=new_value, provenance={**(provenance or {}), "replaces": old_value, "by": by_role})
    session.add(row)
    session.flush()
    return row


def replace_asset(
    session: Session,
    *,
    old_asset_id: str,
    new_asset_id: str,
    moved_keys: Iterable[IdentityKey],
    new_keys: Iterable[IdentityKey],
    by_role: str,
    assignment_id: str,
    carry_encumbrance: bool = False,
) -> GpuAsset:
    """
    RMA replacement. The old asset is RETIRED (never eligible again, assignment ended with reason RMA); the
    new asset records `replaces_asset_id`; moved keys are retired on the old asset and re-issued on the new
    one with history. An open facility encumbrance on the old asset blocks the replacement unless the caller
    explicitly carries it over (then it is released on the old and re-opened on the new — never duplicated).
    """
    require(by_role, REGISTER_ROLES, "replace an asset (RMA)")
    from . import encumbrance as enc  # local import: encumbrance depends on registry lookups

    old = _get(session, old_asset_id)
    if old.status != "ACTIVE":
        raise InvalidState("old asset already retired")
    held = enc.open_facility_encumbrance(session, old_asset_id)
    if held is not None and not carry_encumbrance:
        raise InvalidState("old asset is financed; carry_encumbrance=True is required to move the right")
    current = open_assignment(session, old_asset_id)
    new = GpuAsset(
        asset_id=new_asset_id,
        kind=old.kind,
        sku=old.sku,
        unit_count=old.unit_count,
        ownership=old.ownership,
        custodian=old.custodian,
        location=old.location,
        replaces_asset_id=old_asset_id,
        ownership_review=old.ownership_review,
        identity_confidence=old.identity_confidence,
    )
    session.add(new)
    session.flush()
    now = _now()
    for scheme, value in moved_keys:
        row = session.scalar(
            select(AssetIdentityKey).where(
                AssetIdentityKey.asset_id == old_asset_id,
                AssetIdentityKey.scheme == scheme,
                AssetIdentityKey.value == value,
                AssetIdentityKey.retired_at.is_(None),
            )
        )
        if row is None:
            raise NotFound(f"active key {scheme}={value} on {old_asset_id}")
        row.retired_at = now
        session.flush()
        session.add(AssetIdentityKey(asset_id=new_asset_id, scheme=scheme, value=value, provenance={"movedFrom": old_asset_id, "reason": "RMA"}))
    for scheme, value in new_keys:
        session.add(AssetIdentityKey(asset_id=new_asset_id, scheme=scheme, value=value, provenance={"reason": "RMA", "by": by_role}))
    for key in active_keys(session, old_asset_id):
        key.retired_at = now  # nothing stays active on a retired device
    old.status = "RETIRED"
    old.eligible = False
    session.flush()
    if current is not None:
        current.ended_at = now
        current.provenance = {**current.provenance, "endReason": "RMA", "replacedBy": new_asset_id}
        session.flush()
        assign_provider(
            session,
            asset_id=new_asset_id,
            provider_account_id=current.provider_account_id,
            by_role=by_role,
            reason="RMA",
            assignment_id=assignment_id,
            provenance={"replaces": old_asset_id},
        )
    if held is not None and carry_encumbrance:
        enc.carry_over(session, encumbrance=held, new_asset_id=new_asset_id, new_encumbrance_id=_derive_ulid(new_asset_id, "EN"))
    return new


# ---------------------------------------------------------------- review


def review_ownership(
    session: Session, *, asset_id: str, verdict: str, ownership: str, by_role: str, review_ref: str | None = None, identity_confidence: str | None = None
) -> GpuAsset:
    """Underwriter records the ownership review result. This never sets `eligible` by itself."""
    require(by_role, REVIEW_ROLES, "review asset ownership")
    if verdict not in ("VERIFIED", "REJECTED"):
        raise InvalidState("verdict must be VERIFIED or REJECTED")
    if ownership not in ("OWNED", "LEASED", "UNKNOWN"):
        raise InvalidState("ownership must be OWNED, LEASED or UNKNOWN")
    if verdict == "VERIFIED" and ownership == "UNKNOWN":
        raise InvalidState("cannot verify ownership as UNKNOWN")
    asset = _get(session, asset_id)
    asset.ownership_review = verdict
    asset.ownership = ownership
    asset.review_ref = review_ref
    if identity_confidence is not None:
        asset.identity_confidence = identity_confidence
    session.flush()
    return asset
