"""
Tests for proof builder.
"""

import pytest
from hashcredit_prover.bitcoin import sha256d, BlockHeader
from hashcredit_prover.rpc import MockBitcoinRPC
from hashcredit_prover.proof_builder import ProofBuilder


def create_mock_header(
    prev_hash: bytes,
    merkle_root: bytes,
    timestamp: int = 1690000000,
    bits: int = 0x1D00FFFF,
    nonce: int = 0,
) -> bytes:
    """Create a mock 80-byte header."""
    return (
        (1).to_bytes(4, "little")  # version
        + prev_hash
        + merkle_root
        + timestamp.to_bytes(4, "little")
        + bits.to_bytes(4, "little")
        + nonce.to_bytes(4, "little")
    )


def create_mock_tx(value_sats: int, pubkey_hash: bytes) -> bytes:
    """
    Create a minimal mock transaction with one P2WPKH output.
    This is NOT a valid Bitcoin transaction, just enough for parsing tests.
    """
    # Version
    tx = (1).to_bytes(4, "little")

    # 1 input (dummy)
    tx += b"\x01"  # input count
    tx += b"\x00" * 32  # prev txid
    tx += b"\x00\x00\x00\x00"  # prev vout
    tx += b"\x00"  # script length (empty)
    tx += b"\xff\xff\xff\xff"  # sequence

    # 1 output (P2WPKH)
    tx += b"\x01"  # output count
    tx += value_sats.to_bytes(8, "little")  # value
    script = b"\x00\x14" + pubkey_hash  # P2WPKH: OP_0 <20 bytes>
    tx += bytes([len(script)]) + script

    # Locktime
    tx += b"\x00\x00\x00\x00"

    return tx


@pytest.fixture
def mock_rpc() -> MockBitcoinRPC:
    """Create a mock RPC with test data."""
    rpc = MockBitcoinRPC()

    # Create a simple test chain
    pubkey_hash = bytes.fromhex("1234567890abcdef1234567890abcdef12345678")
    test_tx = create_mock_tx(100000, pubkey_hash)  # 0.001 BTC
    txid = sha256d(test_tx)
    txid_display = txid[::-1].hex()

    # Create headers chain
    prev_hash = b"\x00" * 32  # Genesis-like

    # Block 800000 (checkpoint)
    merkle_root_800000 = sha256d(b"block 800000")
    header_800000 = create_mock_header(prev_hash, merkle_root_800000, timestamp=1690000000)
    hash_800000 = sha256d(header_800000)

    # Block 800001
    merkle_root_800001 = sha256d(b"block 800001")
    header_800001 = create_mock_header(hash_800000, merkle_root_800001, timestamp=1690000600)
    hash_800001 = sha256d(header_800001)

    # Block 800002
    merkle_root_800002 = sha256d(b"block 800002")
    header_800002 = create_mock_header(hash_800001, merkle_root_800002, timestamp=1690001200)
    hash_800002 = sha256d(header_800002)

    # Block 800003
    merkle_root_800003 = sha256d(b"block 800003")
    header_800003 = create_mock_header(hash_800002, merkle_root_800003, timestamp=1690001800)
    hash_800003 = sha256d(header_800003)

    # Block 800004
    merkle_root_800004 = sha256d(b"block 800004")
    header_800004 = create_mock_header(hash_800003, merkle_root_800004, timestamp=1690002400)
    hash_800004 = sha256d(header_800004)

    # Block 800005
    merkle_root_800005 = sha256d(b"block 800005")
    header_800005 = create_mock_header(hash_800004, merkle_root_800005, timestamp=1690003000)
    hash_800005 = sha256d(header_800005)

    # Block 800006 (target block with our transaction)
    # Single tx, so merkle root = txid
    header_800006 = create_mock_header(hash_800005, txid, timestamp=1690003600)
    hash_800006 = sha256d(header_800006)

    # Additional blocks for confirmations (800007-800011)
    # Need 6 confirmations: if tx is in block N, we need blocks up to N+5
    merkle_root_800007 = sha256d(b"block 800007")
    header_800007 = create_mock_header(hash_800006, merkle_root_800007, timestamp=1690004200)
    hash_800007 = sha256d(header_800007)

    merkle_root_800008 = sha256d(b"block 800008")
    header_800008 = create_mock_header(hash_800007, merkle_root_800008, timestamp=1690004800)
    hash_800008 = sha256d(header_800008)

    merkle_root_800009 = sha256d(b"block 800009")
    header_800009 = create_mock_header(hash_800008, merkle_root_800009, timestamp=1690005400)
    hash_800009 = sha256d(header_800009)

    merkle_root_800010 = sha256d(b"block 800010")
    header_800010 = create_mock_header(hash_800009, merkle_root_800010, timestamp=1690006000)
    hash_800010 = sha256d(header_800010)

    merkle_root_800011 = sha256d(b"block 800011")
    header_800011 = create_mock_header(hash_800010, merkle_root_800011, timestamp=1690006600)
    hash_800011 = sha256d(header_800011)

    # Add blocks to mock
    rpc.add_block(800000, hash_800000[::-1].hex(), header_800000.hex(), [])
    rpc.add_block(800001, hash_800001[::-1].hex(), header_800001.hex(), [])
    rpc.add_block(800002, hash_800002[::-1].hex(), header_800002.hex(), [])
    rpc.add_block(800003, hash_800003[::-1].hex(), header_800003.hex(), [])
    rpc.add_block(800004, hash_800004[::-1].hex(), header_800004.hex(), [])
    rpc.add_block(800005, hash_800005[::-1].hex(), header_800005.hex(), [])
    rpc.add_block(800006, hash_800006[::-1].hex(), header_800006.hex(), [txid_display])
    rpc.add_block(800007, hash_800007[::-1].hex(), header_800007.hex(), [])
    rpc.add_block(800008, hash_800008[::-1].hex(), header_800008.hex(), [])
    rpc.add_block(800009, hash_800009[::-1].hex(), header_800009.hex(), [])
    rpc.add_block(800010, hash_800010[::-1].hex(), header_800010.hex(), [])
    rpc.add_block(800011, hash_800011[::-1].hex(), header_800011.hex(), [])

    # Add transaction
    rpc.add_transaction(txid_display, test_tx.hex())

    return rpc


@pytest.fixture
def test_txid(mock_rpc: MockBitcoinRPC) -> str:
    """Get the test transaction ID."""
    pubkey_hash = bytes.fromhex("1234567890abcdef1234567890abcdef12345678")
    test_tx = create_mock_tx(100000, pubkey_hash)
    txid = sha256d(test_tx)
    return txid[::-1].hex()


class TestProofBuilder:
    """Tests for ProofBuilder."""

    @pytest.mark.asyncio
    async def test_build_proof_basic(
        self, mock_rpc: MockBitcoinRPC, test_txid: str
    ) -> None:
        """Test basic proof building."""
        builder = ProofBuilder(mock_rpc)
        borrower = "0x1234567890123456789012345678901234567890"

        result = await builder.build_proof(
            txid=test_txid,
            output_index=0,
            checkpoint_height=800000,
            target_height=800006,
            borrower=borrower,
        )

        # Check proof structure
        assert result.proof.checkpoint_height == 800000
        assert len(result.proof.headers) == 11  # 800001-800011 (tip_height default: target+5)
        assert result.proof.tx_block_index == 5  # tx is in 800006, index 5 in headers
        assert result.proof.output_index == 0
        assert result.proof.borrower == borrower

        # Check extracted data
        assert result.amount_sats == 100000
        assert result.script_type == "p2wpkh"
        assert result.block_height == 800006
        assert result.pubkey_hash == bytes.fromhex(
            "1234567890abcdef1234567890abcdef12345678"
        )

    @pytest.mark.asyncio
    async def test_verify_proof_locally(
        self, mock_rpc: MockBitcoinRPC, test_txid: str
    ) -> None:
        """Test local proof verification."""
        builder = ProofBuilder(mock_rpc)
        borrower = "0x1234567890123456789012345678901234567890"

        result = await builder.build_proof(
            txid=test_txid,
            output_index=0,
            checkpoint_height=800000,
            target_height=800006,
            borrower=borrower,
        )

        # Verify locally
        is_valid = await builder.verify_proof_locally(result)
        assert is_valid

    @pytest.mark.asyncio
    async def test_proof_encoding(
        self, mock_rpc: MockBitcoinRPC, test_txid: str
    ) -> None:
        """Test ABI encoding of proof."""
        builder = ProofBuilder(mock_rpc)
        borrower = "0x1234567890123456789012345678901234567890"

        result = await builder.build_proof(
            txid=test_txid,
            output_index=0,
            checkpoint_height=800000,
            target_height=800006,
            borrower=borrower,
        )

        # Should not raise
        encoded = result.proof.encode_for_contract()
        assert len(encoded) > 0
        assert isinstance(encoded, bytes)

    @pytest.mark.asyncio
    async def test_proof_to_dict(
        self, mock_rpc: MockBitcoinRPC, test_txid: str
    ) -> None:
        """Test JSON serialization of proof."""
        builder = ProofBuilder(mock_rpc)
        borrower = "0x1234567890123456789012345678901234567890"

        result = await builder.build_proof(
            txid=test_txid,
            output_index=0,
            checkpoint_height=800000,
            target_height=800006,
            borrower=borrower,
        )

        proof_dict = result.proof.to_dict()

        assert proof_dict["checkpointHeight"] == 800000
        assert len(proof_dict["headers"]) == 11  # 800001-800011
        assert proof_dict["txBlockIndex"] == 5  # tx is in 800006
        assert proof_dict["outputIndex"] == 0
        assert proof_dict["borrower"] == borrower

    @pytest.mark.asyncio
    async def test_invalid_output_index(
        self, mock_rpc: MockBitcoinRPC, test_txid: str
    ) -> None:
        """Test error handling for invalid output index."""
        builder = ProofBuilder(mock_rpc)
        borrower = "0x1234567890123456789012345678901234567890"

        with pytest.raises(ValueError, match="out of range"):
            await builder.build_proof(
                txid=test_txid,
                output_index=5,  # Only 1 output exists
                checkpoint_height=800000,
                target_height=800006,
                borrower=borrower,
            )
