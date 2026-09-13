"""
GPU-018: wallet auth, object-level permissions, credential redaction, and the R2 proof-query guard.

All tests run against `create_app(Settings(...))` with in-memory stores; no RPC, no network.
"""

from __future__ import annotations

import json
import logging
import time

import pytest
from eth_account import Account
from fastapi.testclient import TestClient

from hashcredit_api.config import Settings
from hashcredit_api.gpu.auth.eip712 import DOMAIN_NAME, LoginMessage
from hashcredit_api.gpu.auth.erc1271 import FakeErc1271Checker
from hashcredit_api.gpu.auth.session import issue_session, parse_session
from hashcredit_api.gpu.proofs.outbound import is_allowed_outbound
from hashcredit_api.gpu.secrets import EnvSecretStore, Redactor, is_secret_ref
from hashcredit_api.main import create_app

CHAIN = 102031
SECRET = "test-session-secret-value-0123456789abcdef"
PROVIDER_SECRET = "prov-token-SUPERSECRETVALUE-9f8e7d6c5b4a"
ESCROW = "0x00000000000000000000000000000000000000e1"
TX = "0x" + "ab" * 32

BORROWER_A_KEY = "0x" + "11" * 32
BORROWER_B_KEY = "0x" + "22" * 32
UNDERWRITER_KEY = "0x" + "33" * 32
TREASURY_KEY = "0x" + "44" * 32
KEEPER_KEY = "0x" + "55" * 32


def _settings(**overrides) -> Settings:
    base = dict(
        api_profile="testnet_demo",
        chain_id=CHAIN,
        gpu_session_secret=SECRET,
        gpu_provider_allowlist=["mockdepin-testonly"],
        gpu_emitter_allowlist={"cc3-testnet.sepolia.v1": [ESCROW], "local-mock.anvil.v1": [ESCROW]},
    )
    base.update(overrides)
    return Settings(**base)


@pytest.fixture
def app():
    return create_app(_settings())


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def rt(app):
    return app.state.gpu


def _wallet(key: str) -> str:
    return Account.from_key(key).address


def login(client: TestClient, key: str, *, chain_id: int = CHAIN, sign_chain: int | None = None,
          sign_domain: str | None = None, borrower_hint: str = "") -> dict:
    """Full challenge → sign → verify flow for an EOA. Returns the verify response JSON (or error JSON)."""
    wallet = _wallet(key)
    ch = client.post("/gpu/auth/challenge", json={"wallet": wallet, "chainId": chain_id, "borrowerHint": borrower_hint})
    assert ch.status_code == 200, ch.text
    c = ch.json()
    msg = LoginMessage(
        wallet=wallet,
        chain_id=sign_chain if sign_chain is not None else chain_id,
        app_domain=sign_domain if sign_domain is not None else c["typedData"]["message"]["appDomain"],
        nonce=bytes.fromhex(c["nonce"][2:]),
        issued_at=c["issuedAt"],
        expires_at=c["expiresAt"],
        borrower_hint=borrower_hint,
    )
    sig = Account.sign_message(msg.signable(), key).signature.hex()
    r = client.post("/gpu/auth/verify", json={"wallet": wallet, "chainId": chain_id, "nonce": c["nonce"], "signature": sig})
    return {"status": r.status_code, "body": r.json(), "nonce": c["nonce"], "signature": sig, "wallet": wallet}


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ----------------------------------------------------------------------------- authentication


class TestLogin:
    def test_eoa_login_issues_bearer_session_bound_to_wallet(self, client, rt):
        rt.ownership.link_wallet(_wallet(BORROWER_A_KEY), "brw_A")
        rt.known_borrowers.add("brw_A")
        res = login(client, BORROWER_A_KEY)
        assert res["status"] == 200, res["body"]
        assert res["body"]["tokenType"] == "Bearer"
        assert res["body"]["borrowerId"] == "brw_A"
        assert "borrower" in res["body"]["roles"]
        me = client.get("/gpu/me", headers=bearer(res["body"]["token"]))
        assert me.status_code == 200 and me.json()["wallet"] == res["wallet"]

    def test_nonce_replay_rejected(self, client):
        res = login(client, BORROWER_A_KEY)
        assert res["status"] == 200
        replay = client.post(
            "/gpu/auth/verify",
            json={"wallet": res["wallet"], "chainId": CHAIN, "nonce": res["nonce"], "signature": res["signature"]},
        )
        assert replay.status_code == 401
        assert replay.json()["detail"]["code"] == "UNAUTHENTICATED"

    def test_signature_over_other_chain_or_domain_rejected(self, client):
        assert login(client, BORROWER_A_KEY, sign_chain=1)["status"] == 401
        assert login(client, BORROWER_A_KEY, sign_domain="evil.example")["status"] == 401

    def test_challenge_for_other_chain_rejected(self, client):
        r = client.post("/gpu/auth/challenge", json={"wallet": _wallet(BORROWER_A_KEY), "chainId": 1})
        assert r.status_code == 422

    def test_signature_by_other_caller_rejected(self, client):
        wallet_a = _wallet(BORROWER_A_KEY)
        ch = client.post("/gpu/auth/challenge", json={"wallet": wallet_a, "chainId": CHAIN}).json()
        msg = LoginMessage(wallet_a, CHAIN, ch["typedData"]["message"]["appDomain"], bytes.fromhex(ch["nonce"][2:]),
                           ch["issuedAt"], ch["expiresAt"])
        sig = Account.sign_message(msg.signable(), BORROWER_B_KEY).signature.hex()  # Mallory signs A's challenge
        r = client.post("/gpu/auth/verify", json={"wallet": wallet_a, "chainId": CHAIN, "nonce": ch["nonce"], "signature": sig})
        assert r.status_code == 401
        # …and cannot present A's challenge as her own wallet either (binding mismatch)
        r2 = client.post("/gpu/auth/verify", json={"wallet": _wallet(BORROWER_B_KEY), "chainId": CHAIN, "nonce": ch["nonce"], "signature": sig})
        assert r2.status_code == 401

    def test_expired_challenge_rejected(self, monkeypatch):
        app = create_app(_settings(gpu_challenge_ttl_seconds=1))
        client = TestClient(app)
        wallet = _wallet(BORROWER_A_KEY)
        ch = client.post("/gpu/auth/challenge", json={"wallet": wallet, "chainId": CHAIN}).json()
        msg = LoginMessage(wallet, CHAIN, ch["typedData"]["message"]["appDomain"], bytes.fromhex(ch["nonce"][2:]),
                           ch["issuedAt"], ch["expiresAt"])
        sig = Account.sign_message(msg.signable(), BORROWER_A_KEY).signature.hex()
        real_time = time.time
        monkeypatch.setattr(time, "time", lambda: real_time() + 5)
        r = client.post("/gpu/auth/verify", json={"wallet": wallet, "chainId": CHAIN, "nonce": ch["nonce"], "signature": sig})
        assert r.status_code == 401 and "expired" in r.json()["detail"]["message"]

    def test_expired_session_rejected(self, client, rt):
        token, _ = issue_session(
            secret=SECRET,
            payload_fields={"wallet": _wallet(BORROWER_A_KEY), "chain_id": CHAIN, "borrower_id": None, "roles": (), "role_epochs": {}},
            ttl_seconds=1,
        )
        assert parse_session(secret=SECRET, token=token, now=int(time.time()) + 5) is None
        # tampered MAC
        assert parse_session(secret=SECRET, token=token[:-2] + "zz") is None
        # foreign secret
        assert parse_session(secret="other-secret", token=token) is None

    def test_role_revocation_invalidates_outstanding_sessions(self, client, rt):
        rt.roles.grant(_wallet(UNDERWRITER_KEY), "underwriter")
        res = login(client, UNDERWRITER_KEY)
        assert res["status"] == 200 and "underwriter" in res["body"]["roles"]
        tok = res["body"]["token"]
        assert client.post("/gpu/facilities/fac_1/underwrite", headers=bearer(tok)).status_code == 200
        rt.roles.revoke(_wallet(UNDERWRITER_KEY), "underwriter")
        r = client.post("/gpu/facilities/fac_1/underwrite", headers=bearer(tok))
        assert r.status_code == 401 and "revoked" in r.json()["detail"]["message"]
        # a key-epoch rotation without membership change also ends the session
        rt.roles.grant(_wallet(UNDERWRITER_KEY), "underwriter")
        tok2 = login(client, UNDERWRITER_KEY)["body"]["token"]
        rt.roles.rotate("underwriter")
        assert client.get("/gpu/me", headers=bearer(tok2)).status_code == 401

    def test_released_wallet_link_ends_borrower_session(self, client, rt):
        wallet = _wallet(BORROWER_A_KEY)
        rt.ownership.link_wallet(wallet, "brw_A")
        rt.known_borrowers.add("brw_A")
        tok = login(client, BORROWER_A_KEY)["body"]["token"]
        assert client.get("/gpu/borrowers/brw_A", headers=bearer(tok)).status_code == 200
        rt.ownership._wallets.pop(wallet.lower())  # link released
        assert client.get("/gpu/borrowers/brw_A", headers=bearer(tok)).status_code == 401

    def test_erc1271_wallet_uses_injected_checker_and_fails_closed(self, client, rt):
        contract_wallet = "0x" + "c0" * 20
        ch = client.post("/gpu/auth/challenge", json={"wallet": contract_wallet, "chainId": CHAIN}).json()
        body = {"wallet": contract_wallet, "chainId": CHAIN, "nonce": ch["nonce"], "signature": "0x" + "ab" * 70, "walletKind": "erc1271"}
        # default checker rejects everything (no RPC configured)
        assert client.post("/gpu/auth/verify", json=body).status_code == 401
        # fake checker: only the exact (wallet, digest, signature) triple passes
        fake = FakeErc1271Checker()
        rt.erc1271 = fake
        ch2 = client.post("/gpu/auth/challenge", json={"wallet": contract_wallet, "chainId": CHAIN}).json()
        msg = LoginMessage(contract_wallet, CHAIN, ch2["typedData"]["message"]["appDomain"], bytes.fromhex(ch2["nonce"][2:]),
                           ch2["issuedAt"], ch2["expiresAt"])
        fake.accept(contract_wallet, msg.digest(), bytes.fromhex("ab" * 70))
        wrong = dict(body, nonce=ch2["nonce"], signature="0x" + "cd" * 70)
        assert client.post("/gpu/auth/verify", json=wrong).status_code == 401
        ch3 = client.post("/gpu/auth/challenge", json={"wallet": contract_wallet, "chainId": CHAIN}).json()
        msg3 = LoginMessage(contract_wallet, CHAIN, ch3["typedData"]["message"]["appDomain"], bytes.fromhex(ch3["nonce"][2:]),
                            ch3["issuedAt"], ch3["expiresAt"])
        fake.accept(contract_wallet, msg3.digest(), bytes.fromhex("ab" * 70))
        ok = client.post("/gpu/auth/verify", json=dict(body, nonce=ch3["nonce"]))
        assert ok.status_code == 200 and fake.calls >= 2

    def test_login_domain_is_not_the_onchain_authorization_domain(self, client):
        ch = client.post("/gpu/auth/challenge", json={"wallet": _wallet(BORROWER_A_KEY), "chainId": CHAIN}).json()
        dom = ch["typedData"]["domain"]
        assert dom["name"] == DOMAIN_NAME and "verifyingContract" not in dom and "salt" in dom
        assert ch["typedData"]["primaryType"] == "Login"  # never `Assertion` (AuthorizationVerifier typehash)

    def test_auth_not_configured_without_secret(self):
        app = create_app(Settings(chain_id=CHAIN))
        c = TestClient(app)
        r = c.post("/gpu/auth/challenge", json={"wallet": _wallet(BORROWER_A_KEY), "chainId": CHAIN})
        assert r.status_code == 503
        assert c.get("/gpu/me", headers=bearer("x.y")).status_code == 503

    def test_auth_rate_limit(self):
        app = create_app(_settings(gpu_auth_rate_limit_per_minute=3))
        c = TestClient(app)
        codes = [c.post("/gpu/auth/challenge", json={"wallet": _wallet(BORROWER_A_KEY), "chainId": CHAIN}).status_code for _ in range(5)]
        assert codes[:3] == [200, 200, 200] and codes[3] == 429 and codes[4] == 429

    def test_body_size_limit_and_security_headers(self):
        app = create_app(_settings(gpu_max_body_bytes=64))
        c = TestClient(app)
        big = {"wallet": _wallet(BORROWER_A_KEY), "chainId": CHAIN, "borrowerHint": "x" * 60}
        r = c.post("/gpu/auth/challenge", content=json.dumps(big), headers={"content-type": "application/json"})
        assert r.status_code == 413
        r2 = c.get("/gpu/me")
        assert r2.headers["X-Content-Type-Options"] == "nosniff" and r2.headers["Cache-Control"] == "no-store"


# ----------------------------------------------------------------------------- object-level permissions


class TestPermissions:
    @pytest.fixture
    def world(self, client, rt):
        a, b = _wallet(BORROWER_A_KEY), _wallet(BORROWER_B_KEY)
        rt.ownership.link_wallet(a, "brw_A")
        rt.ownership.link_wallet(b, "brw_B")
        rt.known_borrowers.update({"brw_A", "brw_B"})
        rt.ownership.set_account("0xacc_a", "brw_A")
        rt.ownership.set_account("0xacc_b", "brw_B")
        rt.ownership.set_facility("fac_A", "brw_A")
        rt.ownership.set_facility("fac_B", "brw_B")
        rt.roles.grant(_wallet(UNDERWRITER_KEY), "underwriter")
        rt.roles.grant(_wallet(TREASURY_KEY), "treasury")
        return {
            "A": login(client, BORROWER_A_KEY)["body"]["token"],
            "B": login(client, BORROWER_B_KEY)["body"]["token"],
            "UW": login(client, UNDERWRITER_KEY)["body"]["token"],
            "TR": login(client, TREASURY_KEY)["body"]["token"],
        }

    def test_idor_across_borrower_account_facility_is_uniform_404(self, client, world):
        for path in ("/gpu/borrowers/brw_B", "/gpu/accounts/0xacc_b", "/gpu/facilities/fac_B"):
            other = client.get(path, headers=bearer(world["A"]))
            missing = client.get(path.replace("_B", "_nope").replace("_b", "_nope"), headers=bearer(world["A"]))
            assert other.status_code == 404 and missing.status_code == 404
            assert other.json() == missing.json()  # no existence leak
        for path in ("/gpu/borrowers/brw_A", "/gpu/accounts/0xacc_a", "/gpu/facilities/fac_A"):
            assert client.get(path, headers=bearer(world["A"])).status_code == 200
            assert client.get(path, headers=bearer(world["UW"])).status_code == 200  # staff read

    def test_borrower_cannot_mutate_via_other_borrowers_connection_path(self, client, world):
        body = {"providerId": "mockdepin-testonly", "externalAccountId": "acct-B", "credentialRef": "env://PROVIDER_TOKEN"}
        assert client.post("/gpu/borrowers/brw_B/connections", json=body, headers=bearer(world["A"])).status_code == 404
        assert client.post("/gpu/borrowers/brw_A/connections", json=body, headers=bearer(world["A"])).status_code == 201

    def test_staff_mutations_require_separate_roles(self, client, world):
        hdr = bearer(world["A"])
        assert client.post("/gpu/facilities/fac_A/underwrite", headers=hdr).status_code == 403
        assert client.post("/gpu/facilities/fac_A/fund", headers=hdr).status_code == 403
        assert client.post("/gpu/control-agreements/ca_1/revoke", headers=hdr).status_code == 403
        assert client.patch("/gpu/recoveries/case_1", headers=hdr).status_code == 403
        assert client.post("/gpu/facilities/fac_A/underwrite", headers=bearer(world["UW"])).status_code == 200
        assert client.post("/gpu/facilities/fac_A/fund", headers=bearer(world["UW"])).status_code == 403  # not treasury
        assert client.post("/gpu/facilities/fac_A/fund", headers=bearer(world["TR"])).status_code == 200
        assert client.post("/gpu/facilities/fac_A/underwrite", headers=bearer(world["TR"])).status_code == 403

    def test_exclusive_roles_cannot_be_combined(self, rt):
        w = _wallet(UNDERWRITER_KEY)
        rt.roles.grant(w, "underwriter")
        with pytest.raises(ValueError):
            rt.roles.grant(w, "treasury")

    def test_unauthenticated_requests_rejected(self, client):
        assert client.get("/gpu/facilities/fac_A").status_code == 401
        assert client.get("/gpu/facilities/fac_A", headers={"Authorization": "Basic abc"}).status_code == 401
        assert client.get("/gpu/facilities/fac_A", headers=bearer("garbage.token")).status_code == 401


# ----------------------------------------------------------------------------- credentials / redaction


class TestSecrets:
    def test_secret_refs_only_and_env_store_resolves_server_side(self, monkeypatch):
        assert is_secret_ref("env://PROVIDER_TOKEN") and is_secret_ref("vault://gpu/aethir/token")
        assert not is_secret_ref(PROVIDER_SECRET) and not is_secret_ref("http://x") and not is_secret_ref("env://../x")
        store = EnvSecretStore({"PROVIDER_TOKEN": PROVIDER_SECRET})
        assert store.resolve("env://PROVIDER_TOKEN") == PROVIDER_SECRET
        assert store.resolve("env://MISSING") is None and store.resolve("vault://x") is None

    def test_raw_credential_value_rejected_and_never_echoed(self, client, rt):
        rt.ownership.link_wallet(_wallet(BORROWER_A_KEY), "brw_A")
        rt.known_borrowers.add("brw_A")
        tok = login(client, BORROWER_A_KEY)["body"]["token"]
        r = client.post(
            "/gpu/borrowers/brw_A/connections",
            json={"providerId": "mockdepin-testonly", "externalAccountId": "acct-A", "credentialRef": PROVIDER_SECRET},
            headers=bearer(tok),
        )
        assert r.status_code == 422 and PROVIDER_SECRET not in r.text
        ok = client.post(
            "/gpu/borrowers/brw_A/connections",
            json={"providerId": "mockdepin-testonly", "externalAccountId": "acct-A", "credentialRef": "env://PROVIDER_TOKEN"},
            headers=bearer(tok),
        )
        assert ok.status_code == 201 and ok.json()["credentialRef"] == "env://PROVIDER_TOKEN"

    def test_session_secret_and_tokens_never_appear_in_responses_or_logs(self, client, rt, caplog):
        tok = login(client, BORROWER_A_KEY)["body"]["token"]
        rt.redactor.register(PROVIDER_SECRET)
        logger = logging.getLogger("hashcredit_api.test")
        with caplog.at_level(logging.INFO):
            logger.info("session %s secret %s provider %s bearer %s", tok, SECRET, PROVIDER_SECRET, f"Bearer {tok}")
            logger.info("key 0x%s", "ab" * 32)
        text = "\n".join(rec.getMessage() for rec in caplog.records)
        assert SECRET not in text and PROVIDER_SECRET not in text and tok not in text
        assert "ab" * 32 not in text and "[REDACTED]" in text
        for path in ("/gpu/me",):
            body = client.get(path, headers=bearer(tok)).text
            assert SECRET not in body and PROVIDER_SECRET not in body

    def test_redactor_masks_common_token_shapes(self):
        r = Redactor()
        out = r.redact("Authorization: Bearer abcdefghijklmnopqrstuvwxyz0123 jwt eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abcdefghijk key sk_live_ABCDEFGHIJKLMNOPQRST")
        assert "abcdefghijklmnopqrstuvwxyz0123" not in out and "eyJhbGci" not in out and "sk_live" not in out


# ----------------------------------------------------------------------------- R2 proof-query guard


class TestProofQueryGuard:
    @pytest.fixture
    def keeper(self, client, rt):
        rt.roles.grant(_wallet(KEEPER_KEY), "keeper")
        return bearer(login(client, KEEPER_KEY)["body"]["token"])

    def _q(self, **over):
        q = {"manifestId": "cc3-testnet.sepolia.v1", "providerId": "mockdepin-testonly", "emitter": ESCROW, "txHash": TX}
        q.update(over)
        return q

    def test_manifest_bound_query_plan_never_reports_verified(self, client, keeper):
        r = client.post("/gpu/proofs/query", json=self._q(), headers=keeper)
        assert r.status_code == 200, r.text
        plan = r.json()
        assert plan["nativeStatus"] == "NOT_REQUESTED"
        assert plan["sourceChainId"] == 11155111 and plan["chainKey"] == 1
        assert plan["manifestHash"].startswith("sha256:")
        assert set(plan["proofHosts"]) == {"proof-gen-api.cc3-testnet.creditcoin.network", "prover.cc3-testnet.creditcoin.network"}

    @pytest.mark.parametrize("field", ["rpcUrl", "verifier", "mock", "trusted", "bypass", "markVerified", "nativeStatus", "precompile", "decoder"])
    def test_forbidden_fields_rejected_on_body_and_query_string(self, client, keeper, field):
        r = client.post("/gpu/proofs/query", json=self._q(**{field: "x"}), headers=keeper)
        assert r.status_code == 422, field
        g = client.get("/gpu/proofs/query", params=self._q(**{field: "x"}), headers=keeper)
        assert g.status_code == 422 and field in g.json()["detail"]["message"]

    def test_unknown_manifest_unregistered_emitter_unadmitted_provider(self, client, keeper):
        assert client.post("/gpu/proofs/query", json=self._q(manifestId="evil.v9"), headers=keeper).status_code == 422
        r = client.post("/gpu/proofs/query", json=self._q(emitter="0x" + "e2" * 20), headers=keeper)
        assert r.status_code == 422 and r.json()["detail"]["code"] == "UNSUPPORTED_SOURCE"
        r2 = client.post("/gpu/proofs/query", json=self._q(providerId="aethir"), headers=keeper)
        assert r2.status_code == 422 and r2.json()["detail"]["code"] == "UNSUPPORTED_SOURCE"
        assert client.post("/gpu/proofs/query", json=self._q(txHash="0x1234"), headers=keeper).status_code == 422

    def test_mock_manifest_rejected_by_default_and_always_on_production(self, client, keeper):
        r = client.post("/gpu/proofs/query", json=self._q(manifestId="local-mock.anvil.v1"), headers=keeper)
        assert r.status_code == 422 and r.json()["detail"]["code"] == "PROFILE_MISMATCH"
        with pytest.raises(ValueError):
            Settings(api_profile="production", chain_id=CHAIN, GPU_ALLOW_MOCK_MANIFESTS=True)

    def test_production_profile_refuses_non_production_manifest(self):
        app = create_app(_settings(api_profile="production", chain_id=102030))
        assert app.state.settings.api_profile == "production"
        c = TestClient(app)
        rt = app.state.gpu
        rt.roles.grant(_wallet(KEEPER_KEY), "keeper")
        hdr = bearer(login(c, KEEPER_KEY, chain_id=102030)["body"]["token"])
        r = c.post("/gpu/proofs/query", json=self._q(), headers=hdr)
        assert r.status_code == 422 and r.json()["detail"]["code"] == "PROFILE_MISMATCH"

    def test_borrower_cannot_plan_proof_queries(self, client, rt):
        tok = login(client, BORROWER_A_KEY)["body"]["token"]
        assert client.post("/gpu/proofs/query", json=self._q(), headers=bearer(tok)).status_code == 403

    def test_no_mark_verified_mutation_exists(self, client, keeper, app):
        paths = {getattr(r, "path", "") for r in app.routes}
        assert not any("verified" in p.lower() or "mark" in p.lower() for p in paths)
        for p in ("/gpu/proofs/mark-verified", "/gpu/proofs/query/verified", "/gpu/evidence/mark-verified"):
            for m in ("post", "patch", "put"):
                assert getattr(client, m)(p, json={}, headers=keeper).status_code in (404, 405)

    def test_outbound_allowlist_blocks_ssrf(self):
        hosts = frozenset({"proof-gen-api.cc3-testnet.creditcoin.network"})
        assert is_allowed_outbound("https://proof-gen-api.cc3-testnet.creditcoin.network/api/v1/proof-by-tx", hosts)
        for bad in (
            "http://proof-gen-api.cc3-testnet.creditcoin.network/x",  # scheme downgrade
            "https://evil.example/",
            "https://127.0.0.1/",
            "https://10.0.0.5/",
            "https://169.254.169.254/latest/meta-data",
            "https://[::1]/",
            "https://localhost/",
            "file:///etc/passwd",
            "https://user:pw@proof-gen-api.cc3-testnet.creditcoin.network/",
            "https://proof-gen-api.cc3-testnet.creditcoin.network.evil.example/",
            "",
        ):
            assert not is_allowed_outbound(bad, hosts), bad
        # http only when explicitly allowed (LOCAL_MOCK manifests) and still never to private literals
        assert is_allowed_outbound("http://mock-prover.internal.example/", {"mock-prover.internal.example"}, allow_http=True)
        assert not is_allowed_outbound("http://127.0.0.1:3999/", {"127.0.0.1"}, allow_http=True)


# ----------------------------------------------------------------------------- profile invariants (GPU-001 re-asserted)


class TestProfileInvariants:
    def test_production_api_holds_no_signer_and_no_wildcard_cors(self):
        s = Settings(api_profile="production", chain_id=CHAIN)
        assert s.demo_admin_private_key is None and s.admin_private_key is None
        assert not hasattr(s, "owner_private_key") and not hasattr(s, "gpu_signer_key")
        with pytest.raises(ValueError):
            Settings(api_profile="production", allowed_origins=["*"])
        with pytest.raises(ValueError):
            Settings(api_profile="production", DEMO_ADMIN_PRIVATE_KEY="0x" + "11" * 32)

    def test_gpu_runtime_has_no_key_material(self, app):
        rt = app.state.gpu
        assert not any("key" in name.lower() and "private" in name.lower() for name in vars(rt))
        assert "sign" not in {n for n in dir(rt) if not n.startswith("_")}
