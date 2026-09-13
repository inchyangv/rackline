"""POST /gpu/auth/challenge and /gpu/auth/verify (bearer sessions; auxiliary path only)."""

from __future__ import annotations

import time

from eth_utils import is_address, to_checksum_address
from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from ..errors import not_configured, unauthenticated, validation
from .challenge import Challenge, new_nonce
from .eip712 import DOMAIN_NAME, DOMAIN_VERSION, LOGIN_TYPES, PURPOSE, LoginMessage, domain_salt, recover_eoa
from .session import issue_session

router = APIRouter(prefix="/gpu/auth", tags=["gpu-auth"])


class ChallengeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    wallet: str
    chainId: int = Field(gt=0)
    borrowerHint: str = Field(default="", max_length=64)


class ChallengeResponse(BaseModel):
    nonce: str
    issuedAt: int
    expiresAt: int
    typedData: dict


class VerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    wallet: str
    chainId: int = Field(gt=0)
    nonce: str
    signature: str
    walletKind: str = Field(default="eoa", pattern="^(eoa|erc1271)$")


class VerifyResponse(BaseModel):
    token: str
    tokenType: str = "Bearer"
    expiresAt: int
    wallet: str
    borrowerId: str | None
    roles: list[str]


def _rt(request: Request):
    rt = getattr(request.app.state, "gpu", None)
    if rt is None or rt.session_secret is None:
        raise not_configured("session auth not configured (GPU_SESSION_SECRET)")
    return rt


def _hex_bytes(value: str, length: int, name: str) -> bytes:
    v = value[2:] if value.startswith("0x") else value
    try:
        raw = bytes.fromhex(v)
    except ValueError:
        raise validation(f"{name} must be hex")
    if len(raw) != length:
        raise validation(f"{name} must be {length} bytes")
    return raw


@router.post("/challenge", response_model=ChallengeResponse)
async def challenge(body: ChallengeRequest, request: Request) -> ChallengeResponse:
    rt = _rt(request)
    if not is_address(body.wallet):
        raise validation("wallet must be an EVM address")
    if body.chainId != rt.chain_id:
        raise validation(f"chainId {body.chainId} is not this API's chain {rt.chain_id}")
    wallet = to_checksum_address(body.wallet)
    now = int(time.time())
    nonce = new_nonce()
    ch = Challenge(
        nonce=nonce,
        wallet=wallet,
        chain_id=body.chainId,
        app_domain=rt.app_domain,
        borrower_hint=body.borrowerHint,
        issued_at=now,
        expires_at=now + rt.challenge_ttl_seconds,
    )
    rt.challenges.put(ch)
    msg = LoginMessage(wallet, ch.chain_id, ch.app_domain, nonce, ch.issued_at, ch.expires_at, ch.borrower_hint)
    td = msg.typed_data()
    td["domain"]["salt"] = "0x" + domain_salt(ch.app_domain).hex()
    td["message"]["nonce"] = "0x" + nonce.hex()
    return ChallengeResponse(nonce="0x" + nonce.hex(), issuedAt=ch.issued_at, expiresAt=ch.expires_at, typedData=td)


@router.post("/verify", response_model=VerifyResponse)
async def verify(body: VerifyRequest, request: Request) -> VerifyResponse:
    rt = _rt(request)
    if not is_address(body.wallet):
        raise validation("wallet must be an EVM address")
    wallet = to_checksum_address(body.wallet)
    nonce = _hex_bytes(body.nonce, 32, "nonce")
    signature = bytes.fromhex(body.signature[2:] if body.signature.startswith("0x") else body.signature)
    ch = rt.challenges.take(nonce)  # single use: a replay finds nothing
    if ch is None:
        raise unauthenticated("unknown or already used challenge")
    now = int(time.time())
    if ch.expires_at <= now:
        raise unauthenticated("challenge expired")
    if ch.wallet.lower() != wallet.lower() or ch.chain_id != body.chainId or ch.chain_id != rt.chain_id:
        raise unauthenticated("challenge binding mismatch")
    msg = LoginMessage(ch.wallet, ch.chain_id, ch.app_domain, ch.nonce, ch.issued_at, ch.expires_at, ch.borrower_hint)
    if body.walletKind == "eoa":
        recovered = recover_eoa(msg, signature)
        if recovered is None or recovered.lower() != wallet.lower():
            raise unauthenticated("signature does not match wallet")
    else:
        if not await rt.erc1271.is_valid_signature(wallet, msg.digest(), signature):
            raise unauthenticated("contract wallet rejected the signature")
    roles = sorted(rt.roles.roles_of(wallet))
    borrower_id = rt.ownership.borrower_of_wallet(wallet)
    if borrower_id is not None and "borrower" not in roles:
        roles.append("borrower")
    token, payload = issue_session(
        secret=rt.session_secret,
        payload_fields={
            "wallet": wallet,
            "chain_id": ch.chain_id,
            "borrower_id": borrower_id,
            "roles": tuple(roles),
            "role_epochs": {r: rt.roles.epoch(r) for r in roles},
        },
        ttl_seconds=rt.session_ttl_seconds,
    )
    rt.redactor.register(token)
    return VerifyResponse(
        token=token, expiresAt=payload.expires_at, wallet=wallet, borrowerId=borrower_id, roles=roles
    )


def login_domain_description() -> dict:
    """For docs/tests: the API login domain differs from the on-chain AuthorizationVerifier domain."""
    return {"name": DOMAIN_NAME, "version": DOMAIN_VERSION, "purpose": PURPOSE, "types": LOGIN_TYPES}
