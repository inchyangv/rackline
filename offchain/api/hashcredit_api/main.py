"""
HashCredit API - HTTP bridge for Frontend to Bitcoin Core/Prover.

Provides REST endpoints for:
- Building SPV proofs (POST /spv/build-proof)
- Building checkpoint payloads (POST /checkpoint/build)
- Verifying borrower claim signatures (POST /claim/complete, verify-only)
- Querying BTC address history (GET /btc/address-history)
- Health checks (GET /health)
"""

import uvicorn
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import httpx
import structlog
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .address import decode_btc_address
from .btc_signmessage import verify_bip137_signature
from .bitcoin import BitcoinRPC, BitcoinRPCConfig, sha256d
from .btc_indexer import BtcIndexer, BtcIndexerConfig
from .claim import build_claim_message, issue_claim_token, verify_claim_token
from .proof import BlockHeader
from .config import Settings, get_settings
from .evm import EVMClient
from .models import (
    BtcAddressHistoryResponse,
    BuildProofRequest,
    BuildProofResponse,
    ClaimCompleteRequest,
    ClaimCompleteResponse,
    ClaimStartRequest,
    ClaimStartResponse,
    HealthResponse,
    SetCheckpointRequest,
    SetCheckpointResponse,
)
from .proof import ProofBuilder

from web3 import Web3
from eth_account import Account
from eth_account.messages import encode_defunct

# Configure logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
)

logger = structlog.get_logger()


# Global clients (initialized at startup)
_bitcoin_rpc: BitcoinRPC | None = None
_evm_client: EVMClient | None = None
_btc_indexer: BtcIndexer | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler."""
    global _bitcoin_rpc, _evm_client, _btc_indexer

    settings = get_settings()

    # Initialize Bitcoin RPC
    _bitcoin_rpc = BitcoinRPC(
        BitcoinRPCConfig(
            url=settings.bitcoin_rpc_url,
            user=settings.bitcoin_rpc_user,
            password=settings.bitcoin_rpc_password,
        )
    )

    # Initialize EVM client
    _evm_client = EVMClient(settings)
    _btc_indexer = BtcIndexer(
        BtcIndexerConfig(
            base_url=settings.btc_indexer_base_url,
            timeout=settings.btc_indexer_timeout_seconds,
        )
    )

    logger.info(
        "API started",
        version=__version__,
        host=settings.host,
        port=settings.port,
        bitcoin_rpc=settings.bitcoin_rpc_url,
        btc_indexer=settings.btc_indexer_base_url,
        evm_rpc=settings.evm_rpc_url,
    )

    yield

    # Cleanup
    if _bitcoin_rpc:
        await _bitcoin_rpc.close()
    if _btc_indexer:
        await _btc_indexer.close()

    logger.info("API stopped")


# Create FastAPI app
app = FastAPI(
    title="HashCredit API",
    description="HTTP bridge for Frontend to Bitcoin Core/Prover",
    version=__version__,
    lifespan=lifespan,
)


# Add CORS middleware
_settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# Health Check
# ============================================================================


@app.get("/health", response_model=HealthResponse)
async def health_check(settings: Settings = Depends(get_settings)) -> HealthResponse:
    """
    Check API health and connectivity.

    Returns service status and connectivity to Bitcoin/EVM RPCs.
    """
    bitcoin_ok = False
    btc_indexer_ok = False
    evm_ok = False

    if _bitcoin_rpc:
        bitcoin_ok = await _bitcoin_rpc.check_connectivity()

    if _evm_client:
        evm_ok = await _evm_client.check_connectivity()
    if _btc_indexer:
        try:
            await _btc_indexer.get_tip_height()
            btc_indexer_ok = True
        except Exception:
            btc_indexer_ok = False

    return HealthResponse(
        status="ok" if (bitcoin_ok and evm_ok) else "degraded",
        version=__version__,
        bitcoin_rpc=bitcoin_ok,
        btc_indexer=btc_indexer_ok,
        evm_rpc=evm_ok,
        contracts={
            "hash_credit_manager": settings.hash_credit_manager,
            "checkpoint_manager": settings.checkpoint_manager,
            "btc_spv_verifier": settings.btc_spv_verifier,
        },
    )


# ============================================================================
# BTC Address History (External Indexer)
# ============================================================================


@app.get(
    "/btc/address-history",
    response_model=BtcAddressHistoryResponse,
)
async def btc_address_history(address: str, limit: int = 25, mining_only: bool = False) -> BtcAddressHistoryResponse:
    """
    Get address-level BTC history from an external Esplora-compatible indexer.

    This endpoint is read-only and used by demo/ops UI to show address activity.
    Optional `mining_only=true` filters to direct coinbase reward receipts.
    """
    if _btc_indexer is None:
        raise HTTPException(status_code=503, detail="BTC indexer not initialized")

    decoded = decode_btc_address(address)
    if decoded is None:
        return BtcAddressHistoryResponse(
            success=False,
            address=address,
            error="Unsupported or invalid BTC address",
        )

    try:
        result = await _btc_indexer.get_address_history(address=address, limit=limit, mining_only=mining_only)
        return BtcAddressHistoryResponse(
            success=True,
            address=result["address"],
            tip_height=result.get("tip_height"),
            balance_chain_sats=result.get("balance_chain_sats"),
            balance_mempool_delta_sats=result.get("balance_mempool_delta_sats"),
            tx_count_chain=result.get("tx_count_chain"),
            tx_count_mempool=result.get("tx_count_mempool"),
            items=result.get("items", []),
        )
    except httpx.HTTPStatusError as e:
        status = e.response.status_code if e.response is not None else 502
        msg = f"Indexer returned HTTP {status}"
        logger.warning("BTC indexer HTTP error", address=address, status=status)
        return BtcAddressHistoryResponse(
            success=False,
            address=address,
            error=msg,
        )
    except Exception as e:
        logger.error("Failed to fetch BTC address history", address=address, error=str(e))
        return BtcAddressHistoryResponse(
            success=False,
            address=address,
            error=str(e),
        )


# ============================================================================
# SPV Proof Building
# ============================================================================


@app.post(
    "/spv/build-proof",
    response_model=BuildProofResponse,
)
async def build_proof(request: BuildProofRequest) -> BuildProofResponse:
    """
    Build an SPV proof for a Bitcoin transaction.

    Takes transaction details and returns ABI-encoded proof hex
    that can be submitted to the BtcSpvVerifier contract.
    """
    if not _bitcoin_rpc:
        raise HTTPException(status_code=503, detail="Bitcoin RPC not initialized")

    try:
        builder = ProofBuilder(_bitcoin_rpc)
        result = await builder.build_proof(
            txid=request.txid,
            output_index=request.output_index,
            checkpoint_height=request.checkpoint_height,
            target_height=request.target_height,
            borrower=request.borrower,
        )

        encoded = result.proof.encode_for_contract()

        logger.info(
            "Proof built",
            txid=request.txid,
            borrower=request.borrower,
            amount_sats=result.amount_sats,
        )

        return BuildProofResponse(
            success=True,
            proof_hex=f"0x{encoded.hex()}",
            amount_sats=result.amount_sats,
            pubkey_hash=f"0x{result.pubkey_hash.hex()}",
            script_type=result.script_type,
            header_chain_length=len(result.proof.headers),
            merkle_depth=len(result.proof.merkle_proof),
        )

    except Exception as e:
        logger.error("Failed to build proof", error=str(e), txid=request.txid)
        return BuildProofResponse(
            success=False,
            error=str(e),
        )


# ============================================================================
# Checkpoint Payload Builder (read-only)
# ============================================================================


@app.post(
    "/checkpoint/build",
    response_model=SetCheckpointResponse,
)
async def build_checkpoint(
    request: SetCheckpointRequest,
) -> SetCheckpointResponse:
    """
    Build checkpoint payload data for wallet submission.

    Fetches block data from Bitcoin RPC and returns parameters required by
    CheckpointManager.setCheckpoint(...). This endpoint never sends an EVM tx.
    """
    if not _bitcoin_rpc:
        raise HTTPException(status_code=503, detail="Bitcoin RPC not initialized")

    try:
        block_hash_hex = await _bitcoin_rpc.get_block_hash(request.height)
        header_info = await _bitcoin_rpc.get_block_header(block_hash_hex, verbose=True)
        header_hex = await _bitcoin_rpc.get_block_header_hex(block_hash_hex)

        header_bytes = bytes.fromhex(header_hex)
        internal_block_hash = sha256d(header_bytes)
        header = BlockHeader.from_bytes(header_bytes)
        bits = header.bits

        timestamp = header_info["time"]
        chain_work_hex = header_info.get("chainwork", "0")

        return SetCheckpointResponse(
            success=True,
            height=request.height,
            block_hash=f"0x{internal_block_hash.hex()}",
            timestamp=timestamp,
            chain_work=chain_work_hex,
            bits=bits,
            dry_run=True,
        )
    except Exception as e:
        logger.error("Failed to build checkpoint payload", error=str(e), height=request.height)
        return SetCheckpointResponse(
            success=False,
            height=request.height,
            dry_run=True,
            error=str(e),
        )


# ============================================================================
# Borrower Claim (mainnet-grade mapping)
# ============================================================================


@app.post("/claim/start", response_model=ClaimStartResponse)
async def claim_start(
    request: ClaimStartRequest,
    settings: Settings = Depends(get_settings),
) -> ClaimStartResponse:
    """
    Start a borrower claim.

    Returns a claim token and a message to sign with BOTH:
    - EVM wallet (personal_sign)
    - BTC wallet (signmessage; BIP-137 style, base64 output)
    """
    if settings.borrower_mapping_mode.lower() != "claim":
        return ClaimStartResponse(
            success=False,
            borrower=request.borrower,
            btc_address=request.btc_address,
            error="Claim flow is disabled (BORROWER_MAPPING_MODE is not 'claim')",
        )

    if not settings.claim_secret:
        return ClaimStartResponse(
            success=False,
            borrower=request.borrower,
            btc_address=request.btc_address,
            error="CLAIM_SECRET not configured",
        )

    # Validate BTC address format early.
    decoded = decode_btc_address(request.btc_address.strip())
    if decoded is None:
        return ClaimStartResponse(
            success=False,
            borrower=request.borrower,
            btc_address=request.btc_address,
            error="Invalid or unsupported Bitcoin address format",
        )

    try:
        borrower = Web3.to_checksum_address(request.borrower.strip())
    except Exception:
        return ClaimStartResponse(
            success=False,
            borrower=request.borrower,
            btc_address=request.btc_address,
            error="Invalid borrower EVM address",
        )
    btc_address = request.btc_address.strip()

    token, payload = issue_claim_token(
        secret=settings.claim_secret,
        borrower=borrower,
        btc_address=btc_address,
        chain_id=settings.chain_id,
        ttl_seconds=settings.claim_ttl_seconds,
    )
    message = build_claim_message(payload)
    return ClaimStartResponse(
        success=True,
        borrower=borrower,
        btc_address=btc_address,
        claim_token=token,
        message=message,
        expires_at=payload.expires_at,
    )


@app.post("/claim/complete", response_model=ClaimCompleteResponse)
async def claim_complete(
    request: ClaimCompleteRequest,
    settings: Settings = Depends(get_settings),
) -> ClaimCompleteResponse:
    """
    Verify a borrower claim:
    1) Verify claim token (HMAC)
    2) Verify EVM signature over message
    3) Verify BTC signature over message
    4) Return derived hashes for wallet-side on-chain submission
    """
    if settings.borrower_mapping_mode.lower() != "claim":
        return ClaimCompleteResponse(success=False, dry_run=True, error="Claim flow is disabled")

    if not settings.claim_secret:
        return ClaimCompleteResponse(success=False, dry_run=True, error="CLAIM_SECRET not configured")

    try:
        payload = verify_claim_token(secret=settings.claim_secret, token=request.claim_token)
    except Exception as e:
        return ClaimCompleteResponse(success=False, dry_run=True, error=f"Invalid claim token: {e}")

    message = build_claim_message(payload)

    # Verify EVM signature
    try:
        recovered = Account.recover_message(encode_defunct(text=message), signature=request.evm_signature)
    except Exception as e:
        return ClaimCompleteResponse(
            success=False,
            borrower=payload.borrower,
            btc_address=payload.btc_address,
            dry_run=True,
            error=f"Invalid EVM signature: {e}",
        )
    if recovered.lower() != payload.borrower.lower():
        return ClaimCompleteResponse(
            success=False,
            borrower=payload.borrower,
            btc_address=payload.btc_address,
            dry_run=True,
            error="EVM signature does not match borrower address",
        )

    # Verify BTC signature (optional — skipped when using MetaMask BTC wallet)
    if request.btc_signature:
        try:
            ok = verify_bip137_signature(btc_address=payload.btc_address, message=message, signature_b64=request.btc_signature)
        except Exception as e:
            return ClaimCompleteResponse(
                success=False,
                borrower=payload.borrower,
                btc_address=payload.btc_address,
                dry_run=True,
                error=f"BTC signature verification error: {e}",
            )
        if not ok:
            return ClaimCompleteResponse(
                success=False,
                borrower=payload.borrower,
                btc_address=payload.btc_address,
                dry_run=True,
                error="BTC signature does not match btc_address",
            )

    decoded = decode_btc_address(payload.btc_address)
    if decoded is None:
        return ClaimCompleteResponse(
            success=False,
            borrower=payload.borrower,
            btc_address=payload.btc_address,
            dry_run=True,
            error="Unsupported BTC address type",
        )
    pubkey_hash, _addr_type = decoded
    pubkey_hash_hex = f"0x{pubkey_hash.hex()}"

    btc_payout_key_hash = Web3.keccak(text=payload.btc_address)
    btc_payout_key_hash_hex = f"0x{btc_payout_key_hash.hex()}"

    return ClaimCompleteResponse(
        success=True,
        borrower=payload.borrower,
        btc_address=payload.btc_address,
        pubkey_hash=pubkey_hash_hex,
        btc_payout_key_hash=btc_payout_key_hash_hex,
        dry_run=True,
    )


# ============================================================================
# Entry Point
# ============================================================================


def run() -> None:
    """Run the API server."""
    settings = get_settings()
    uvicorn.run(
        "hashcredit_api.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )


if __name__ == "__main__":
    run()
