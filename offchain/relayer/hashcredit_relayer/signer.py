"""
EIP-712 signature generation for payout claims.
"""

from dataclasses import dataclass
from typing import Any

from eth_account import Account
from eth_account.messages import encode_typed_data
import structlog

logger = structlog.get_logger()


@dataclass
class PayoutClaim:
    """Payout claim to be signed."""

    borrower: str  # Borrower EVM address
    txid: bytes  # Bitcoin txid (32 bytes)
    vout: int  # Output index
    amount_sats: int  # Amount in satoshis
    block_height: int  # Bitcoin block height
    block_timestamp: int  # Block timestamp
    deadline: int  # Signature deadline (unix timestamp)


def create_eip712_domain(chain_id: int, verifying_contract: str) -> dict[str, Any]:
    """Create EIP-712 domain separator data."""
    return {
        "name": "HashCredit",
        "version": "1",
        "chainId": chain_id,
        "verifyingContract": verifying_contract,
    }


def create_payout_claim_types() -> dict[str, list[dict[str, str]]]:
    """Create EIP-712 type definitions for PayoutClaim."""
    return {
        "PayoutClaim": [
            {"name": "borrower", "type": "address"},
            {"name": "txid", "type": "bytes32"},
            {"name": "vout", "type": "uint32"},
            {"name": "amountSats", "type": "uint64"},
            {"name": "blockHeight", "type": "uint32"},
            {"name": "blockTimestamp", "type": "uint32"},
            {"name": "deadline", "type": "uint256"},
        ]
    }


def sign_payout_claim(
    claim: PayoutClaim,
    private_key: str,
    chain_id: int,
    verifying_contract: str,
) -> bytes:
    """
    Sign a payout claim using EIP-712.

    Returns:
        65-byte signature (r || s || v)
    """
    # Prepare typed data
    domain = create_eip712_domain(chain_id, verifying_contract)
    types = create_payout_claim_types()

    # Ensure txid is properly formatted as bytes32
    txid_bytes = claim.txid if isinstance(claim.txid, bytes) else bytes.fromhex(
        claim.txid.replace("0x", "")
    )

    message = {
        "borrower": claim.borrower,
        "txid": txid_bytes,
        "vout": claim.vout,
        "amountSats": claim.amount_sats,
        "blockHeight": claim.block_height,
        "blockTimestamp": claim.block_timestamp,
        "deadline": claim.deadline,
    }

    full_message = {
        "types": {
            "EIP712Domain": [
                {"name": "name", "type": "string"},
                {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"},
                {"name": "verifyingContract", "type": "address"},
            ],
            **types,
        },
        "primaryType": "PayoutClaim",
        "domain": domain,
        "message": message,
    }

    # Sign
    account = Account.from_key(private_key)
    signed = account.sign_typed_data(full_message=full_message)

    logger.info(
        "signed_payout_claim",
        borrower=claim.borrower,
        txid=txid_bytes.hex(),
        vout=claim.vout,
        amount_sats=claim.amount_sats,
        signer=account.address,
    )

    return signed.signature


def txid_to_bytes32(txid_hex: str) -> bytes:
    """
    Convert Bitcoin txid hex to bytes32.

    Bitcoin txids are displayed in reverse byte order,
    so we need to reverse them for use on EVM.
    """
    # Remove 0x prefix if present
    txid_hex = txid_hex.replace("0x", "")

    # Bitcoin txids are displayed in reverse byte order
    # For on-chain use, we keep them as-is (little-endian as stored)
    return bytes.fromhex(txid_hex)
