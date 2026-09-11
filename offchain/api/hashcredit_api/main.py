"""
HashCredit API - HTTP bridge for Frontend to Bitcoin Core/Prover.

Provides REST endpoints for:
- Building SPV proofs (POST /spv/build-proof)
- Setting checkpoints (POST /checkpoint/set)
- Setting borrower pubkey hash (POST /borrower/set-pubkey-hash)
- Submitting proofs (POST /spv/submit)
- Health checks (GET /health)
"""

import uvicorn
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .address import decode_btc_address
from .auth import verify_api_token
from .btc_signmessage import verify_bip137_signature
from .bitcoin import BitcoinRPC, BitcoinRPCConfig, sha256d
from .claim import build_claim_message, issue_claim_token, verify_claim_token
from .proof import BlockHeader
from .config import Settings, get_settings
from .evm import EVMClient
from .models import (
    BuildProofRequest,
    BuildProofResponse,
    ClaimCompleteRequest,
    ClaimCompleteResponse,
    ClaimStartRequest,
    ClaimStartResponse,
    HealthResponse,
    RegisterBorrowerRequest,
    RegisterBorrowerResponse,
    SetBorrowerPubkeyHashRequest,
    SetBorrowerPubkeyHashResponse,
    SetCheckpointRequest,
    SetCheckpointResponse,
    SubmitProofRequest,
    SubmitProofResponse,
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


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler."""
    global _bitcoin_rpc, _evm_client

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

    logger.info(
        "API started",
        version=__version__,
        host=settings.host,
        port=settings.port,
        bitcoin_rpc=settings.bitcoin_rpc_url,
        evm_rpc=settings.evm_rpc_url,
    )

    yield

    # Cleanup
    if _bitcoin_rpc:
        await _bitcoin_rpc.close()

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
    evm_ok = False

    if _bitcoin_rpc:
        bitcoin_ok = await _bitcoin_rpc.check_connectivity()

    if _evm_client:
        evm_ok = await _evm_client.check_connectivity()

    return HealthResponse(
        status="ok" if (bitcoin_ok and evm_ok) else "degraded",
        version=__version__,
        bitcoin_rpc=bitcoin_ok,
        evm_rpc=evm_ok,
        contracts={
            "hash_credit_manager": settings.hash_credit_manager,
            "checkpoint_manager": settings.checkpoint_manager,
            "btc_spv_verifier": settings.btc_spv_verifier,
        },
    )


# ============================================================================
# SPV Proof Building
# ============================================================================


@app.post(
    "/spv/build-proof",
    response_model=BuildProofResponse,
    dependencies=[Depends(verify_api_token)],
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
# Submit Proof
# ============================================================================


@app.post(
    "/spv/submit",
    response_model=SubmitProofResponse,
    dependencies=[Depends(verify_api_token)],
)
async def submit_proof(
    request: SubmitProofRequest,
    settings: Settings = Depends(get_settings),
) -> SubmitProofResponse:
    """
    Submit an SPV proof to the HashCreditManager contract.

    Takes ABI-encoded proof and submits it via submitPayout().
    """
    if not _evm_client:
        raise HTTPException(status_code=503, detail="EVM client not initialized")

    if not settings.private_key:
        raise HTTPException(status_code=503, detail="Private key not configured")

    if not settings.hash_credit_manager:
        raise HTTPException(status_code=503, detail="HASH_CREDIT_MANAGER not configured")

    try:
        # Parse proof hex
        proof_hex = request.proof_hex
        if proof_hex.startswith("0x"):
            proof_hex = proof_hex[2:]
        proof_bytes = bytes.fromhex(proof_hex)

        if request.dry_run:
            logger.info("Dry run: would submit proof", proof_size=len(proof_bytes))
            return SubmitProofResponse(
                success=True,
                dry_run=True,
            )

        # Submit proof
        receipt = await _evm_client.submit_payout(proof_bytes)

        logger.info(
            "Proof submitted",
            tx_hash=receipt["transactionHash"].hex(),
            gas_used=receipt["gasUsed"],
        )

        return SubmitProofResponse(
            success=receipt["status"] == 1,
            tx_hash=receipt["transactionHash"].hex(),
            block_number=receipt["blockNumber"],
            gas_used=receipt["gasUsed"],
            dry_run=False,
        )

    except Exception as e:
        logger.error("Failed to submit proof", error=str(e))
        return SubmitProofResponse(
            success=False,
            error=str(e),
            dry_run=request.dry_run,
        )


# ============================================================================
# Checkpoint Management
# ============================================================================


@app.post(
    "/checkpoint/set",
    response_model=SetCheckpointResponse,
    dependencies=[Depends(verify_api_token)],
)
async def set_checkpoint(
    request: SetCheckpointRequest,
    settings: Settings = Depends(get_settings),
) -> SetCheckpointResponse:
    """
    Register a Bitcoin block checkpoint on CheckpointManager.

    Fetches block header from Bitcoin RPC and submits to EVM contract.
    """
    if not _bitcoin_rpc:
        raise HTTPException(status_code=503, detail="Bitcoin RPC not initialized")

    if not _evm_client:
        raise HTTPException(status_code=503, detail="EVM client not initialized")

    if not settings.private_key and not request.dry_run:
        raise HTTPException(status_code=503, detail="Private key not configured")

    if not settings.checkpoint_manager:
        raise HTTPException(status_code=503, detail="CHECKPOINT_MANAGER not configured")

    try:
        # Fetch block info from Bitcoin
        block_hash_hex = await _bitcoin_rpc.get_block_hash(request.height)
        header_info = await _bitcoin_rpc.get_block_header(block_hash_hex, verbose=True)
        header_hex = await _bitcoin_rpc.get_block_header_hex(block_hash_hex)

        # Calculate internal block hash and parse bits
        header_bytes = bytes.fromhex(header_hex)
        internal_block_hash = sha256d(header_bytes)

        # Parse header to extract bits
        header = BlockHeader.from_bytes(header_bytes)
        bits = header.bits

        # Extract fields
        timestamp = header_info["time"]
        chain_work_hex = header_info.get("chainwork", "0")
        chain_work = int(chain_work_hex, 16)

        if request.dry_run:
            logger.info(
                "Dry run: would set checkpoint",
                height=request.height,
                block_hash=internal_block_hash.hex(),
                bits=f"0x{bits:08x}",
            )
            return SetCheckpointResponse(
                success=True,
                height=request.height,
                block_hash=f"0x{internal_block_hash.hex()}",
                timestamp=timestamp,
                chain_work=chain_work_hex,
                bits=bits,
                dry_run=True,
            )

        # Submit to contract
        receipt = await _evm_client.set_checkpoint(
            height=request.height,
            block_hash=internal_block_hash,
            chain_work=chain_work,
            timestamp=timestamp,
            bits=bits,
        )

        logger.info(
            "Checkpoint set",
            height=request.height,
            tx_hash=receipt["transactionHash"].hex(),
        )

        return SetCheckpointResponse(
            success=receipt["status"] == 1,
            height=request.height,
            block_hash=f"0x{internal_block_hash.hex()}",
            timestamp=timestamp,
            chain_work=chain_work_hex,
            bits=bits,
            tx_hash=receipt["transactionHash"].hex(),
            gas_used=receipt["gasUsed"],
            dry_run=False,
        )

    except Exception as e:
        logger.error("Failed to set checkpoint", error=str(e), height=request.height)
        return SetCheckpointResponse(
            success=False,
            height=request.height,
            dry_run=request.dry_run,
            error=str(e),
        )


# ============================================================================
# Borrower Management
# ============================================================================


@app.post(
    "/borrower/set-pubkey-hash",
    response_model=SetBorrowerPubkeyHashResponse,
    dependencies=[Depends(verify_api_token)],
)
async def set_borrower_pubkey_hash(
    request: SetBorrowerPubkeyHashRequest,
    settings: Settings = Depends(get_settings),
) -> SetBorrowerPubkeyHashResponse:
    """
    Register a borrower's Bitcoin pubkey hash on BtcSpvVerifier.

    Decodes the Bitcoin address to extract the pubkey hash and
    registers it on-chain for SPV proof verification.
    """
    if not _evm_client:
        raise HTTPException(status_code=503, detail="EVM client not initialized")

    if not settings.private_key and not request.dry_run:
        raise HTTPException(status_code=503, detail="Private key not configured")

    if not settings.btc_spv_verifier:
        raise HTTPException(status_code=503, detail="BTC_SPV_VERIFIER not configured")

    if settings.borrower_mapping_mode.lower() == "claim":
        raise HTTPException(status_code=403, detail="Direct mapping is disabled in claim mode. Use /claim/*.")

    try:
        # Decode Bitcoin address
        result = decode_btc_address(request.btc_address)
        if result is None:
            return SetBorrowerPubkeyHashResponse(
                success=False,
                borrower=request.borrower,
                error="Invalid or unsupported Bitcoin address format",
                dry_run=request.dry_run,
            )

        pubkey_hash, addr_type = result

        if request.dry_run:
            logger.info(
                "Dry run: would set borrower pubkey hash",
                borrower=request.borrower,
                pubkey_hash=pubkey_hash.hex(),
            )
            return SetBorrowerPubkeyHashResponse(
                success=True,
                borrower=request.borrower,
                pubkey_hash=f"0x{pubkey_hash.hex()}",
                address_type=addr_type,
                dry_run=True,
            )

        # Submit to contract
        receipt = await _evm_client.set_borrower_pubkey_hash(
            borrower=request.borrower,
            pubkey_hash=pubkey_hash,
        )

        logger.info(
            "Borrower pubkey hash set",
            borrower=request.borrower,
            tx_hash=receipt["transactionHash"].hex(),
        )

        return SetBorrowerPubkeyHashResponse(
            success=receipt["status"] == 1,
            borrower=request.borrower,
            pubkey_hash=f"0x{pubkey_hash.hex()}",
            address_type=addr_type,
            tx_hash=receipt["transactionHash"].hex(),
            gas_used=receipt["gasUsed"],
            dry_run=False,
        )

    except Exception as e:
        logger.error(
            "Failed to set borrower pubkey hash",
            error=str(e),
            borrower=request.borrower,
        )
        return SetBorrowerPubkeyHashResponse(
            success=False,
            borrower=request.borrower,
            dry_run=request.dry_run,
            error=str(e),
        )


# ============================================================================
# Manager Admin (Borrower Registration)
# ============================================================================


@app.post(
    "/manager/register-borrower",
    response_model=RegisterBorrowerResponse,
    dependencies=[Depends(verify_api_token)],
)
async def register_borrower(
    request: RegisterBorrowerRequest,
    settings: Settings = Depends(get_settings),
) -> RegisterBorrowerResponse:
    """
    Register a borrower on HashCreditManager (owner-only).

    Computes btcPayoutKeyHash = keccak256(utf8(btc_address)) and calls
    HashCreditManager.registerBorrower(borrower, btcPayoutKeyHash).
    """
    if not _evm_client:
        raise HTTPException(status_code=503, detail="EVM client not initialized")

    if not settings.private_key and not request.dry_run:
        raise HTTPException(status_code=503, detail="Private key not configured")

    if not settings.hash_credit_manager:
        raise HTTPException(status_code=503, detail="HASH_CREDIT_MANAGER not configured")

    if settings.borrower_mapping_mode.lower() == "claim":
        raise HTTPException(status_code=403, detail="Direct borrower registration is disabled in claim mode. Use /claim/*.")

    try:
        btc_payout_key_hash = Web3.keccak(text=request.btc_address)
        btc_payout_key_hash_hex = f"0x{btc_payout_key_hash.hex()}"

        if request.dry_run:
            logger.info(
                "Dry run: would register borrower",
                borrower=request.borrower,
                btc_payout_key_hash=btc_payout_key_hash_hex,
            )
            return RegisterBorrowerResponse(
                success=True,
                borrower=request.borrower,
                btc_address=request.btc_address,
                btc_payout_key_hash=btc_payout_key_hash_hex,
                dry_run=True,
            )

        receipt = await _evm_client.register_borrower(
            borrower=request.borrower,
            btc_payout_key_hash=btc_payout_key_hash,
        )

        logger.info(
            "Borrower registered",
            borrower=request.borrower,
            tx_hash=receipt["transactionHash"].hex(),
        )

        return RegisterBorrowerResponse(
            success=receipt["status"] == 1,
            borrower=request.borrower,
            btc_address=request.btc_address,
            btc_payout_key_hash=btc_payout_key_hash_hex,
            tx_hash=receipt["transactionHash"].hex(),
            gas_used=receipt["gasUsed"],
            dry_run=False,
        )

    except Exception as e:
        logger.error("Failed to register borrower", error=str(e), borrower=request.borrower)
        return RegisterBorrowerResponse(
            success=False,
            borrower=request.borrower,
            btc_address=request.btc_address,
            btc_payout_key_hash=None,
            dry_run=request.dry_run,
            error=str(e),
        )


# ============================================================================
# Borrower Claim (mainnet-grade mapping)
# ============================================================================


@app.post("/claim/start", response_model=ClaimStartResponse)
async def claim_start(
    request: ClaimStartRequest,
    http_request: Request,
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

    if settings.claim_require_api_token and settings.api_token:
        api_key = http_request.headers.get("X-API-Key", "")
        if api_key != settings.api_token:
            raise HTTPException(status_code=401, detail="API token required for claim endpoints")

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
    http_request: Request,
    settings: Settings = Depends(get_settings),
) -> ClaimCompleteResponse:
    """
    Complete a borrower claim:
    1) Verify claim token (HMAC)
    2) Verify EVM signature over message
    3) Verify BTC signature over message
    4) If not dry-run, register on-chain:
       - BtcSpvVerifier.setBorrowerPubkeyHash(borrower, pubkeyHash)
       - HashCreditManager.registerBorrower(borrower, keccak256(btc_address))
    """
    if settings.borrower_mapping_mode.lower() != "claim":
        return ClaimCompleteResponse(success=False, dry_run=request.dry_run, error="Claim flow is disabled")

    if not settings.claim_secret:
        return ClaimCompleteResponse(success=False, dry_run=request.dry_run, error="CLAIM_SECRET not configured")

    if settings.claim_require_api_token and settings.api_token:
        api_key = http_request.headers.get("X-API-Key", "")
        if api_key != settings.api_token:
            raise HTTPException(status_code=401, detail="API token required for claim endpoints")

    if not _evm_client:
        raise HTTPException(status_code=503, detail="EVM client not initialized")

    try:
        payload = verify_claim_token(secret=settings.claim_secret, token=request.claim_token)
    except Exception as e:
        return ClaimCompleteResponse(success=False, dry_run=request.dry_run, error=f"Invalid claim token: {e}")

    message = build_claim_message(payload)

    # Verify EVM signature
    try:
        recovered = Account.recover_message(encode_defunct(text=message), signature=request.evm_signature)
    except Exception as e:
        return ClaimCompleteResponse(
            success=False,
            borrower=payload.borrower,
            btc_address=payload.btc_address,
            dry_run=request.dry_run,
            error=f"Invalid EVM signature: {e}",
        )
    if recovered.lower() != payload.borrower.lower():
        return ClaimCompleteResponse(
            success=False,
            borrower=payload.borrower,
            btc_address=payload.btc_address,
            dry_run=request.dry_run,
            error="EVM signature does not match borrower address",
        )

    # Verify BTC signature
    try:
        ok = verify_bip137_signature(btc_address=payload.btc_address, message=message, signature_b64=request.btc_signature)
    except Exception as e:
        return ClaimCompleteResponse(
            success=False,
            borrower=payload.borrower,
            btc_address=payload.btc_address,
            dry_run=request.dry_run,
            error=f"BTC signature verification error: {e}",
        )
    if not ok:
        return ClaimCompleteResponse(
            success=False,
            borrower=payload.borrower,
            btc_address=payload.btc_address,
            dry_run=request.dry_run,
            error="BTC signature does not match btc_address",
        )

    decoded = decode_btc_address(payload.btc_address)
    if decoded is None:
        return ClaimCompleteResponse(
            success=False,
            borrower=payload.borrower,
            btc_address=payload.btc_address,
            dry_run=request.dry_run,
            error="Unsupported BTC address type",
        )
    pubkey_hash, _addr_type = decoded
    pubkey_hash_hex = f"0x{pubkey_hash.hex()}"

    btc_payout_key_hash = Web3.keccak(text=payload.btc_address)
    btc_payout_key_hash_hex = f"0x{btc_payout_key_hash.hex()}"

    if request.dry_run:
        return ClaimCompleteResponse(
            success=True,
            borrower=payload.borrower,
            btc_address=payload.btc_address,
            pubkey_hash=pubkey_hash_hex,
            btc_payout_key_hash=btc_payout_key_hash_hex,
            dry_run=True,
        )

    if not settings.private_key:
        raise HTTPException(status_code=503, detail="Private key not configured")
    if not settings.btc_spv_verifier:
        raise HTTPException(status_code=503, detail="BTC_SPV_VERIFIER not configured")
    if not settings.hash_credit_manager:
        raise HTTPException(status_code=503, detail="HASH_CREDIT_MANAGER not configured")

    # 1) Always (re-)set pubkey hash (owner-only).
    receipt_set = await _evm_client.set_borrower_pubkey_hash(borrower=payload.borrower, pubkey_hash=pubkey_hash)
    tx_set = receipt_set["transactionHash"].hex()

    # 2) Register borrower if not registered (status==0)
    tx_reg = None
    try:
        status = await _evm_client.get_borrower_status(payload.borrower)
    except Exception:
        status = 0
    if status == 0:
        receipt_reg = await _evm_client.register_borrower(payload.borrower, btc_payout_key_hash)
        tx_reg = receipt_reg["transactionHash"].hex()

    return ClaimCompleteResponse(
        success=True,
        borrower=payload.borrower,
        btc_address=payload.btc_address,
        pubkey_hash=pubkey_hash_hex,
        btc_payout_key_hash=btc_payout_key_hash_hex,
        tx_set_pubkey_hash=tx_set,
        tx_register_borrower=tx_reg,
        dry_run=False,
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
