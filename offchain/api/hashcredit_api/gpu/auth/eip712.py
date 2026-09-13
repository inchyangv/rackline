"""
EIP-712 typed data for the API login challenge.

Deliberately a *different* domain from the on-chain `AuthorizationVerifier` (GPU-030):
  - name "Rackline API Login" / version "1", `chainId`, and a `salt` = keccak256(appDomain) instead of a
    `verifyingContract`, so a login signature can never be replayed into any contract whose domain separator
    includes its own address (WALLET_LINK on-chain requires a separate, explicit signature).
  - primary type `Login(address wallet,uint256 chainId,string appDomain,string purpose,bytes32 nonce,
    uint64 issuedAt,uint64 expiresAt,string borrowerHint)`.
"""

from __future__ import annotations

from dataclasses import dataclass

from eth_account import Account
from eth_account.messages import SignableMessage, encode_typed_data
from eth_utils import keccak, to_checksum_address

DOMAIN_NAME = "Rackline API Login"
DOMAIN_VERSION = "1"
PURPOSE = "API_LOGIN"

LOGIN_TYPES = {
    "EIP712Domain": [
        {"name": "name", "type": "string"},
        {"name": "version", "type": "string"},
        {"name": "chainId", "type": "uint256"},
        {"name": "salt", "type": "bytes32"},
    ],
    "Login": [
        {"name": "wallet", "type": "address"},
        {"name": "chainId", "type": "uint256"},
        {"name": "appDomain", "type": "string"},
        {"name": "purpose", "type": "string"},
        {"name": "nonce", "type": "bytes32"},
        {"name": "issuedAt", "type": "uint64"},
        {"name": "expiresAt", "type": "uint64"},
        {"name": "borrowerHint", "type": "string"},
    ],
}


def domain_salt(app_domain: str) -> bytes:
    return keccak(text=app_domain)


@dataclass(frozen=True)
class LoginMessage:
    wallet: str
    chain_id: int
    app_domain: str
    nonce: bytes
    issued_at: int
    expires_at: int
    borrower_hint: str = ""

    def typed_data(self) -> dict:
        return {
            "types": LOGIN_TYPES,
            "primaryType": "Login",
            "domain": {
                "name": DOMAIN_NAME,
                "version": DOMAIN_VERSION,
                "chainId": self.chain_id,
                "salt": domain_salt(self.app_domain),
            },
            "message": {
                "wallet": to_checksum_address(self.wallet),
                "chainId": self.chain_id,
                "appDomain": self.app_domain,
                "purpose": PURPOSE,
                "nonce": self.nonce,
                "issuedAt": self.issued_at,
                "expiresAt": self.expires_at,
                "borrowerHint": self.borrower_hint,
            },
        }

    def signable(self) -> SignableMessage:
        return encode_typed_data(full_message=self.typed_data())

    def digest(self) -> bytes:
        s = self.signable()
        return keccak(b"\x19" + s.version + s.header + s.body)


def recover_eoa(message: LoginMessage, signature: bytes) -> str | None:
    """Address that produced `signature` over the typed data, or None if the signature is malformed."""
    if len(signature) != 65:
        return None
    try:
        return to_checksum_address(Account.recover_message(message.signable(), signature=signature))
    except Exception:
        return None
