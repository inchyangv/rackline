"""
GPU-017 tables (migration `0003_assets_rights`): provider-account ↔ borrower link history with a review
state, and asset review flags (duplicate listing, unverified ownership/lease, priority conflicts).

Linking an account to a borrower is *registration*, never approval: `provider_account_links` carries its own
`review_state` and nothing here touches `borrowers.underwriting_status` or facilities. Flags make an asset
ineligible until an underwriter resolves them (docs/gpu/permissions-and-states.md).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..domain import enums as E
from .models import ULID, Base, _in

LINK_STATES = ("REGISTERED", "VERIFIED", "REJECTED")
ASSET_FLAGS = ("DUPLICATE_LISTING", "OWNERSHIP_UNVERIFIED", "LEASE_UNVERIFIED", "PRIORITY_CONFLICT", "RMA_PENDING")


class ProviderAccountLink(Base):
    __tablename__ = "provider_account_links"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider_account_id: Mapped[str] = mapped_column(String(200), ForeignKey("provider_accounts.provider_account_id", ondelete="RESTRICT"), nullable=False)
    borrower_id: Mapped[str] = mapped_column(ULID, ForeignKey("borrowers.borrower_id", ondelete="RESTRICT"), nullable=False)
    legal_entity_id: Mapped[str] = mapped_column(ULID, ForeignKey("legal_entities.legal_entity_id", ondelete="RESTRICT"), nullable=False)
    review_state: Mapped[str] = mapped_column(String(16), nullable=False, server_default="REGISTERED")
    linked_by: Mapped[str] = mapped_column(String(16), nullable=False)
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    reviewed_by: Mapped[str | None] = mapped_column(String(16))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_ref: Mapped[str | None] = mapped_column(Text)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    release_reason: Mapped[str | None] = mapped_column(Text)
    previous_link_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("provider_account_links.id", ondelete="RESTRICT"))
    provenance: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    __table_args__ = (
        CheckConstraint(f"review_state IN {_in(list(LINK_STATES))}", name="ck_provider_account_links_state"),
        CheckConstraint(f"linked_by IN {_in(E.Role)}", name="ck_provider_account_links_linked_by"),
        CheckConstraint(f"reviewed_by IS NULL OR reviewed_by IN {_in(E.Role)}", name="ck_provider_account_links_reviewed_by"),
        CheckConstraint("(review_state = 'REGISTERED') = (reviewed_at IS NULL)", name="ck_provider_account_links_reviewed"),
        CheckConstraint("review_ref IS NULL OR review_ref ~ '^(vault|secret|doc)://'", name="ck_provider_account_links_ref"),
        CheckConstraint("released_at IS NULL OR released_at >= linked_at", name="ck_provider_account_links_release"),
        # One live link per provider account: release before re-linking to another borrower.
        Index("uq_provider_account_links_active", "provider_account_id", unique=True, postgresql_where="released_at IS NULL"),
    )


class AssetReviewFlag(Base):
    __tablename__ = "asset_review_flags"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset_id: Mapped[str] = mapped_column(ULID, ForeignKey("gpu_assets.asset_id", ondelete="CASCADE"), nullable=False)
    flag: Mapped[str] = mapped_column(String(24), nullable=False)
    details: Mapped[dict] = mapped_column(JSONB, nullable=False)
    raised_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[str | None] = mapped_column(String(16))
    resolution: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        CheckConstraint(f"flag IN {_in(list(ASSET_FLAGS))}", name="ck_asset_review_flags_flag"),
        CheckConstraint(f"resolved_by IS NULL OR resolved_by IN {_in(E.Role)}", name="ck_asset_review_flags_resolved_by"),
        CheckConstraint("(resolved_at IS NULL) = (resolved_by IS NULL)", name="ck_asset_review_flags_resolution"),
        Index("ix_asset_review_flags_open", "asset_id", postgresql_where="resolved_at IS NULL"),
    )
