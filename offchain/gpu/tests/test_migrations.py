"""
Migration tests on real PostgreSQL (GPU-015): empty DB → head, downgrade/upgrade cycle, no drift
between ORM metadata and migrated schema, coexistence with a pre-existing legacy table, and a
pg_dump/pg_restore round-trip that preserves ids, relations and sums.
"""

from __future__ import annotations

import json
import subprocess
from decimal import Decimal
from pathlib import Path

import psycopg2
import pytest

from hashcredit_gpu.db.cli import current, downgrade, schema_diff, upgrade

from .conftest import _dsn

REPO = Path(__file__).resolve().parents[3]
DOMAIN_FIXTURE = REPO / "test" / "fixtures" / "gpu" / "domain" / "sample-v1.json"
HEAD = "0006"  # Chain-projected receivable/repayment history (0006) over the durable product API (0005)


def _tables(url: str) -> set[str]:
    with psycopg2.connect(_dsn(url)) as c, c.cursor() as cur:
        cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public'")
        return {r[0] for r in cur.fetchall()}


def test_empty_database_to_head_and_back(fresh_db_url):
    assert current(fresh_db_url) is None
    upgrade(fresh_db_url, "0001")
    assert current(fresh_db_url) == "0001"
    tables = _tables(fresh_db_url)
    assert len(tables) == 19  # 18 domain tables + alembic_version (GPU-015)
    upgrade(fresh_db_url, "0002")
    assert current(fresh_db_url) == "0002"
    assert len(_tables(fresh_db_url)) == 19 + 20 + 1  # + GPU-016 ledgers (0002) + v_cash_ownership view
    upgrade(fresh_db_url, "0003")
    assert current(fresh_db_url) == "0003"
    assert len(_tables(fresh_db_url)) == 19 + 20 + 1 + 2  # + GPU-017 provider_account_links, asset_review_flags (0003)
    upgrade(fresh_db_url, "head")
    assert current(fresh_db_url) == HEAD
    assert len(_tables(fresh_db_url)) == 19 + 20 + 1 + 2 + 9 + 7 + 2  # projector + durable API + history projections
    assert schema_diff(fresh_db_url) == [], "ORM metadata and migrated schema drifted"
    downgrade(fresh_db_url, "base")
    assert current(fresh_db_url) is None
    assert _tables(fresh_db_url) == {"alembic_version"}
    with psycopg2.connect(_dsn(fresh_db_url)) as c, c.cursor() as cur:
        cur.execute("SELECT count(*) FROM pg_trigger WHERE NOT tgisinternal")
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT count(*) FROM pg_proc WHERE proname LIKE 'hcg_%'")
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT count(*) FROM information_schema.views WHERE table_schema='public'")
        assert cur.fetchone()[0] == 0
    upgrade(fresh_db_url, "head")
    assert current(fresh_db_url) == HEAD


def test_upgrade_is_idempotent(migrated_db_url):
    upgrade(migrated_db_url, "head")
    assert current(migrated_db_url) == HEAD


def test_previous_schema_fixture_to_head_preserves_legacy_table(fresh_db_url):
    """A database that already holds the v1 relayer table must migrate to head without touching it."""
    with psycopg2.connect(_dsn(fresh_db_url)) as c, c.cursor() as cur:
        cur.execute(
            "CREATE TABLE processed_payouts (id serial PRIMARY KEY, txid varchar(64) NOT NULL, vout integer NOT NULL, "
            "borrower varchar(42) NOT NULL, amount_sats integer NOT NULL, block_height integer NOT NULL, status varchar(20), "
            "CONSTRAINT uq_txid_vout UNIQUE (txid, vout))"
        )
        cur.execute("INSERT INTO processed_payouts (txid, vout, borrower, amount_sats, block_height, status) VALUES ('ab'||repeat('0', 62), 0, %s, 123456, 800000, 'confirmed')", ("0x" + "a1" * 20,))
        c.commit()
    upgrade(fresh_db_url, "head")
    with psycopg2.connect(_dsn(fresh_db_url)) as c, c.cursor() as cur:
        cur.execute("SELECT txid, vout, amount_sats FROM processed_payouts")
        assert cur.fetchall() == [("ab" + "0" * 62, 0, 123456)]
    assert "facilities" in _tables(fresh_db_url)
    # drift check ignores the legacy table only because it is not part of Base.metadata; it must not be dropped
    downgrade(fresh_db_url, "base")
    assert "processed_payouts" in _tables(fresh_db_url)


def _seed_from_domain_fixture(url: str) -> dict:
    fx = json.loads(DOMAIN_FIXTURE.read_text())
    le = fx["legalEntities"][0]
    brw = fx["borrowers"][0]
    fac = fx["facilities"][0]
    with psycopg2.connect(_dsn(url)) as c, c.cursor() as cur:
        cur.execute("INSERT INTO legal_entities (legal_entity_id, jurisdiction, registration_ref, documents_ref) VALUES (%s, %s, %s, %s)",
                    (le["legalEntityId"], le["jurisdiction"], le["registrationRef"], json.dumps(le["documentsRef"])))
        cur.execute("INSERT INTO borrowers (borrower_id, legal_entity_id, group_id, kyc_status, underwriting_status) VALUES (%s, %s, %s, %s, %s)",
                    (brw["borrowerId"], brw["legalEntityId"], brw["groupId"], brw["kycStatus"], brw["underwritingStatus"]))
        for w in brw["wallets"]:
            cur.execute("INSERT INTO borrower_wallets (borrower_id, chain_id, address, role, verified_at) VALUES (%s, %s, %s, %s, %s)",
                        (brw["borrowerId"], w["chainId"], w["address"].lower(), w["role"], w["verifiedAt"]))
        cur.execute("INSERT INTO providers (provider_id, display_name, source_env_id, source_chain_key, source_chain_id, execution_profile, environment_status, manifest_hash, test_only) "
                    "VALUES ('mockdepin-testonly', 'MockDePIN (TEST_ONLY)', 'cc3-testnet', 1, 11155111, 'NATIVE_TESTNET', 'PROBED', %s, true)", (fx["sourceChains"][0]["manifestHash"],))
        for pa in fx["providerAccounts"]:
            cur.execute("INSERT INTO provider_accounts (provider_account_id, provider_id, external_account_id, borrower_id, roles, auth_scope, credential_ref, control_version, last_verified_at) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        (pa["providerAccountId"], pa["providerId"], pa["externalAccountId"], pa["borrowerId"], json.dumps(pa["roles"]), json.dumps(pa["authScope"]), pa["credentialRef"], pa["controlVersion"], pa["lastVerifiedAt"]))
        for a in fx["assets"]:
            cur.execute("INSERT INTO gpu_assets (asset_id, kind, sku, unit_count, ownership, custodian, location, parent_asset_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                        (a["assetId"], a["kind"], a["sku"], a["unitCount"], a["ownership"], a["custodian"], a["location"], a["parentAssetId"]))
            for k in a["identityKeys"]:
                cur.execute("INSERT INTO asset_identity_keys (asset_id, scheme, value, provenance) VALUES (%s, %s, %s, %s)", (a["assetId"], k["scheme"], k["value"], json.dumps(k["provenance"])))
        for asg in fx["assetAssignments"]:
            cur.execute("INSERT INTO asset_provider_assignments (assignment_id, asset_id, provider_account_id, started_at, ended_at, reason, provenance) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                        (asg["assignmentId"], asg["assetId"], asg["providerAccountId"], asg["from"], asg["to"], asg["reason"], json.dumps(asg["provenance"])))
        cur.execute("INSERT INTO policy_versions (policy_version_id, test_only) VALUES (%s, true)", (fac["policyVersionId"],))
        cur.execute("INSERT INTO terms_versions (terms_version_id, test_only) VALUES (%s, true)", (fac["termsVersionId"],))
        ca = fx["controlAgreements"][0]
        cur.execute("INSERT INTO control_agreements (control_agreement_id, borrower_id, provider_account_id, control_grade, subject, receiver_chain_id, receiver_address, change_authority, agreement_hash, version, effective_from, effective_to, precedence, last_observed_at, observation_provenance, poc_ref) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 1, %s, %s, %s, %s, %s, 'doc://poc/GPU-009-simulated')",
                    (ca["controlAgreementId"], ca["borrowerId"], ca["providerAccountId"], ca["controlGrade"], json.dumps(ca["subject"]), ca["receiver"]["chainId"], ca["receiver"]["address"].lower(), ca["changeAuthority"], ca["agreementHash"], ca["effectiveFrom"], ca["effectiveTo"], ca["precedence"], ca["lastObservedAt"], json.dumps(ca["observationProvenance"])))
        for f in fx["facilities"]:
            cur.execute("INSERT INTO facilities (facility_id, borrower_id, vault_id, loan_chain_id, loan_token_address, loan_decimals, state, approved_cap, advance_rate_bps, terms_version_id, policy_version_id, execution_profile, principal, unpaid_interest, fees, reserved_draws, rate_bps, maturity_at, control_agreement_id, funded_agreement_version, test_only_terms) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        (f["facilityId"], f["borrowerId"], f["vaultId"], f["loanAsset"]["chainId"], f["loanAsset"]["address"].lower(), f["loanAsset"]["decimals"], f["state"], f["approvedCap"]["amount"], f["advanceRateBps"], f["termsVersionId"], f["policyVersionId"], f["executionProfile"], f["principal"]["amount"], f["unpaidInterest"]["amount"], f["fees"]["amount"], f["reservedDraws"]["amount"], f["rateBps"], f["maturityAt"], f["controlAgreementId"], 1 if f["controlAgreementId"] else None, f["testOnlyTerms"]))
        d = fx["creditDecisions"][0]
        cur.execute("INSERT INTO credit_decisions (credit_decision_id, facility_id, decided_by, policy_version_id, inputs, limit_amount, valid_until, status, execution_profile) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (d["creditDecisionId"], d["facilityId"], d["decidedBy"], d["policyVersionId"], json.dumps(d["inputs"]), d["limit"]["amount"], d["validUntil"], d["status"], "NATIVE_TESTNET"))
        c.commit()
    return fx


def _snapshot(url: str) -> dict:
    with psycopg2.connect(_dsn(url)) as c, c.cursor() as cur:
        cur.execute("SELECT facility_id, borrower_id, principal, unpaid_interest, control_agreement_id FROM facilities ORDER BY facility_id")
        facilities = cur.fetchall()
        cur.execute("SELECT sum(principal) + sum(unpaid_interest) + sum(fees) FROM facilities")
        debt = cur.fetchone()[0]
        cur.execute("SELECT assignment_id, asset_id, provider_account_id, ended_at IS NULL FROM asset_provider_assignments ORDER BY assignment_id")
        assignments = cur.fetchall()
        cur.execute("SELECT count(*) FROM asset_identity_keys")
        keys = cur.fetchone()[0]
        cur.execute("SELECT credit_decision_id, facility_id, limit_amount FROM credit_decisions")
        decisions = cur.fetchall()
    return {"facilities": facilities, "debt": debt, "assignments": assignments, "keys": keys, "decisions": decisions}


def test_backup_restore_preserves_ids_relations_and_sums(pg_server_url, fresh_db_url, pg_bindir):
    if pg_bindir is None or not (pg_bindir / "pg_dump").exists():
        pytest.fail("pg_dump/pg_restore not found next to the PostgreSQL binaries; backup/restore cannot be verified")
    upgrade(fresh_db_url, "head")
    fx = _seed_from_domain_fixture(fresh_db_url)
    before = _snapshot(fresh_db_url)
    assert before["debt"] == Decimal(fx["facilities"][0]["principal"]["amount"]) + Decimal(fx["facilities"][0]["unpaidInterest"]["amount"])
    assert len(before["assignments"]) == 3 and sum(1 for a in before["assignments"] if a[3]) == 2  # two open (GPU on B, MIG on B)

    dump = subprocess.run([str(pg_bindir / "pg_dump"), "--format=custom", "--dbname", _dsn(fresh_db_url)], capture_output=True, check=True).stdout
    assert len(dump) > 1000

    # wipe and restore into the same database name
    downgrade(fresh_db_url, "base")
    with psycopg2.connect(_dsn(fresh_db_url)) as c, c.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS alembic_version")
        c.commit()
    subprocess.run([str(pg_bindir / "pg_restore"), "--dbname", _dsn(fresh_db_url), "--no-owner"], input=dump, capture_output=True, check=True)

    after = _snapshot(fresh_db_url)
    assert after == before
    assert current(fresh_db_url) == HEAD
    assert schema_diff(fresh_db_url) == []
    # triggers survive the round-trip and still enforce isolation
    with psycopg2.connect(_dsn(fresh_db_url)) as c, c.cursor() as cur:
        with pytest.raises(psycopg2.errors.CheckViolation):
            cur.execute("UPDATE facilities SET execution_profile = 'PRODUCTION', test_only_terms = false WHERE facility_id = %s", (fx["facilities"][0]["facilityId"],))
        c.rollback()
