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
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .address import decode_btc_address
from .auth import verify_api_token
from .bitcoin import BitcoinRPC, BitcoinRPCConfig, sha256d, BlockHeader
from .config import Settings, get_settings
from .evm import EVMClient
from .models import (
    BuildProofRequest,
    BuildProofResponse,
    HealthResponse,
    SetBorrowerPubkeyHashRequest,
    SetBorrowerPubkeyHashResponse,
    SetCheckpointRequest,
    SetCheckpointResponse,
    SubmitProofRequest,
    SubmitProofResponse,
)
from .proof import ProofBuilder

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
