"""
GPU-001: public admin register/grant path removal and demo isolation.

Production profile (default): no register-and-grant route, no key of any kind can be loaded.
testnet_demo profile: guarded, capped, chain/asset-bound path with a demo-only key; every guard
must reject *before* anything is signed.
"""

import time

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi.testclient import TestClient
from pydantic import ValidationError
from web3 import Web3

from hashcredit_api import evm as evm_module
from hashcredit_api.address import decode_btc_address
from hashcredit_api.config import Settings
from hashcredit_api.demo import DEMO_GRANT_AMOUNT, DemoAdminClient, build_demo_auth_message
from hashcredit_api.evm import EVMClient
from hashcredit_api.main import create_app

# Deterministic test keys (never used anywhere real).
DEMO_ADMIN_KEY = "0x" + "11" * 32
BORROWER = Account.from_key("0x" + "22" * 32)
STRANGER = Account.from_key("0x" + "33" * 32)

MANAGER = "0x1000000000000000000000000000000000000001"
VERIFIER = "0x2000000000000000000000000000000000000002"
MOCK_USDT = "0x3000000000000000000000000000000000000003"
EXTERNAL_USDT = "0x4000000000000000000000000000000000000004"

BTC_ADDRESS = "tb1qw508d6qejxtdg4y5r3zarvary0c5xw7kxpjzsx"  # P2WPKH testnet
BTC_PUBKEY_HASH = decode_btc_address(BTC_ADDRESS)[0]  # type: ignore[index]


def production_settings(**overrides) -> Settings:
    return Settings(evm_rpc_url="http://localhost:8545", chain_id=102031, **overrides)


def demo_settings(**overrides) -> Settings:
    base = dict(
        API_PROFILE="testnet_demo",
        DEMO_ADMIN_PRIVATE_KEY=DEMO_ADMIN_KEY,
        evm_rpc_url="http://localhost:8545",
        chain_id=31337,
        DEMO_ALLOWED_CHAIN_IDS=[31337, 102031],
        DEMO_ALLOWED_STABLECOINS=[MOCK_USDT],
        hash_credit_manager=MANAGER,
        btc_spv_verifier=VERIFIER,
    )
    base.update(overrides)
    return Settings(**base)


class FakeEVM(EVMClient):
    """Read-only client with canned answers; never touches an RPC."""

    def __init__(self, settings: Settings, *, chain_id: int, stablecoin: str, linked: bytes | None):
        super().__init__(settings)
        self._chain_id = chain_id
        self._stablecoin = stablecoin
        self._linked = linked if linked is not None else b"\x00" * 20

    async def check_connectivity(self) -> bool:
        return True

    async def get_chain_id(self) -> int:
        return self._chain_id

    async def read_manager_stablecoin(self) -> str:
        return self._stablecoin

    async def read_verifier_pubkey_hash(self, borrower: str) -> bytes:
        return self._linked


class SendRecorder:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def __call__(self, **kwargs) -> dict[str, str]:
        self.calls.append(kwargs)
        return {"register_tx": "0xaa", "grant_tx": "0xbb"}


def demo_client(settings: Settings, *, chain_id=31337, stablecoin=MOCK_USDT, linked=BTC_PUBKEY_HASH):
    """(TestClient, DemoAdminClient, SendRecorder) for a demo app without running the lifespan."""
    app = create_app(settings)
    fake = FakeEVM(settings, chain_id=chain_id, stablecoin=stablecoin, linked=linked)
    recorder = SendRecorder()
    admin = DemoAdminClient(settings, fake, send_admin_txs=recorder)
    app.state.demo_admin = admin
    return TestClient(app), admin, recorder


def signed_body(settings: Settings, signer=BORROWER, *, borrower=None, btc_address=BTC_ADDRESS, expires_in=120, chain_id=None, manager=None):
    borrower = borrower or BORROWER.address
    expires_at = int(time.time()) + expires_in
    message = build_demo_auth_message(
        borrower=borrower,
        btc_address=btc_address,
        chain_id=chain_id if chain_id is not None else settings.chain_id,
        manager=manager or Web3.to_checksum_address(settings.hash_credit_manager),
        expires_at=expires_at,
    )
    sig = signer.sign_message(encode_defunct(text=message)).signature.hex()
    return {"borrower": borrower, "btc_address": btc_address, "evm_signature": sig, "expires_at": expires_at}


# ---------------------------------------------------------------------------
# Production profile
# ---------------------------------------------------------------------------


class TestProductionProfile:
    def test_default_profile_is_production(self):
        assert production_settings().api_profile == "production"
        assert production_settings().is_demo is False

    def test_register_and_grant_route_absent(self):
        client = TestClient(create_app(production_settings()))
        r = client.post(
            "/claim/register-and-grant",
            json={"borrower": BORROWER.address, "btc_address": BTC_ADDRESS, "evm_signature": "0x", "expires_at": 0},
        )
        assert r.status_code == 404
        assert client.post("/claim/demo-auth-message", json={"borrower": BORROWER.address, "btc_address": BTC_ADDRESS}).status_code == 404
        # Legacy two-field body is rejected the same way: the route does not exist at all.
        assert client.post("/claim/register-and-grant", json={"borrower": BORROWER.address, "btc_address": BTC_ADDRESS}).status_code == 404

    def test_production_rejects_any_admin_key(self):
        with pytest.raises(ValidationError, match="ADMIN_PRIVATE_KEY is no longer accepted"):
            production_settings(ADMIN_PRIVATE_KEY=DEMO_ADMIN_KEY)
        with pytest.raises(ValidationError, match="must not be set on a production API process"):
            production_settings(DEMO_ADMIN_PRIVATE_KEY=DEMO_ADMIN_KEY)

    def test_read_only_evm_client_has_no_signing_surface(self):
        client = EVMClient(production_settings())
        assert client.has_admin_key is False
        assert not hasattr(client, "account")
        assert not hasattr(EVMClient, "register_and_grant")
        # The read-only module must not import an account/signing facility at all.
        assert not hasattr(evm_module, "Account")
        assert "sign" not in " ".join(dir(evm_module)).lower()

    def test_health_reports_production_profile(self):
        r = TestClient(create_app(production_settings())).get("/health")
        assert r.status_code == 200
        assert r.json()["api_profile"] == "production"

    def test_demo_client_cannot_be_built_for_production(self):
        s = production_settings()
        with pytest.raises(RuntimeError, match="only be constructed under API_PROFILE=testnet_demo"):
            DemoAdminClient(s, EVMClient(s))


# ---------------------------------------------------------------------------
# Demo profile configuration guards
# ---------------------------------------------------------------------------


class TestDemoConfigGuards:
    def test_demo_refuses_mainnet_chain_ids(self):
        with pytest.raises(ValidationError, match="is a mainnet"):
            demo_settings(chain_id=102030, DEMO_ALLOWED_CHAIN_IDS=[31337])
        with pytest.raises(ValidationError, match="contains mainnet chain ids"):
            demo_settings(DEMO_ALLOWED_CHAIN_IDS=[31337, 102030])
        with pytest.raises(ValidationError, match="contains mainnet chain ids"):
            demo_settings(DEMO_ALLOWED_CHAIN_IDS=[1])

    def test_demo_refuses_chain_outside_allowlist(self):
        with pytest.raises(ValidationError, match="not in DEMO_ALLOWED_CHAIN_IDS"):
            demo_settings(chain_id=99999)

    def test_demo_refuses_legacy_admin_key_name(self):
        with pytest.raises(ValidationError, match="ADMIN_PRIVATE_KEY is no longer accepted"):
            demo_settings(ADMIN_PRIVATE_KEY=DEMO_ADMIN_KEY)

    def test_demo_requires_its_own_key(self):
        s = demo_settings(DEMO_ADMIN_PRIVATE_KEY=None)
        with pytest.raises(RuntimeError, match="DEMO_ADMIN_PRIVATE_KEY not configured"):
            DemoAdminClient(s, EVMClient(s))

    def test_demo_cap_must_be_positive(self):
        with pytest.raises(ValidationError, match="DEMO_GRANT_CAP must be positive"):
            demo_settings(DEMO_GRANT_CAP=0)


# ---------------------------------------------------------------------------
# Demo profile request guards (nothing is signed unless every guard passes)
# ---------------------------------------------------------------------------


class TestDemoRegisterAndGrant:
    def test_happy_path_signs_once_with_capped_amount(self):
        s = demo_settings()
        client, admin, rec = demo_client(s)
        r = client.post("/claim/register-and-grant", json=signed_body(s))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["success"] is True
        assert body["register_tx"] == "0xaa" and body["grant_tx"] == "0xbb"
        assert admin.sign_calls == 1
        assert len(rec.calls) == 1
        assert rec.calls[0]["credit_amount"] == DEMO_GRANT_AMOUNT <= s.demo_grant_cap
        assert rec.calls[0]["borrower"] == BORROWER.address
        assert rec.calls[0]["btc_payout_key_hash"] == Web3.keccak(text=BTC_ADDRESS)

    def test_auth_message_endpoint_matches_builder(self):
        s = demo_settings()
        client, _, _ = demo_client(s)
        r = client.post("/claim/demo-auth-message", json={"borrower": BORROWER.address, "btc_address": BTC_ADDRESS})
        assert r.status_code == 200
        data = r.json()
        assert data["message"] == build_demo_auth_message(
            borrower=BORROWER.address, btc_address=BTC_ADDRESS, chain_id=31337, manager=Web3.to_checksum_address(MANAGER), expires_at=data["expires_at"]
        )
        assert "TEST_ONLY" in data["message"]

    def test_anonymous_request_rejected_before_signing(self):
        s = demo_settings()
        client, admin, rec = demo_client(s)
        # Missing signature fields → schema rejection.
        assert client.post("/claim/register-and-grant", json={"borrower": BORROWER.address, "btc_address": BTC_ADDRESS}).status_code == 422
        # Garbage signature → 403.
        body = signed_body(s)
        body["evm_signature"] = "0xdeadbeef"
        assert client.post("/claim/register-and-grant", json=body).status_code == 403
        assert admin.sign_calls == 0 and rec.calls == []

    def test_third_party_cannot_register_another_borrower(self):
        s = demo_settings()
        client, admin, rec = demo_client(s)
        r = client.post("/claim/register-and-grant", json=signed_body(s, signer=STRANGER))
        assert r.status_code == 403
        assert "not from the borrower" in r.json()["detail"]
        assert admin.sign_calls == 0 and rec.calls == []

    def test_signature_bound_to_chain_and_manager(self):
        s = demo_settings()
        client, admin, rec = demo_client(s)
        assert client.post("/claim/register-and-grant", json=signed_body(s, chain_id=102031)).status_code == 403
        assert client.post("/claim/register-and-grant", json=signed_body(s, manager="0x9000000000000000000000000000000000000009")).status_code == 403
        assert admin.sign_calls == 0 and rec.calls == []

    def test_expired_or_overlong_authorization_rejected(self):
        s = demo_settings()
        client, admin, rec = demo_client(s)
        assert client.post("/claim/register-and-grant", json=signed_body(s, expires_in=-1)).status_code == 403
        assert client.post("/claim/register-and-grant", json=signed_body(s, expires_in=s.demo_auth_ttl_seconds + 600)).status_code == 403
        assert admin.sign_calls == 0 and rec.calls == []

    def test_fake_btc_address_rejected(self):
        s = demo_settings()
        # Valid format but not linked on-chain for this borrower.
        client, admin, rec = demo_client(s, linked=b"\x99" * 20)
        r = client.post("/claim/register-and-grant", json=signed_body(s))
        assert r.status_code == 409
        # Invalid format.
        client2, admin2, rec2 = demo_client(s)
        r2 = client2.post("/claim/register-and-grant", json=signed_body(s, btc_address="not-a-btc-address"))
        assert r2.status_code == 400
        assert admin.sign_calls == admin2.sign_calls == 0 and rec.calls == rec2.calls == []

    def test_rpc_chain_mismatch_rejected(self):
        s = demo_settings()
        client, admin, rec = demo_client(s, chain_id=102031)  # configured 31337, RPC says testnet
        r = client.post("/claim/register-and-grant", json=signed_body(s))
        assert r.status_code == 403
        assert "RPC chain id" in r.json()["detail"]
        assert admin.sign_calls == 0 and rec.calls == []

    def test_external_stablecoin_rejected(self):
        s = demo_settings()
        client, admin, rec = demo_client(s, stablecoin=EXTERNAL_USDT)
        r = client.post("/claim/register-and-grant", json=signed_body(s))
        assert r.status_code == 403
        assert "TEST_ONLY" in r.json()["detail"]
        assert admin.sign_calls == 0 and rec.calls == []

    def test_empty_stablecoin_allowlist_rejected(self):
        s = demo_settings(DEMO_ALLOWED_STABLECOINS=[])
        client, admin, rec = demo_client(s)
        r = client.post("/claim/register-and-grant", json=signed_body(s))
        assert r.status_code == 403
        assert admin.sign_calls == 0 and rec.calls == []

    @pytest.mark.asyncio
    async def test_cap_enforced_inside_client(self):
        s = demo_settings(DEMO_GRANT_CAP=500_000_000)
        rec = SendRecorder()
        admin = DemoAdminClient(s, FakeEVM(s, chain_id=31337, stablecoin=MOCK_USDT, linked=BTC_PUBKEY_HASH), send_admin_txs=rec)
        with pytest.raises(PermissionError, match="exceeds DEMO_GRANT_CAP"):
            await admin.register_and_grant(borrower=BORROWER.address, btc_payout_key_hash=b"\x00" * 32)
        with pytest.raises(PermissionError):
            await admin.register_and_grant(borrower=BORROWER.address, btc_payout_key_hash=b"\x00" * 32, credit_amount=0)
        assert rec.calls == [] and admin.sign_calls == 0
        ok = await admin.register_and_grant(borrower=BORROWER.address, btc_payout_key_hash=b"\x00" * 32, credit_amount=500_000_000)
        assert ok["register_tx"] == "0xaa" and admin.sign_calls == 1

    def test_health_reports_demo_profile(self):
        s = demo_settings()
        client, _, _ = demo_client(s)
        assert client.get("/health").json()["api_profile"] == "testnet_demo"
