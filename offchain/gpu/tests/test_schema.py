"""
Schema constraint tests on real PostgreSQL (GPU-015): FK/unique/check constraints and the
profile-isolation triggers must reject the shortcuts the domain model forbids.
"""

from __future__ import annotations

import json
from pathlib import Path

import psycopg2
import pytest
from psycopg2 import errors

from hashcredit_gpu.domain import enums as E
from hashcredit_gpu.domain.enums import SCHEMA_DEF_FOR
from hashcredit_gpu.domain.money import AssetRef, Money

REPO = Path(__file__).resolve().parents[3]
SCHEMA_JSON = REPO / "config" / "gpu" / "schema" / "domain-v1.schema.json"

ULID_A = "01J000000000000000000000AA"
ULID_B = "01J000000000000000000000BB"
ULID_C = "01J000000000000000000000CC"
ULID_D = "01J000000000000000000000DD"
ULID_E = "01J000000000000000000000EE"
ULID_F = "01J000000000000000000000FF"
ADDR1 = "0x" + "a1" * 20
ADDR2 = "0x" + "b2" * 20
HASH1 = "0x" + "c3" * 32
MUSDT = "0x" + "d4" * 20


# ---------------------------------------------------------------- helpers


def run(conn, sql, params=None):
    with conn.cursor() as cur:
        cur.execute(sql, params)
    conn.commit()


def expect_error(conn, exc, sql, params=None, match: str | None = None):
    with pytest.raises(exc) as ei:
        with conn.cursor() as cur:
            cur.execute(sql, params)
    conn.rollback()
    if match:
        assert match in str(ei.value), str(ei.value)


def seed_base(conn, *, provider_profile="NATIVE_TESTNET", provider_test_only=True):
    run(conn, "INSERT INTO legal_entities (legal_entity_id, jurisdiction) VALUES (%s, NULL)", (ULID_A,))
    run(conn, "INSERT INTO borrowers (borrower_id, legal_entity_id) VALUES (%s, %s)", (ULID_B, ULID_A))
    run(
        conn,
        "INSERT INTO providers (provider_id, display_name, source_env_id, source_chain_key, source_chain_id, execution_profile, environment_status, test_only) "
        "VALUES ('mockdepin-testonly', 'MockDePIN (TEST_ONLY)', 'cc3-testnet', 1, 11155111, %s, 'PROBED', %s)",
        (provider_profile, provider_test_only),
    )
    run(
        conn,
        "INSERT INTO provider_accounts (provider_account_id, provider_id, external_account_id, borrower_id) "
        "VALUES ('mockdepin-testonly:acct-A', 'mockdepin-testonly', 'acct-A', %s)",
        (ULID_B,),
    )
    run(conn, "INSERT INTO policy_versions (policy_version_id, test_only) VALUES ('pol-test', true)")
    run(conn, "INSERT INTO terms_versions (terms_version_id, test_only) VALUES ('terms-test', true)")
    run(
        conn,
        "INSERT INTO policy_versions (policy_version_id, approved_by, approved_at, test_only) VALUES ('pol-prod', 'credit', now(), false)",
    )
    run(
        conn,
        "INSERT INTO terms_versions (terms_version_id, approved_by, approved_at, test_only) VALUES ('terms-prod', 'ceo', now(), false)",
    )


def insert_facility(conn, fid, *, profile, policy="pol-test", terms="terms-test", state="DRAFT", control=None, funded_version=None, test_only_terms=True, principal=0):
    run(
        conn,
        "INSERT INTO facilities (facility_id, borrower_id, vault_id, loan_chain_id, loan_token_address, loan_decimals, state, terms_version_id, "
        "policy_version_id, execution_profile, control_agreement_id, funded_agreement_version, test_only_terms, principal) "
        "VALUES (%s, %s, 'vault-1', 102031, %s, 6, %s, %s, %s, %s, %s, %s, %s, %s)",
        (fid, ULID_B, MUSDT, state, terms, policy, profile, control, funded_version, test_only_terms, principal),
    )


def insert_e2_agreement(conn, cid=ULID_C, version=1):
    run(
        conn,
        "INSERT INTO control_agreements (control_agreement_id, borrower_id, provider_account_id, control_grade, subject, receiver_chain_id, "
        "receiver_address, change_authority, agreement_hash, version, effective_from, poc_ref) "
        "VALUES (%s, %s, 'mockdepin-testonly:acct-A', 'E2', '[\"REWARD_RECEIVER\"]', 11155111, %s, 'PARTNER', %s, %s, now(), 'doc://poc/GPU-009')",
        (cid, ULID_B, ADDR1, HASH1, version),
    )


# ---------------------------------------------------------------- enum parity


def test_enums_match_json_schema():
    schema = json.loads(SCHEMA_JSON.read_text())
    for enum_cls, def_name in SCHEMA_DEF_FOR.items():
        assert [m.value for m in enum_cls] == schema["$defs"][def_name]["enum"], def_name


def test_money_is_exact_and_asset_bound():
    usd = AssetRef(chain_id=102031, address=MUSDT, symbol="mUSDT", decimals=6)
    a = Money(amount="5000000000", asset=usd)
    b = Money(amount="250000000", asset=usd)
    assert (a - b).amount == "4750000000"
    with pytest.raises(ValueError):
        Money(amount="1.5", asset=usd)
    other = AssetRef(chain_id=11155111, address=ADDR1, symbol="USDC", decimals=6)
    with pytest.raises(ValueError):
        _ = a + Money(amount="1", asset=other)


# ---------------------------------------------------------------- constraints


def test_migrated_schema_has_expected_tables_and_triggers(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY 1")
        tables = {r[0] for r in cur.fetchall()}
        cur.execute("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal ORDER BY 1")
        triggers = {r[0] for r in cur.fetchall()}
    for t in ["providers", "legal_entities", "borrowers", "borrower_wallets", "provider_accounts", "account_authorizations",
              "gpu_assets", "asset_identity_keys", "asset_provider_assignments", "asset_encumbrances", "custody_documents",
              "policy_versions", "terms_versions", "control_agreements", "control_observations", "facilities",
              "credit_decisions", "facility_state_transitions", "alembic_version"]:
        assert t in tables, t
    assert {"trg_credit_decisions_profile_match", "trg_facilities_production_isolation"} <= triggers


def test_required_verification_is_always_native(conn):
    seed_base(conn)
    expect_error(conn, errors.CheckViolation,
                 "INSERT INTO providers (provider_id, display_name, source_env_id, source_chain_key, source_chain_id, execution_profile, environment_status, required_verification, test_only) "
                 "VALUES ('x', 'x', 'cc3-testnet', 1, 11155111, 'NATIVE_TESTNET', 'PROBED', 'OFFCHAIN_ASSERTION', true)")
    expect_error(conn, errors.CheckViolation,
                 "INSERT INTO facilities (facility_id, borrower_id, vault_id, loan_chain_id, loan_decimals, terms_version_id, policy_version_id, execution_profile, required_verification) "
                 "VALUES (%s, %s, 'v', 102031, 6, 'terms-test', 'pol-test', 'NATIVE_TESTNET', 'LOCAL_MOCK')", (ULID_D, ULID_B))


def test_provider_account_id_format_and_uniqueness(conn):
    seed_base(conn)
    expect_error(conn, errors.UniqueViolation,
                 "INSERT INTO provider_accounts (provider_account_id, provider_id, external_account_id, borrower_id) VALUES ('mockdepin-testonly:acct-A', 'mockdepin-testonly', 'acct-A', %s)", (ULID_B,))
    expect_error(conn, errors.CheckViolation,
                 "INSERT INTO provider_accounts (provider_account_id, provider_id, external_account_id, borrower_id) VALUES ('wrong-id', 'mockdepin-testonly', 'acct-B', %s)", (ULID_B,))
    expect_error(conn, errors.CheckViolation,
                 "INSERT INTO provider_accounts (provider_account_id, provider_id, external_account_id, borrower_id, credential_ref) VALUES ('mockdepin-testonly:acct-C', 'mockdepin-testonly', 'acct-C', %s, 'sk_live_plaintext')", (ULID_B,))


def test_wallet_linked_to_one_borrower_at_a_time(conn):
    seed_base(conn)
    run(conn, "INSERT INTO legal_entities (legal_entity_id) VALUES (%s)", (ULID_E,))
    run(conn, "INSERT INTO borrowers (borrower_id, legal_entity_id) VALUES (%s, %s)", (ULID_F, ULID_E))
    run(conn, "INSERT INTO borrower_wallets (borrower_id, chain_id, address, role) VALUES (%s, 102031, %s, 'SIGNER')", (ULID_B, ADDR1))
    expect_error(conn, errors.UniqueViolation,
                 "INSERT INTO borrower_wallets (borrower_id, chain_id, address, role) VALUES (%s, 102031, %s, 'SIGNER')", (ULID_F, ADDR1))
    run(conn, "UPDATE borrower_wallets SET released_at = now() WHERE address = %s", (ADDR1,))
    run(conn, "INSERT INTO borrower_wallets (borrower_id, chain_id, address, role) VALUES (%s, 102031, %s, 'SIGNER')", (ULID_F, ADDR1))
    expect_error(conn, errors.CheckViolation,
                 "INSERT INTO borrower_wallets (borrower_id, chain_id, address, role) VALUES (%s, 102031, %s, 'SIGNER')", (ULID_B, "0xNOTLOWERCASEHEX"))


def test_asset_identity_and_single_open_assignment(conn):
    seed_base(conn)
    run(conn, "INSERT INTO provider_accounts (provider_account_id, provider_id, external_account_id, borrower_id) VALUES ('mockdepin-testonly:acct-B', 'mockdepin-testonly', 'acct-B', %s)", (ULID_B,))
    run(conn, "INSERT INTO gpu_assets (asset_id, kind, ownership) VALUES (%s, 'PHYSICAL_GPU', 'OWNED')", (ULID_C,))
    run(conn, "INSERT INTO asset_identity_keys (asset_id, scheme, value, provenance) VALUES (%s, 'SERIAL', 'SN-1', '{}')", (ULID_C,))
    # the same serial cannot become a second asset
    run(conn, "INSERT INTO gpu_assets (asset_id, kind, ownership) VALUES (%s, 'PHYSICAL_GPU', 'OWNED')", (ULID_D,))
    expect_error(conn, errors.UniqueViolation, "INSERT INTO asset_identity_keys (asset_id, scheme, value, provenance) VALUES (%s, 'SERIAL', 'SN-1', '{}')", (ULID_D,))
    # one open assignment per asset
    run(conn, "INSERT INTO asset_provider_assignments (assignment_id, asset_id, provider_account_id, started_at, reason, provenance) VALUES (%s, %s, 'mockdepin-testonly:acct-A', '2026-07-01', 'ONBOARD', '{}')", (ULID_E, ULID_C))
    expect_error(conn, errors.UniqueViolation,
                 "INSERT INTO asset_provider_assignments (assignment_id, asset_id, provider_account_id, started_at, reason, provenance) VALUES (%s, %s, 'mockdepin-testonly:acct-B', '2026-09-01', 'MOVE', '{}')", (ULID_F, ULID_C))
    run(conn, "UPDATE asset_provider_assignments SET ended_at = '2026-09-01' WHERE assignment_id = %s", (ULID_E,))
    run(conn, "INSERT INTO asset_provider_assignments (assignment_id, asset_id, provider_account_id, started_at, reason, provenance) VALUES (%s, %s, 'mockdepin-testonly:acct-B', '2026-09-01', 'MOVE', '{}')", (ULID_F, ULID_C))
    # MIG child must reference an existing parent; eligibility needs confirmed ownership
    expect_error(conn, errors.ForeignKeyViolation, "INSERT INTO gpu_assets (asset_id, kind, parent_asset_id) VALUES (%s, 'MIG_PARTITION', %s)", (ULID_A, "01J000000000000000000000ZZ"))
    expect_error(conn, errors.CheckViolation, "INSERT INTO gpu_assets (asset_id, kind, ownership, eligible) VALUES (%s, 'PHYSICAL_GPU', 'UNKNOWN', true)", (ULID_A,))


def test_control_agreement_e2_requires_partner_authority_hash_and_poc(conn):
    seed_base(conn)
    expect_error(conn, errors.CheckViolation,
                 "INSERT INTO control_agreements (control_agreement_id, borrower_id, provider_account_id, control_grade, change_authority) "
                 "VALUES (%s, %s, 'mockdepin-testonly:acct-A', 'E2', 'BORROWER_ALONE')", (ULID_C, ULID_B))
    expect_error(conn, errors.CheckViolation,
                 "INSERT INTO control_agreements (control_agreement_id, borrower_id, provider_account_id, control_grade, change_authority, receiver_address, effective_from) "
                 "VALUES (%s, %s, 'mockdepin-testonly:acct-A', 'E2', 'PARTNER', %s, now())", (ULID_C, ULID_B, ADDR1))  # no hash / poc_ref
    insert_e2_agreement(conn)
    expect_error(conn, errors.UniqueViolation, "INSERT INTO control_agreements (control_agreement_id, borrower_id, provider_account_id, version) VALUES (%s, %s, 'mockdepin-testonly:acct-A', 1)", (ULID_D, ULID_B))
    # E0 drafts need none of that
    run(conn, "INSERT INTO control_agreements (control_agreement_id, borrower_id, provider_account_id, version) VALUES (%s, %s, 'mockdepin-testonly:acct-A', 2)", (ULID_D, ULID_B))


def test_facility_money_and_state_invariants(conn):
    seed_base(conn)
    insert_facility(conn, ULID_D, profile="NATIVE_TESTNET")
    expect_error(conn, errors.CheckViolation, "UPDATE facilities SET principal = -1 WHERE facility_id = %s", (ULID_D,))
    expect_error(conn, errors.CheckViolation, "UPDATE facilities SET advance_rate_bps = 10001 WHERE facility_id = %s", (ULID_D,))
    # ACTIVE requires a control agreement + funded version
    expect_error(conn, errors.CheckViolation, "UPDATE facilities SET state = 'ACTIVE' WHERE facility_id = %s", (ULID_D,), match="ck_facilities_funded_requires_control")
    insert_e2_agreement(conn)
    run(conn, "UPDATE facilities SET state = 'ACTIVE', control_agreement_id = %s, funded_agreement_version = 1, principal = 1000 WHERE facility_id = %s", (ULID_C, ULID_D))
    # REPAID/RELEASED with debt outstanding is impossible
    expect_error(conn, errors.CheckViolation, "UPDATE facilities SET state = 'RELEASED' WHERE facility_id = %s", (ULID_D,), match="ck_facilities_released_debt_zero")
    run(conn, "UPDATE facilities SET principal = 0, state = 'REPAID' WHERE facility_id = %s", (ULID_D,))
    # transitions audit never accepts oracle/keeper authority
    expect_error(conn, errors.CheckViolation,
                 "INSERT INTO facility_state_transitions (facility_id, from_state, to_state, trigger, authority) VALUES (%s, 'ACTIVE', 'REPAID', 'debt_zero', 'oracle')", (ULID_D,))
    run(conn, "INSERT INTO facility_state_transitions (facility_id, from_state, to_state, trigger, authority) VALUES (%s, 'ACTIVE', 'REPAID', 'debt_zero', 'system')", (ULID_D,))


def test_credit_decision_profile_must_match_facility(conn):
    seed_base(conn)
    insert_facility(conn, ULID_D, profile="NATIVE_TESTNET")
    expect_error(conn, psycopg2.errors.CheckViolation,
                 "INSERT INTO credit_decisions (credit_decision_id, facility_id, decided_by, policy_version_id, limit_amount, valid_until, execution_profile) "
                 "VALUES (%s, %s, 'underwriter', 'pol-test', 100, now() + interval '1 day', 'PRODUCTION')", (ULID_E, ULID_D), match="does not match facility profile")
    run(conn, "INSERT INTO credit_decisions (credit_decision_id, facility_id, decided_by, policy_version_id, limit_amount, valid_until, execution_profile) "
              "VALUES (%s, %s, 'underwriter', 'pol-test', 100, now() + interval '1 day', 'NATIVE_TESTNET')", (ULID_E, ULID_D))
    expect_error(conn, errors.CheckViolation,
                 "INSERT INTO credit_decisions (credit_decision_id, facility_id, decided_by, policy_version_id, limit_amount, valid_until, execution_profile) "
                 "VALUES (%s, %s, 'keeper', 'pol-test', 100, now() + interval '1 day', 'NATIVE_TESTNET')", (ULID_F, ULID_D))
    expect_error(conn, errors.CheckViolation,
                 "INSERT INTO credit_decisions (credit_decision_id, facility_id, decided_by, policy_version_id, limit_amount, valid_until, execution_profile) "
                 "VALUES (%s, %s, 'underwriter', 'pol-test', 100, now() - interval '1 day', 'NATIVE_TESTNET')", (ULID_F, ULID_D))


def test_production_facility_rejects_test_only_policy_terms_and_testnet_provider(conn):
    seed_base(conn)  # provider is NATIVE_TESTNET + test_only
    # TEST_ONLY policy/terms → rejected by trigger
    expect_error(conn, errors.CheckViolation,
                 "INSERT INTO facilities (facility_id, borrower_id, vault_id, loan_chain_id, loan_decimals, terms_version_id, policy_version_id, execution_profile, test_only_terms) "
                 "VALUES (%s, %s, 'v', 102030, 6, 'terms-test', 'pol-prod', 'PRODUCTION', false)", (ULID_D, ULID_B), match="TEST_ONLY policy/terms")
    # test_only_terms flag on a production facility → check constraint
    expect_error(conn, errors.CheckViolation,
                 "INSERT INTO facilities (facility_id, borrower_id, vault_id, loan_chain_id, loan_decimals, terms_version_id, policy_version_id, execution_profile, test_only_terms) "
                 "VALUES (%s, %s, 'v', 102030, 6, 'terms-prod', 'pol-prod', 'PRODUCTION', true)", (ULID_D, ULID_B), match="ck_facilities_prod_not_test_terms")
    # production facility bound to a NATIVE_TESTNET / test_only provider's agreement → trigger
    insert_e2_agreement(conn)
    expect_error(conn, errors.CheckViolation,
                 "INSERT INTO facilities (facility_id, borrower_id, vault_id, loan_chain_id, loan_decimals, terms_version_id, policy_version_id, execution_profile, test_only_terms, state, control_agreement_id, funded_agreement_version) "
                 "VALUES (%s, %s, 'v', 102030, 6, 'terms-prod', 'pol-prod', 'PRODUCTION', false, 'ACTIVE', %s, 1)", (ULID_D, ULID_B, ULID_C), match="cannot bind provider with profile NATIVE_TESTNET")
    # a clean production row is accepted
    run(conn, "INSERT INTO facilities (facility_id, borrower_id, vault_id, loan_chain_id, loan_decimals, terms_version_id, policy_version_id, execution_profile, test_only_terms) "
              "VALUES (%s, %s, 'v', 102030, 6, 'terms-prod', 'pol-prod', 'PRODUCTION', false)", (ULID_D, ULID_B))


def test_execution_profile_is_immutable(conn):
    seed_base(conn)
    insert_facility(conn, ULID_D, profile="NATIVE_TESTNET")
    expect_error(conn, errors.CheckViolation, "UPDATE facilities SET execution_profile = 'PRODUCTION', test_only_terms = false WHERE facility_id = %s", (ULID_D,), match="immutable")
    expect_error(conn, errors.CheckViolation, "UPDATE facilities SET execution_profile = 'LOCAL_MOCK' WHERE facility_id = %s", (ULID_D,), match="immutable")


def test_provider_test_only_flag_matches_profile(conn):
    expect_error(conn, errors.CheckViolation,
                 "INSERT INTO providers (provider_id, display_name, source_env_id, source_chain_key, source_chain_id, execution_profile, environment_status, test_only) "
                 "VALUES ('p', 'p', 'cc3-mainnet', 1, 1, 'PRODUCTION', 'UNCONFIRMED', true)")
    expect_error(conn, errors.CheckViolation,
                 "INSERT INTO providers (provider_id, display_name, source_env_id, source_chain_key, source_chain_id, execution_profile, environment_status, test_only) "
                 "VALUES ('p', 'p', 'cc3-testnet', 1, 11155111, 'NATIVE_TESTNET', 'PROBED', false)")


def test_secret_refs_only(conn):
    expect_error(conn, errors.CheckViolation, "INSERT INTO legal_entities (legal_entity_id, registration_ref) VALUES (%s, 'BRN 123-45-67890')", (ULID_A,))
    run(conn, "INSERT INTO legal_entities (legal_entity_id, registration_ref) VALUES (%s, 'vault://kyc/le-1/registration')", (ULID_A,))
