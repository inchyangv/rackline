"""GPU-045 integration tests: real PostgreSQL migrations, real EOA login, no RPC or fixtures in API."""

import importlib.util
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from eth_account import Account
from eth_account.messages import encode_typed_data
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from hashcredit_api.gpu.app import create_app
from hashcredit_api.gpu.auth.roles import InMemoryRoleRegistry
from hashcredit_api.gpu.product.settings import ProductSettings
from hashcredit_gpu.db import ledgers as L
from hashcredit_gpu.db import models as M
from hashcredit_gpu.db.projections_models import ChainBlock, ChainCursor, ChainDeployment

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("gpu_product_pg_support", ROOT / "offchain/gpu/tests/conftest.py")
support = importlib.util.module_from_spec(spec)
spec.loader.exec_module(support)
pg_server_url = support.pg_server_url
fresh_db_url = support.fresh_db_url
migrated_db_url = support.migrated_db_url

MANIFEST = "sha256:" + "ab" * 32
BLOCK = "0x" + "cd" * 32
TOKEN = "0x" + "12" * 20
DEPLOYMENT = "00000000000000000000000001"


def uid(n):
    return str(n).zfill(26)


@pytest.fixture
def setup(migrated_db_url):
    wallets = [Account.create() for _ in range(3)]
    cfg = ProductSettings(database_url=migrated_db_url, execution_profile="NATIVE_TESTNET", chain_id=102031,
        deployment_id=DEPLOYMENT, manifest_hash=MANIFEST, app_domain="https://rackline.example.test",
        session_secret="test-only-session-secret-not-for-production-use")
    engine = create_engine(migrated_db_url)
    now = datetime.now(timezone.utc)
    with Session(engine) as session:
        session.add(ChainDeployment(deployment_id=DEPLOYMENT, chain_id=102031, execution_profile="NATIVE_TESTNET",
            env_id="cc3-testnet", manifest_hash=MANIFEST, deployment_block=1, contracts={}, finality_depth=0))
        session.add(M.Provider(provider_id="mockdepin-testonly", display_name="TEST_ONLY provider",
            source_env_id="cc3-testnet", source_chain_key=1, source_chain_id=11155111,
            execution_profile="NATIVE_TESTNET", environment_status="PROBED", manifest_hash=MANIFEST,
            capabilities={"listAssets": True, "claimRevenue": False, "secret": "must-not-leak"}, test_only=True))
        session.add(M.PolicyVersion(policy_version_id="TEST_ONLY", test_only=True))
        session.add(M.TermsVersion(terms_version_id="TEST_ONLY", test_only=True))
        session.flush()
        session.add(ChainBlock(deployment_id=DEPLOYMENT, number=10, hash=BLOCK, parent_hash="0x" + "ef" * 32,
            timestamp=int(now.timestamp()), tier="FINALIZED"))
        session.add(ChainCursor(deployment_id=DEPLOYMENT, last_block_number=10, last_block_hash=BLOCK,
            finalized_block_number=10, updated_at=now))
        for i, wallet in enumerate(wallets[:2], start=1):
            session.add(M.LegalEntity(legal_entity_id=uid(100 + i), registration_ref="doc://private/registration"))
            session.flush()
            session.add(M.Borrower(borrower_id=uid(200 + i), legal_entity_id=uid(100 + i)))
            session.flush()
            session.add(M.BorrowerWallet(borrower_id=uid(200 + i), chain_id=102031,
                address=wallet.address.lower(), role="SIGNER", verified_at=now))
            session.add(M.ProviderAccount(provider_account_id=f"mockdepin-testonly:account-{i}",
                provider_id="mockdepin-testonly", external_account_id=f"account-{i}", borrower_id=uid(200 + i),
                credential_ref="vault://private/provider-credential"))
            session.add(M.Facility(facility_id=uid(300 + i), borrower_id=uid(200 + i), vault_id="gpu-vault",
                loan_chain_id=102031, loan_token_address=TOKEN, loan_decimals=6, state="DRAFT",
                principal=Decimal("9007199254740993123456789"), unpaid_interest=Decimal("37"), fees=Decimal("3"),
                terms_version_id="TEST_ONLY", policy_version_id="TEST_ONLY", execution_profile="NATIVE_TESTNET"))
            session.flush()
            for j in range(2):
                session.add(L.Receivable(receivable_id=uid(400 + i * 10 + j),
                    economic_event_id=f"mockdepin-testonly/account-{i}/OBLIGATION/invoice-{j}",
                    provider_account_id=f"mockdepin-testonly:account-{i}", obligation_ref=f"invoice-{j}",
                    asset_chain_id=11155111, asset_token_address=TOKEN, asset_decimals=6,
                    gross=9999, net=9000, paid_amount=0, unpaid_amount=9000, execution_profile="NATIVE_TESTNET"))
            session.add(L.Settlement(settlement_id=uid(500 + i), provider_account_id=f"mockdepin-testonly:account-{i}",
                settlement_ref=f"settlement-{i}", asset_chain_id=11155111, asset_token_address=TOKEN,
                asset_decimals=6, source_amount=9000, execution_profile="NATIVE_TESTNET"))
        session.flush()
        session.add(L.ExceptionCase(exception_id=uid(700), kind="SOURCE_REVIEW", severity="BLOCKING",
            entity_table="receivables", entity_id=uid(410), detail={"secret": "must-not-leak"}))
        session.commit()
    roles = InMemoryRoleRegistry()
    roles.grant(wallets[2].address, "operator")
    app = create_app(cfg, roles=roles)
    with TestClient(app) as client:
        yield client, engine, wallets, app
    engine.dispose()


def login(client, wallet):
    challenge = client.post("/gpu/auth/challenge", json={"wallet": wallet.address, "chainId": 102031})
    assert challenge.status_code == 200, challenge.text
    data = challenge.json()
    signature = wallet.sign_message(encode_typed_data(full_message=data["typedData"])).signature.hex()
    response = client.post("/gpu/auth/verify", json={"wallet": wallet.address, "chainId": 102031,
        "nonce": data["nonce"], "signature": signature})
    assert response.status_code == 200, response.text
    return {"Authorization": "Bearer " + response.json()["token"]}


def test_unconfigured_liveness_is_not_readiness():
    with TestClient(create_app(ProductSettings(_env_file=None, database_url=None, chain_id=None, session_secret=None))) as client:
        assert client.get("/health").json()["status"] == "alive"
        response = client.get("/ready")
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "UPSTREAM_UNAVAILABLE"
        assert response.headers["Cache-Control"] == "no-store"


def test_actual_db_rows_exact_amounts_and_explicit_noncanonical_financials(setup):
    client, _, wallets, _ = setup
    headers = login(client, wallets[0])
    assert client.get("/ready").status_code == 200
    response = client.get("/v1/facilities", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["data"]) == 1
    row = body["data"][0]
    assert row["recordedPrincipal"] == {"amount": "9007199254740993123456789", "asset": {"chainId": 102031, "address": TOKEN, "decimals": 6}}
    assert row["availableDraw"] is None and row["canonicalFinancials"] is None
    assert row["financialReadiness"] == "UNAVAILABLE_ID_BINDING"
    assert body["meta"]["canonicalBlock"]["hash"] == BLOCK
    assert body["meta"]["canonicalScope"] == "INDEXER_WATERMARK_ONLY"
    assert body["meta"]["financialAuthorization"] is False


def test_idor_and_absent_are_same_after_authentication(setup):
    client, _, wallets, _ = setup
    assert client.get("/v1/facilities").status_code == 401
    headers = login(client, wallets[0])
    other = client.get(f"/v1/facilities/{uid(302)}", headers=headers)
    missing = client.get(f"/v1/facilities/{uid(999)}", headers=headers)
    assert other.status_code == missing.status_code == 404
    assert other.json()["error"]["code"] == missing.json()["error"]["code"] == "NOT_FOUND"
    assert client.get("/v1/operations", headers=headers).status_code == 403


def test_scoped_pagination_and_invalid_cursor(setup):
    client, _, wallets, _ = setup
    headers = login(client, wallets[0])
    first = client.get("/v1/receivables?limit=1", headers=headers).json()
    assert len(first["data"]) == 1 and first["pagination"]["nextCursor"]
    second = client.get("/v1/receivables", params={"limit": 1, "cursor": first["pagination"]["nextCursor"]}, headers=headers).json()
    assert second["data"][0]["receivableId"] != first["data"][0]["receivableId"]
    assert second["pagination"]["nextCursor"] is None
    assert client.get("/v1/receivables?limit=101", headers=headers).status_code == 422
    assert client.get("/v1/receivables?cursor=bogus", headers=headers).status_code == 422
    assert client.get("/v1/connections", params={"cursor": first["pagination"]["nextCursor"]}, headers=headers).status_code == 422


def test_credentials_and_arbitrary_json_never_serialized(setup):
    client, _, wallets, _ = setup
    headers = login(client, wallets[2])
    responses = [client.get(f"/v1/{resource}", headers=headers) for resource in ("providers", "connections", "operations")]
    assert all(response.status_code == 200 for response in responses)
    payload = " ".join(response.text for response in responses)
    assert "must-not-leak" not in payload and "vault://" not in payload and "doc://" not in payload
    assert responses[0].json()["data"][0]["capabilities"]["claimRevenue"] == "UNSUPPORTED"
    assert responses[1].json()["data"][0]["credentialConfigured"] is True


def test_missing_and_stale_projections_do_not_create_ready_credit(setup):
    client, engine, wallets, _ = setup
    headers = login(client, wallets[0])
    with engine.begin() as connection:
        connection.execute(text("UPDATE chain_cursors SET updated_at=:at"), {"at": datetime.now(timezone.utc) - timedelta(hours=1)})
    assert client.get("/ready").status_code == 503
    stale = client.get("/v1/facilities", headers=headers)
    assert stale.status_code == 200
    assert stale.json()["meta"]["freshness"] == "STALE"
    assert stale.json()["data"][0]["availableDraw"] is None
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM chain_cursors"))
    assert client.get("/ready").status_code == 503
    assert client.get("/v1/facilities", headers=headers).status_code == 503


def test_raw_states_are_separate_and_not_proof_or_cash(setup):
    client, _, wallets, _ = setup
    headers = login(client, wallets[0])
    receivable = client.get("/v1/receivables", headers=headers).json()["data"][0]
    assert receivable["unpaidAmount"]["amount"] == "9000"
    assert receivable["evidence"]["nativeStatus"] is None
    assert receivable["evidence"]["businessEligibility"] is None
    assert receivable["evidence"]["earningsProvenance"] == "SIMULATED"
    settlement = client.get("/v1/settlements", headers=headers).json()["data"][0]
    assert settlement["state"] == "ANNOUNCED"
    assert settlement["destinationReceipts"] == []
    assert settlement["destinationCashRecorded"] is False


def test_unregistered_wallet_gets_no_borrower_privileges_and_released_link_revokes(setup):
    client, engine, wallets, _ = setup
    unknown = login(client, Account.create())
    assert client.get("/v1/me", headers=unknown).json()["data"]["roles"] == []
    assert client.get("/v1/facilities", headers=unknown).status_code == 403
    headers = login(client, wallets[0])
    with engine.begin() as connection:
        connection.execute(text("UPDATE borrower_wallets SET released_at=now() WHERE address=:wallet"), {"wallet": wallets[0].address.lower()})
    assert client.get("/v1/facilities", headers=headers).status_code == 401


def test_mutations_cannot_stub_success_or_mark_verified(setup):
    client, engine, wallets, _ = setup
    headers = login(client, wallets[2])
    assert client.post("/v1/connections", headers=headers, json={"nativeStatus": "VERIFIED"}).status_code == 422
    for path in ("/v1/facilities", "/v1/operations/test/acknowledge"):
        assert client.post(path, headers=headers, json={"nativeStatus": "VERIFIED"}).status_code == 503
    assert client.post("/v1/evidence/mark-verified", headers=headers, json={}).status_code == 405
    for path in ("/claim/register-and-grant", "/btc/proof", "/gpu/facilities/test/fund"):
        assert client.post(path, headers=headers, json={}).status_code == 404
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM provider_accounts")) == 2
        assert connection.scalar(text("SELECT count(*) FROM tx_intents")) == 0


def test_malformed_login_signature_is_sanitized_422(setup):
    client, _, wallets, _ = setup
    response = client.post("/gpu/auth/verify", json={"wallet": wallets[0].address, "chainId": 102031,
        "nonce": "0x" + "00" * 32, "signature": "secret-token-non-hex"})
    assert response.status_code == 422
    assert "secret-token" not in response.text


def test_lp_missing_projection_is_not_fake_zero_nav(setup):
    client, _, wallets, _ = setup
    response = client.get("/v1/lp", headers=login(client, wallets[2]))
    assert response.status_code == 503
    assert "data" not in response.json()


def test_openapi_contract_and_no_btc_import():
    code = '''
import importlib.abc, sys
class RejectBitcoin(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "coincurve" or fullname.startswith(("hashcredit_api.bitcoin", "hashcredit_api.btc", "hashcredit_api.proof", "hashcredit_api.claim", "hashcredit_api.main")):
            raise ImportError("BTC dependency forbidden")
sys.meta_path.insert(0, RejectBitcoin())
from hashcredit_api.gpu.app import create_app
app = create_app()
schema = app.openapi()
assert "/v1/facilities" in schema["paths"]
assert "Page_FacilityDTO_" in schema["components"]["schemas"]
assert "hashcredit_api.main" not in sys.modules
print("BTC-free factory and typed OpenAPI OK")
'''
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("profile,chain", [("LOCAL_MOCK", 102031), ("NATIVE_TESTNET", 102030), ("PRODUCTION", 31337)])
def test_wrong_chain_profile_fails_closed(profile, chain):
    with pytest.raises(ValueError):
        ProductSettings(execution_profile=profile, chain_id=chain)
