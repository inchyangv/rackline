"""
GPU-017 asset/account rights services on real PostgreSQL: MIG partitions collapse to one collateral unit,
NIC changes keep identity with history, RMA replacement retires the old device and cannot be financed twice,
duplicate listings across provider accounts are flagged and ineligible, relinking needs a release and keeps
from/to/at history, account links never approve borrowers or create facilities, existing collateral blocks a
second facility, native NFT/anchor/transfer evidence never becomes ownership/unencumbrance/E2, and every
transition is role-gated.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from hashcredit_gpu.assets import (
    Forbidden,
    InvalidState,
    NotOwnershipEvidence,
    encumbrance,
    entities,
    evidence,
    registry,
)
from hashcredit_gpu.db.assets_models import ProviderAccountLink
from hashcredit_gpu.db.models import (
    AssetEncumbrance,
    Borrower,
    ControlAgreement,
    CustodyDocument,
    Facility,
    GpuAsset,
)

from .conftest import _dsn
from .test_schema import ULID_B, ULID_E, ULID_F, insert_facility, run, seed_base

ACCT_A = "mockdepin-testonly:acct-A"
ACCT_B = "mockdepin-testonly:acct-B"
BORROWER_2 = "01J000000000000000000000B2"
ENTITY_2 = "01J000000000000000000000A2"
FACILITY_1 = ULID_E
FACILITY_2 = ULID_F
GPU_1 = "01J0000000000000000000GPX1"
GPU_2 = "01J0000000000000000000GPX2"
MIG_1 = "01J0000000000000000000M1G1"
MIG_2 = "01J0000000000000000000M1G2"
RMA_1 = "01J0000000000000000000RMA1"
ENC_1 = "01J0000000000000000000ENC1"
ENC_2 = "01J0000000000000000000ENC2"
ENC_3 = "01J0000000000000000000ENC3"
KEYS_1 = [("GPU_UUID", "GPU-aaaa-1111"), ("SERIAL", "SN-0001"), ("NIC_MAC", "aa:bb:cc:00:00:01")]


@pytest.fixture
def db(conn, migrated_db_url):
    """Seeded schema: entity/borrower A, provider, accounts A & B, a second borrower, two DRAFT facilities."""
    seed_base(conn)
    run(conn, "INSERT INTO provider_accounts (provider_account_id, provider_id, external_account_id, borrower_id) VALUES (%s, 'mockdepin-testonly', 'acct-B', %s)", (ACCT_B, ULID_B))
    run(conn, "INSERT INTO legal_entities (legal_entity_id, jurisdiction) VALUES (%s, NULL)", (ENTITY_2,))
    run(conn, "INSERT INTO borrowers (borrower_id, legal_entity_id) VALUES (%s, %s)", (BORROWER_2, ENTITY_2))
    insert_facility(conn, FACILITY_1, profile="NATIVE_TESTNET")
    insert_facility(conn, FACILITY_2, profile="NATIVE_TESTNET")
    conn.commit()
    engine = create_engine(_dsn(migrated_db_url).replace("postgresql://", "postgresql+psycopg2://", 1) if _dsn(migrated_db_url).startswith("postgresql://") else migrated_db_url)
    try:
        yield engine
    finally:
        engine.dispose()


def session(engine) -> Session:
    return Session(engine, expire_on_commit=False)


def register_gpu(s: Session, asset_id=GPU_1, keys=KEYS_1, account=ACCT_A):
    r = registry.register_asset(s, asset_id=asset_id, kind="PHYSICAL_GPU", keys=keys, by_role="operator", provider_account_id=account, sku="H100-80G")
    assert r.created and r.conflict is None
    return r.asset


def verify_owned(s: Session, asset_id: str):
    registry.review_ownership(s, asset_id=asset_id, verdict="VERIFIED", ownership="OWNED", by_role="underwriter", review_ref="doc://review/1", identity_confidence="HIGH")


# ---------------------------------------------------------------- partitions


def test_mig_split_is_one_collateral_unit(db):
    with session(db) as s, s.begin():
        register_gpu(s)
        registry.register_partition(s, parent_asset_id=GPU_1, child_asset_id=MIG_1, keys=[("GPU_UUID", "MIG-1")], by_role="operator")
        registry.register_partition(s, parent_asset_id=GPU_1, child_asset_id=MIG_2, keys=[("GPU_UUID", "MIG-2")], by_role="operator")
        units = registry.collateral_units(s, [GPU_1, MIG_1, MIG_2, MIG_1])
        assert units == {GPU_1: 1}
        # a partition cannot be partitioned, and a partition of a financed parent is not separately financeable
        with pytest.raises(InvalidState):
            registry.register_partition(s, parent_asset_id=MIG_1, child_asset_id="01J0000000000000000000M1G3", keys=[("GPU_UUID", "MIG-3")], by_role="operator")
        verify_owned(s, GPU_1)
        encumbrance.assign_to_facility(s, encumbrance_id=ENC_1, asset_id=GPU_1, facility_id=FACILITY_1, by_role="underwriter")
        verify_owned(s, MIG_1)
        e = encumbrance.eligibility(s, MIG_1, for_facility_id=FACILITY_2)
        assert not e.eligible and any(r.startswith("parentFinancedByFacility") for r in e.reasons)


# ---------------------------------------------------------------- identity changes


def test_nic_change_keeps_identity_with_history(db):
    with session(db) as s, s.begin():
        register_gpu(s)
        registry.change_identity_key(s, asset_id=GPU_1, scheme="NIC_MAC", old_value="aa:bb:cc:00:00:01", new_value="aa:bb:cc:00:00:02", by_role="operator")
        assert registry.find_asset_by_key(s, "NIC_MAC", "aa:bb:cc:00:00:02").asset_id == GPU_1
        assert registry.find_asset_by_key(s, "NIC_MAC", "aa:bb:cc:00:00:01") is None
        hist = [(k.scheme, k.value, k.retired_at is None) for k in registry.key_history(s, GPU_1) if k.scheme == "NIC_MAC"]
        assert hist == [("NIC_MAC", "aa:bb:cc:00:00:01", False), ("NIC_MAC", "aa:bb:cc:00:00:02", True)]
        assert registry.open_assignment(s, GPU_1).provider_account_id == ACCT_A
        # re-registering the old MAC as a "new" GPU does not create a second asset (history is not identity)
        r = registry.register_asset(s, asset_id=GPU_2, kind="PHYSICAL_GPU", keys=[("NIC_MAC", "aa:bb:cc:00:00:01")], by_role="operator")
        assert r.created and r.asset.asset_id == GPU_2  # retired key is free again; the *serial/UUID* would collide
        r2 = registry.register_asset(s, asset_id="01J0000000000000000000GPX3", kind="PHYSICAL_GPU", keys=[("SERIAL", "SN-0001")], by_role="operator")
        assert not r2.created and r2.asset.asset_id == GPU_1 and r2.conflict.flag == "DUPLICATE_LISTING"


# ---------------------------------------------------------------- RMA


def test_rma_replacement_retires_old_and_prevents_double_financing(db):
    with session(db) as s, s.begin():
        register_gpu(s)
        verify_owned(s, GPU_1)
        encumbrance.assign_to_facility(s, encumbrance_id=ENC_1, asset_id=GPU_1, facility_id=FACILITY_1, by_role="underwriter")
        with pytest.raises(InvalidState, match="carry_encumbrance"):
            registry.replace_asset(s, old_asset_id=GPU_1, new_asset_id=RMA_1, moved_keys=[("SERIAL", "SN-0001")], new_keys=[("GPU_UUID", "GPU-bbbb-2222")], by_role="operator", assignment_id="01J0000000000000000000ASR1")
        new = registry.replace_asset(
            s, old_asset_id=GPU_1, new_asset_id=RMA_1, moved_keys=[("SERIAL", "SN-0001")], new_keys=[("GPU_UUID", "GPU-bbbb-2222")],
            by_role="operator", assignment_id="01J0000000000000000000ASR1", carry_encumbrance=True,
        )
        old = s.get(GpuAsset, GPU_1)
        assert old.status == "RETIRED" and not old.eligible and new.replaces_asset_id == GPU_1
        assert registry.active_keys(s, GPU_1) == []
        assert {(k.scheme, k.value) for k in registry.active_keys(s, RMA_1)} == {("SERIAL", "SN-0001"), ("GPU_UUID", "GPU-bbbb-2222")}
        assert registry.open_assignment(s, GPU_1) is None
        assert registry.open_assignment(s, RMA_1).provider_account_id == ACCT_A
        # exactly one open facility encumbrance survives, on the new asset
        assert s.get(AssetEncumbrance, ENC_1).status == "RELEASED"
        assert encumbrance.open_facility_encumbrance(s, RMA_1).facility_id == FACILITY_1
        assert encumbrance.open_facility_encumbrance(s, GPU_1) is None
        # neither device can be financed by a second facility
        with pytest.raises(InvalidState, match="not eligible"):
            encumbrance.assign_to_facility(s, encumbrance_id=ENC_2, asset_id=GPU_1, facility_id=FACILITY_2, by_role="underwriter")
        with pytest.raises(InvalidState, match="financedByFacility"):
            encumbrance.assign_to_facility(s, encumbrance_id=ENC_3, asset_id=RMA_1, facility_id=FACILITY_2, by_role="underwriter")
        with pytest.raises(InvalidState):
            registry.assign_provider(s, asset_id=GPU_1, provider_account_id=ACCT_B, by_role="operator", reason="MOVE", assignment_id="01J0000000000000000000ASR2")
        assert registry.collateral_units(s, [GPU_1, RMA_1]) == {GPU_1: 0, RMA_1: 1}


# ---------------------------------------------------------------- duplicate listing


def test_same_physical_asset_on_two_providers_is_flagged_and_ineligible(db):
    with session(db) as s, s.begin():
        register_gpu(s)
        verify_owned(s, GPU_1)
        assert encumbrance.eligibility(s, GPU_1).eligible
        out = registry.assign_provider(s, asset_id=GPU_1, provider_account_id=ACCT_B, by_role="operator", reason="ONBOARD", assignment_id="01J0000000000000000000ASB1")
        assert out.flag == "DUPLICATE_LISTING"
        assert out.details == {"existingProviderAccountId": ACCT_A, "attemptedProviderAccountId": ACCT_B}
        assert registry.open_assignment(s, GPU_1).provider_account_id == ACCT_A  # still one live assignment
        e = encumbrance.eligibility(s, GPU_1)
        assert not e.eligible and "openFlag=DUPLICATE_LISTING" in e.reasons
        assert s.get(GpuAsset, GPU_1).eligible is False
        # a second "asset" claiming the same UUID from provider B is the same device, not new collateral
        r = registry.register_asset(s, asset_id=GPU_2, kind="PHYSICAL_GPU", keys=[("GPU_UUID", "GPU-aaaa-1111")], by_role="operator", provider_account_id=ACCT_B)
        assert not r.created and r.asset.asset_id == GPU_1
        assert r.conflict.details["attemptedProviderAccountId"] == ACCT_B and r.conflict.details["existingProviderAccountId"] == ACCT_A
        assert s.get(GpuAsset, GPU_2) is None
        assert len(registry.open_flags(s, GPU_1, "DUPLICATE_LISTING")) == 2
        with pytest.raises(Forbidden):
            registry.resolve_flag(s, flag_id=out.id, by_role="operator", resolution="x")
        for f in registry.open_flags(s, GPU_1):
            registry.resolve_flag(s, flag_id=f.id, by_role="underwriter", resolution="provider B listing was a stale mirror; removed")
        assert encumbrance.eligibility(s, GPU_1).eligible


# ---------------------------------------------------------------- account links


def test_relink_to_another_borrower_requires_release_and_keeps_history(db):
    with session(db) as s, s.begin():
        first = entities.link_account(s, provider_account_id=ACCT_A, borrower_id=ULID_B, by_role="operator", provenance={"source": "portal"})
        assert first.review_state == "REGISTERED"
        entities.review_link(s, link_id=first.id, verdict="VERIFIED", by_role="underwriter", review_ref="doc://kyc/acct-A")
        with pytest.raises(InvalidState, match="release"):
            entities.relink_account(s, provider_account_id=ACCT_A, new_borrower_id=BORROWER_2, by_role="operator")
        with pytest.raises(Forbidden):
            entities.release_link(s, provider_account_id=ACCT_A, by_role="borrower", reason="self-service")
        entities.release_link(s, provider_account_id=ACCT_A, by_role="underwriter", reason="entity sold the account")
        second = entities.relink_account(s, provider_account_id=ACCT_A, new_borrower_id=BORROWER_2, by_role="operator")
        assert second.previous_link_id == first.id and second.borrower_id == BORROWER_2 and second.legal_entity_id == ENTITY_2
        assert second.provenance["from"] == ULID_B and second.provenance["to"] == BORROWER_2 and "at" in second.provenance
        assert second.review_state == "REGISTERED"  # review starts over for the new borrower
        hist = entities.link_history(s, ACCT_A)
        assert [(h.borrower_id, h.released_at is None) for h in hist] == [(ULID_B, False), (BORROWER_2, True)]
        # the DB itself refuses a second live link
        s.add(ProviderAccountLink(provider_account_id=ACCT_A, borrower_id=ULID_B, legal_entity_id=hist[0].legal_entity_id, linked_by="operator"))
        with pytest.raises(Exception, match="uq_provider_account_links_active"):
            s.flush()


def test_account_link_creates_no_borrower_approval_or_facility(db):
    with session(db) as s, s.begin():
        before_facilities = s.scalar(select(func.count()).select_from(Facility))
        link = entities.link_account(s, provider_account_id=ACCT_B, borrower_id=ULID_B, by_role="operator")
        entities.review_link(s, link_id=link.id, verdict="VERIFIED", by_role="underwriter")
        b = s.get(Borrower, ULID_B)
        assert b.underwriting_status == "NONE" and b.kyc_status == "NONE"
        assert s.scalar(select(func.count()).select_from(Facility)) == before_facilities
        assert s.scalar(select(func.count()).select_from(ControlAgreement)) == 0
        with pytest.raises(Forbidden):
            entities.link_account(s, provider_account_id=ACCT_A, borrower_id=ULID_B, by_role="borrower")
        with pytest.raises(Forbidden):
            entities.review_link(s, link_id=link.id, verdict="REJECTED", by_role="operator")


# ---------------------------------------------------------------- collateral / priority


def test_existing_collateral_and_third_party_priority_block_a_second_facility(db):
    with session(db) as s, s.begin():
        register_gpu(s)
        e = encumbrance.eligibility(s, GPU_1)
        assert not e.eligible and "ownershipReview=UNVERIFIED" in e.reasons and "ownership=UNKNOWN" in e.reasons
        registry.review_ownership(s, asset_id=GPU_1, verdict="VERIFIED", ownership="LEASED", by_role="underwriter")
        e = encumbrance.eligibility(s, GPU_1)
        assert not e.eligible and "leased without LEASE_CONSENT document" in e.reasons
        encumbrance.attach_document(s, asset_id=GPU_1, kind="LEASE_CONSENT", document_ref="doc://lease/consent-1", document_hash="0x" + "ab" * 32, by_role="underwriter")
        assert encumbrance.eligibility(s, GPU_1).eligible
        encumbrance.assign_to_facility(s, encumbrance_id=ENC_1, asset_id=GPU_1, facility_id=FACILITY_1, by_role="underwriter")
        with pytest.raises(InvalidState, match="financedByFacility"):
            encumbrance.assign_to_facility(s, encumbrance_id=ENC_2, asset_id=GPU_1, facility_id=FACILITY_2, by_role="underwriter")
        # DB-level guard as well: a raw second open facility encumbrance is rejected
        s.add(AssetEncumbrance(encumbrance_id=ENC_2, asset_id=GPU_1, holder="facility:x", priority=1, kind="ASSIGNMENT", valid_from=func.now(), facility_id=FACILITY_2))
        with pytest.raises(Exception, match="uq_asset_encumbrances_open_facility"):
            s.flush()
    with session(db) as s, s.begin():
        register_gpu(s, asset_id=GPU_2, keys=[("SERIAL", "SN-0002")], account=ACCT_B)
        verify_owned(s, GPU_2)
        encumbrance.record_third_party_right(s, encumbrance_id=ENC_3, asset_id=GPU_2, holder="Bank X", kind="LIEN", priority=1, document_ref="doc://ucc/1", by_role="underwriter")
        e = encumbrance.eligibility(s, GPU_2)
        assert not e.eligible and "thirdPartyLIEN=Bank X@1" in e.reasons and "openFlag=PRIORITY_CONFLICT" in e.reasons
        with pytest.raises(Forbidden):
            encumbrance.record_third_party_right(s, encumbrance_id="01J0000000000000000000ENC4", asset_id=GPU_2, holder="Bank Y", kind="LIEN", priority=2, document_ref="doc://ucc/2", by_role="operator")


# ---------------------------------------------------------------- R2 regression


def test_native_evidence_never_approves_ownership_unencumbrance_or_e2(db):
    with session(db) as s, s.begin():
        register_gpu(s)
        base = {"sourceEventId": "0x" + "11" * 32, "verificationMethod": "ATTESTCOIN_NATIVE", "nativeStatus": "CONSUMED", "dataHash": "0x" + "22" * 32}
        for kind in ("NFT_MINT", "HASH_ANCHOR", "TOKEN_TRANSFER"):
            doc = evidence.attach_native_evidence(s, asset_id=GPU_1, evidence={**base, "kind": kind}, by_role="operator")
            assert doc.kind == f"NATIVE_EVIDENCE_{kind}" and doc.document_ref.startswith("doc://native-evidence/")
        a = s.get(GpuAsset, GPU_1)
        assert a.ownership == "UNKNOWN" and a.ownership_review == "UNVERIFIED" and a.eligible is False
        assert encumbrance.open_encumbrances(s, GPU_1) == []
        assert s.scalar(select(func.count()).select_from(ControlAgreement)) == 0
        assert s.scalar(select(func.count()).select_from(CustodyDocument)) == 3
        assert not encumbrance.eligibility(s, GPU_1).eligible
        with pytest.raises(NotOwnershipEvidence):
            evidence.attach_native_evidence(s, asset_id=GPU_1, evidence={**base, "kind": "NFT_MINT", "ownership": "OWNED"}, by_role="underwriter")
        with pytest.raises(NotOwnershipEvidence):
            evidence.ownership_from_evidence({**base, "kind": "TOKEN_TRANSFER"})
        with pytest.raises(InvalidState):
            evidence.attach_native_evidence(s, asset_id=GPU_1, evidence={**base, "kind": "DEED"}, by_role="operator")
        # the DB also refuses the shortcut: eligible without a verified review
        a.eligible = True
        a.ownership = "OWNED"
        with pytest.raises(Exception, match="ck_gpu_assets_eligible_requires_review"):
            s.flush()


# ---------------------------------------------------------------- roles / state machine


def test_review_transitions_are_role_gated_and_monotonic(db):
    with session(db) as s, s.begin():
        register_gpu(s)
        with pytest.raises(Forbidden):
            registry.review_ownership(s, asset_id=GPU_1, verdict="VERIFIED", ownership="OWNED", by_role="operator")
        with pytest.raises(Forbidden):
            registry.register_asset(s, asset_id=GPU_2, kind="PHYSICAL_GPU", keys=[("SERIAL", "SN-X")], by_role="lp")
        with pytest.raises(Forbidden, match="unknown role"):
            registry.register_asset(s, asset_id=GPU_2, kind="PHYSICAL_GPU", keys=[("SERIAL", "SN-X")], by_role="admin")
        with pytest.raises(InvalidState):
            registry.review_ownership(s, asset_id=GPU_1, verdict="VERIFIED", ownership="UNKNOWN", by_role="underwriter")
        registry.review_ownership(s, asset_id=GPU_1, verdict="REJECTED", ownership="UNKNOWN", by_role="underwriter", review_ref="doc://review/rejected")
        assert s.get(GpuAsset, GPU_1).ownership_review == "REJECTED" and not encumbrance.eligibility(s, GPU_1).eligible
        link = entities.link_account(s, provider_account_id=ACCT_A, borrower_id=ULID_B, by_role="system")
        entities.review_link(s, link_id=link.id, verdict="REJECTED", by_role="underwriter")
        with pytest.raises(InvalidState, match="already reviewed"):
            entities.review_link(s, link_id=link.id, verdict="VERIFIED", by_role="underwriter")
        with pytest.raises(InvalidState):
            entities.link_account(s, provider_account_id=ACCT_B, borrower_id=BORROWER_2, by_role="operator")  # bound to borrower B
        # identity confidence and ownership review are independent fields
        registry.review_ownership(s, asset_id=GPU_1, verdict="VERIFIED", ownership="OWNED", by_role="underwriter", identity_confidence="LOW")
        a = s.get(GpuAsset, GPU_1)
        assert a.identity_confidence == "LOW" and a.ownership_review == "VERIFIED"
