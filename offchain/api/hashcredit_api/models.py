"""
Pydantic models for API requests and responses.
"""

from typing import Optional

from pydantic import BaseModel, Field


# ============================================================================
# Build Proof
# ============================================================================

class BuildProofRequest(BaseModel):
    """Request to build an SPV proof."""

    txid: str = Field(..., description="Bitcoin transaction ID (display format)")
    output_index: int = Field(..., ge=0, description="Output index (vout)")
    checkpoint_height: int = Field(..., gt=0, description="Checkpoint block height")
    target_height: int = Field(..., gt=0, description="Target block height (where tx is confirmed)")
    borrower: str = Field(..., description="Borrower EVM address (0x...)")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "txid": "abc123def456...",
                    "output_index": 0,
                    "checkpoint_height": 2500000,
                    "target_height": 2500006,
                    "borrower": "0x1234567890abcdef1234567890abcdef12345678"
                }
            ]
        }
    }


class BuildProofResponse(BaseModel):
    """Response containing the built SPV proof."""

    success: bool = Field(..., description="Whether proof was built successfully")
    proof_hex: Optional[str] = Field(None, description="ABI-encoded proof (0x...)")
    amount_sats: Optional[int] = Field(None, description="Output amount in satoshis")
    pubkey_hash: Optional[str] = Field(None, description="Extracted pubkey hash (0x...)")
    script_type: Optional[str] = Field(None, description="Script type (p2pkh/p2wpkh)")
    header_chain_length: Optional[int] = Field(None, description="Number of headers in chain")
    merkle_depth: Optional[int] = Field(None, description="Merkle proof depth")
    error: Optional[str] = Field(None, description="Error message if failed")


# ============================================================================
# Set Checkpoint
# ============================================================================

class SetCheckpointRequest(BaseModel):
    """Request to set a Bitcoin checkpoint."""

    height: int = Field(..., gt=0, description="Bitcoin block height to checkpoint")
    dry_run: bool = Field(False, description="If true, return data without sending tx")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "height": 2500000,
                    "dry_run": False
                }
            ]
        }
    }


class SetCheckpointResponse(BaseModel):
    """Response from setting a checkpoint."""

    success: bool = Field(..., description="Whether checkpoint was set successfully")
    height: int = Field(..., description="Checkpoint height")
    block_hash: Optional[str] = Field(None, description="Block hash (internal format)")
    timestamp: Optional[int] = Field(None, description="Block timestamp")
    chain_work: Optional[str] = Field(None, description="Cumulative chain work (hex)")
    bits: Optional[int] = Field(None, description="Difficulty target bits (compact format)")
    tx_hash: Optional[str] = Field(None, description="Transaction hash (if not dry run)")
    gas_used: Optional[int] = Field(None, description="Gas used (if not dry run)")
    dry_run: bool = Field(False, description="Whether this was a dry run")
    error: Optional[str] = Field(None, description="Error message if failed")


# ============================================================================
# Set Borrower Pubkey Hash
# ============================================================================

class SetBorrowerPubkeyHashRequest(BaseModel):
    """Request to register borrower's Bitcoin pubkey hash."""

    borrower: str = Field(..., description="Borrower EVM address (0x...)")
    btc_address: str = Field(..., description="Borrower's Bitcoin address (tb1q.../m.../n...)")
    dry_run: bool = Field(False, description="If true, return data without sending tx")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "borrower": "0x1234567890abcdef1234567890abcdef12345678",
                    "btc_address": "tb1qw508d6qejxtdg4y5r3zarvary0c5xw7kxpjzsx",
                    "dry_run": False
                }
            ]
        }
    }


class SetBorrowerPubkeyHashResponse(BaseModel):
    """Response from setting borrower pubkey hash."""

    success: bool = Field(..., description="Whether pubkey hash was set successfully")
    borrower: str = Field(..., description="Borrower EVM address")
    pubkey_hash: Optional[str] = Field(None, description="Extracted pubkey hash (0x...)")
    address_type: Optional[str] = Field(None, description="Bitcoin address type")
    tx_hash: Optional[str] = Field(None, description="Transaction hash (if not dry run)")
    gas_used: Optional[int] = Field(None, description="Gas used (if not dry run)")
    dry_run: bool = Field(False, description="Whether this was a dry run")
    error: Optional[str] = Field(None, description="Error message if failed")


# ============================================================================
# Submit Proof
# ============================================================================

class SubmitProofRequest(BaseModel):
    """Request to submit an SPV proof to the contract."""

    proof_hex: str = Field(..., description="ABI-encoded proof (0x...)")
    dry_run: bool = Field(False, description="If true, validate without sending tx")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "proof_hex": "0x000000...",
                    "dry_run": False
                }
            ]
        }
    }


class SubmitProofResponse(BaseModel):
    """Response from submitting a proof."""

    success: bool = Field(..., description="Whether proof was submitted successfully")
    tx_hash: Optional[str] = Field(None, description="Transaction hash")
    block_number: Optional[int] = Field(None, description="Block number")
    gas_used: Optional[int] = Field(None, description="Gas used")
    dry_run: bool = Field(False, description="Whether this was a dry run")
    error: Optional[str] = Field(None, description="Error message if failed")


# ============================================================================
# Register Borrower (Manager)
# ============================================================================

class RegisterBorrowerRequest(BaseModel):
    """Request to register borrower on HashCreditManager (owner-only)."""

    borrower: str = Field(..., description="Borrower EVM address (0x...)")
    btc_address: str = Field(..., description="Borrower BTC payout address (string)")
    dry_run: bool = Field(False, description="If true, return data without sending tx")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "borrower": "0x1234567890abcdef1234567890abcdef12345678",
                    "btc_address": "tb1q...",
                    "dry_run": False,
                }
            ]
        }
    }


class RegisterBorrowerResponse(BaseModel):
    """Response from registering borrower."""

    success: bool = Field(..., description="Whether borrower was registered successfully")
    borrower: str = Field(..., description="Borrower EVM address")
    btc_address: str = Field(..., description="BTC payout address (string)")
    btc_payout_key_hash: Optional[str] = Field(None, description="keccak256(btc_address) as bytes32 (0x...)")
    tx_hash: Optional[str] = Field(None, description="Transaction hash (if not dry run)")
    gas_used: Optional[int] = Field(None, description="Gas used (if not dry run)")
    dry_run: bool = Field(False, description="Whether this was a dry run")
    error: Optional[str] = Field(None, description="Error message if failed")


# ============================================================================
# Borrower Claim (mainnet-grade mapping)
# ============================================================================


class ClaimStartRequest(BaseModel):
    """Request to start a borrower claim."""

    borrower: str = Field(..., description="Borrower EVM address (0x...)")
    btc_address: str = Field(..., description="Borrower Bitcoin payout address (bc1q.../tb1q.../1.../m.../n...)")


class ClaimStartResponse(BaseModel):
    """Response containing claim token and message to sign."""

    success: bool = Field(..., description="Whether claim start succeeded")
    borrower: str = Field(..., description="Borrower EVM address")
    btc_address: str = Field(..., description="Borrower BTC address")
    claim_token: Optional[str] = Field(None, description="HMAC-signed claim token (submit to /claim/complete)")
    message: Optional[str] = Field(None, description="Message to sign (BTC + EVM)")
    expires_at: Optional[int] = Field(None, description="Unix timestamp when token expires")
    error: Optional[str] = Field(None, description="Error message if failed")


class ClaimCompleteRequest(BaseModel):
    """Request to complete a borrower claim and register on-chain mappings."""

    claim_token: str = Field(..., description="Claim token from /claim/start")
    evm_signature: str = Field(..., description="EVM signature over the provided message")
    btc_signature: str = Field(..., description="BTC signature (base64, BIP-137 style) over the provided message")
    dry_run: bool = Field(False, description="If true, verify only; do not send on-chain transactions")


class ClaimCompleteResponse(BaseModel):
    """Response from completing a borrower claim."""

    success: bool = Field(..., description="Whether claim completed successfully")
    borrower: Optional[str] = Field(None, description="Borrower EVM address")
    btc_address: Optional[str] = Field(None, description="Borrower BTC address")
    pubkey_hash: Optional[str] = Field(None, description="Extracted pubkey hash (0x...)")
    btc_payout_key_hash: Optional[str] = Field(None, description="keccak256(utf8(btc_address)) (0x...)")
    tx_set_pubkey_hash: Optional[str] = Field(None, description="Tx hash for setBorrowerPubkeyHash")
    tx_register_borrower: Optional[str] = Field(None, description="Tx hash for registerBorrower")
    dry_run: bool = Field(False, description="Whether this was a dry run")
    error: Optional[str] = Field(None, description="Error message if failed")


# ============================================================================
# Health Check
# ============================================================================

class HealthResponse(BaseModel):
    """Health check response."""

    status: str = Field(..., description="Service status")
    version: str = Field(..., description="API version")
    bitcoin_rpc: bool = Field(..., description="Bitcoin RPC connectivity")
    evm_rpc: bool = Field(..., description="EVM RPC connectivity")
    contracts: dict[str, Optional[str]] = Field(
        ...,
        description="Configured contract addresses"
    )
