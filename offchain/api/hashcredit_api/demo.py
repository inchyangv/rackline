"""
Testnet demo admin path (GPU-001).

This module is the ONLY place the API signs a transaction, and it is mounted only when
`API_PROFILE=testnet_demo`. The production app never imports a key and has no
`/claim/register-and-grant` route (404).

Guards, in order, before any transaction is signed:
  1. request shape + BTC address decodes
  2. borrower authorization: an EVM signature by the borrower over a demo-specific message that
     binds borrower, BTC address, chain id, manager address and an expiry (auxiliary wallet-auth
     signature; it never creates evidence or credit by itself)
  3. the BTC address is already linked on-chain for that borrower (BtcSpvVerifier.borrowerPubkeyHash)
  4. RPC chain id equals the configured demo chain id and is allowlisted (never a mainnet)
  5. the manager's stablecoin is a TEST_ONLY allowlisted token (external stablecoin → refuse)
  6. grant amount <= DEMO_GRANT_CAP
"""

import time
from typing import Any, Awaitable, Callable

import structlog
from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi import APIRouter, HTTPException, Request
from web3 import Web3

from .address import decode_btc_address
from .config import MAINNET_CHAIN_IDS, Settings
from .evm import EVMClient
from .models import (
    DemoAuthMessageRequest,
    DemoAuthMessageResponse,
    RegisterAndGrantRequest,
    RegisterAndGrantResponse,
)

logger = structlog.get_logger()

DEMO_GRANT_AMOUNT = 1_000_000_000  # 1,000 mUSDT (6 decimals)

# Minimal ABI fragments for the two admin calls.
MANAGER_ADMIN_ABI = [
    {
        "inputs": [
            {"name": "borrower", "type": "address"},
            {"name": "btcPayoutKeyHash", "type": "bytes32"},
        ],
        "name": "registerBorrower",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [
            {"name": "borrower", "type": "address"},
            {"name": "creditLimitAmount", "type": "uint128"},
        ],
        "name": "grantTestnetCredit",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
]


def build_demo_auth_message(
    *, borrower: str, btc_address: str, chain_id: int, manager: str, expires_at: int
) -> str:
    """Deterministic message the borrower signs to authorize a demo registration for itself."""
    return (
        "Rackline testnet demo registration\n"
        f"borrower: {borrower}\n"
        f"btc_address: {btc_address}\n"
        f"chain_id: {chain_id}\n"
        f"manager: {manager}\n"
        f"expires_at: {expires_at}\n"
        "TEST_ONLY: grants demo credit on a testnet; no real funds."
    )


class DemoAdminClient:
    """
    Holds the demo-only signer and performs the guarded register+grant.

    `send_admin_txs` is injectable so tests can prove the guards run before any signing.
    """

    def __init__(
        self,
        settings: Settings,
        evm: EVMClient,
        send_admin_txs: Callable[..., Awaitable[dict[str, str]]] | None = None,
    ):
        if not settings.is_demo:
            raise RuntimeError("DemoAdminClient can only be constructed under API_PROFILE=testnet_demo")
        pk = settings.demo_admin_private_key
        if not pk:
            raise RuntimeError("DEMO_ADMIN_PRIVATE_KEY not configured")
        pk = pk.strip()
        if not pk.startswith("0x"):
            pk = "0x" + pk
        self.account = Account.from_key(pk)
        self.settings = settings
        self.evm = evm
        self._send_admin_txs = send_admin_txs or self._send_admin_txs_onchain
        self.sign_calls = 0

    async def register_and_grant(
        self, *, borrower: str, btc_payout_key_hash: bytes, credit_amount: int = DEMO_GRANT_AMOUNT
    ) -> dict[str, str]:
        s = self.settings
        # 4. chain binding: configured id must be allowlisted, must not be a mainnet, and the RPC must agree
        if s.chain_id in MAINNET_CHAIN_IDS or s.chain_id not in s.demo_allowed_chain_ids:
            raise PermissionError(f"chain {s.chain_id} is not allowed for demo admin transactions")
        rpc_chain = await self.evm.get_chain_id()
        if rpc_chain != s.chain_id:
            raise PermissionError(f"RPC chain id {rpc_chain} != configured {s.chain_id}; refusing")
        # 5. asset binding: the manager must lend a TEST_ONLY stablecoin from the allowlist
        allow = {a.lower() for a in s.demo_allowed_stablecoins}
        if not allow:
            raise PermissionError("no TEST_ONLY stablecoin allowlisted (DEMO_ALLOWED_STABLECOINS)")
        stablecoin = (await self.evm.read_manager_stablecoin()).lower()
        if stablecoin not in allow:
            raise PermissionError(f"manager stablecoin {stablecoin} is not an allowlisted TEST_ONLY token")
        # 6. cap
        if credit_amount <= 0 or credit_amount > s.demo_grant_cap:
            raise PermissionError(f"credit amount {credit_amount} exceeds DEMO_GRANT_CAP {s.demo_grant_cap}")
        self.sign_calls += 1
        return await self._send_admin_txs(
            borrower=borrower, btc_payout_key_hash=btc_payout_key_hash, credit_amount=credit_amount
        )

    async def _send_admin_txs_onchain(
        self, *, borrower: str, btc_payout_key_hash: bytes, credit_amount: int
    ) -> dict[str, str]:
        w3 = self.evm.w3
        if not self.evm.manager_address:
            raise RuntimeError("HASH_CREDIT_MANAGER address not configured")
        manager_addr = w3.to_checksum_address(self.evm.manager_address)
        borrower_addr = w3.to_checksum_address(borrower)
        contract = w3.eth.contract(address=manager_addr, abi=MANAGER_ADMIN_ABI)

        nonce = await w3.eth.get_transaction_count(self.account.address)
        register_tx = await contract.functions.registerBorrower(borrower_addr, btc_payout_key_hash).build_transaction(
            {"from": self.account.address, "nonce": nonce, "chainId": self.settings.chain_id, "gas": 200_000}
        )
        signed_register = self.account.sign_transaction(register_tx)
        register_hash = await w3.eth.send_raw_transaction(signed_register.raw_transaction)
        register_receipt = await w3.eth.wait_for_transaction_receipt(register_hash, timeout=60)
        if register_receipt["status"] != 1:
            raise RuntimeError(f"registerBorrower reverted (tx: {register_hash.hex()})")

        nonce2 = await w3.eth.get_transaction_count(self.account.address)
        grant_tx = await contract.functions.grantTestnetCredit(borrower_addr, credit_amount).build_transaction(
            {"from": self.account.address, "nonce": nonce2, "chainId": self.settings.chain_id, "gas": 200_000}
        )
        signed_grant = self.account.sign_transaction(grant_tx)
        grant_hash = await w3.eth.send_raw_transaction(signed_grant.raw_transaction)
        grant_receipt = await w3.eth.wait_for_transaction_receipt(grant_hash, timeout=60)
        if grant_receipt["status"] != 1:
            raise RuntimeError(f"grantTestnetCredit reverted (tx: {grant_hash.hex()})")

        return {"register_tx": register_hash.hex(), "grant_tx": grant_hash.hex()}


def _demo_admin(request: Request) -> DemoAdminClient:
    client: Any = getattr(request.app.state, "demo_admin", None)
    if client is None:
        raise HTTPException(status_code=503, detail="demo admin client not initialized")
    return client


def _settings(request: Request) -> Settings:
    return request.app.state.settings


demo_router = APIRouter(tags=["testnet-demo"])


@demo_router.post("/claim/demo-auth-message", response_model=DemoAuthMessageResponse)
async def demo_auth_message(body: DemoAuthMessageRequest, request: Request) -> DemoAuthMessageResponse:
    """Return the exact message a borrower must sign to authorize its own demo registration."""
    s = _settings(request)
    try:
        borrower = Web3.to_checksum_address(body.borrower.strip())
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid borrower EVM address")
    if decode_btc_address(body.btc_address.strip()) is None:
        raise HTTPException(status_code=400, detail="Invalid or unsupported Bitcoin address format")
    if not s.hash_credit_manager:
        raise HTTPException(status_code=503, detail="HASH_CREDIT_MANAGER not configured")
    expires_at = int(time.time()) + s.demo_auth_ttl_seconds
    message = build_demo_auth_message(
        borrower=borrower,
        btc_address=body.btc_address.strip(),
        chain_id=s.chain_id,
        manager=Web3.to_checksum_address(s.hash_credit_manager),
        expires_at=expires_at,
    )
    return DemoAuthMessageResponse(message=message, expires_at=expires_at)


@demo_router.post("/claim/register-and-grant", response_model=RegisterAndGrantResponse)
async def register_and_grant(body: RegisterAndGrantRequest, request: Request) -> RegisterAndGrantResponse:
    """
    TESTNET DEMO ONLY: register a borrower and grant capped demo credit after the guards pass.
    """
    s = _settings(request)
    admin = _demo_admin(request)

    # 1. shape
    try:
        borrower = Web3.to_checksum_address(body.borrower.strip())
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid borrower EVM address")
    btc_address = body.btc_address.strip()
    decoded = decode_btc_address(btc_address)
    if decoded is None:
        raise HTTPException(status_code=400, detail="Invalid or unsupported Bitcoin address format")
    pubkey_hash, _ = decoded
    if not s.hash_credit_manager:
        raise HTTPException(status_code=503, detail="HASH_CREDIT_MANAGER not configured")

    # 2. borrower authorization (auxiliary wallet-auth signature; anonymous or third-party callers fail here)
    now = int(time.time())
    if body.expires_at <= now:
        raise HTTPException(status_code=403, detail="Authorization expired")
    if body.expires_at > now + s.demo_auth_ttl_seconds:
        raise HTTPException(status_code=403, detail="Authorization expiry too far in the future")
    message = build_demo_auth_message(
        borrower=borrower,
        btc_address=btc_address,
        chain_id=s.chain_id,
        manager=Web3.to_checksum_address(s.hash_credit_manager),
        expires_at=body.expires_at,
    )
    try:
        recovered = Account.recover_message(encode_defunct(text=message), signature=body.evm_signature)
    except Exception:
        raise HTTPException(status_code=403, detail="Invalid authorization signature")
    if recovered.lower() != borrower.lower():
        raise HTTPException(status_code=403, detail="Authorization signature is not from the borrower")

    # 3. BTC address must already be linked on-chain for this borrower
    try:
        linked = await admin.evm.read_verifier_pubkey_hash(borrower)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Cannot read on-chain BTC link: {e}")
    if linked != pubkey_hash:
        raise HTTPException(status_code=409, detail="BTC address is not linked on-chain for this borrower")

    # 4-6 + signing inside the client
    try:
        result = await admin.register_and_grant(
            borrower=borrower, btc_payout_key_hash=Web3.keccak(text=btc_address)
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.error("demo register_and_grant failed", borrower=borrower, error=str(e))
        return RegisterAndGrantResponse(success=False, borrower=borrower, error=str(e))

    logger.info("demo borrower registered and credit granted", borrower=borrower, **result)
    return RegisterAndGrantResponse(
        success=True,
        borrower=borrower,
        register_tx=result["register_tx"],
        grant_tx=result["grant_tx"],
        credit_amount="1,000 mUSDT (TEST_ONLY)",
    )
