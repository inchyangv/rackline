"""
Tests for Bitcoin utilities.
"""

import pytest
from hashcredit_prover.bitcoin import (
    sha256d,
    reverse_bytes,
    bytes_to_hex_le,
    hex_le_to_bytes,
    txid_display_to_internal,
    txid_internal_to_display,
    BlockHeader,
    compute_merkle_root,
    generate_merkle_proof,
    verify_merkle_proof,
    parse_varint,
    parse_tx_outputs,
    extract_pubkey_hash,
)


class TestSha256d:
    """Tests for sha256d."""

    def test_empty_bytes(self) -> None:
        """sha256d of empty bytes."""
        result = sha256d(b"")
        # sha256d("") = 0x5df6e0e2761359d30a8275058e299fcc0381534545f55cf43e41983f5d4c9456
        expected = bytes.fromhex(
            "5df6e0e2761359d30a8275058e299fcc0381534545f55cf43e41983f5d4c9456"
        )
        assert result == expected

    def test_hello_world(self) -> None:
        """sha256d of 'hello world'."""
        result = sha256d(b"hello world")
        # Known value
        assert len(result) == 32


class TestByteOrder:
    """Tests for byte order utilities."""

    def test_reverse_bytes(self) -> None:
        assert reverse_bytes(b"\x01\x02\x03") == b"\x03\x02\x01"

    def test_bytes_to_hex_le(self) -> None:
        assert bytes_to_hex_le(b"\x01\x02\x03") == "030201"

    def test_hex_le_to_bytes(self) -> None:
        assert hex_le_to_bytes("030201") == b"\x01\x02\x03"


class TestTxidConversion:
    """Tests for txid format conversion.

    Protocol standard:
    - On-chain: internal byte order (sha256d result without reversal)
    - Display format (block explorers): reversed byte order

    Example:
    - Raw tx sha256d = 0102030405...1f2021222324252627282930313233 (internal)
    - Display format = 3332313029...060504030201 (reversed)
    """

    def test_display_to_internal(self) -> None:
        """Convert display format txid to internal format."""
        # Display format (what you see on blockchain.info)
        display_txid = "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789"

        internal = txid_display_to_internal(display_txid)

        # Should be reversed
        expected = bytes.fromhex(display_txid)[::-1]
        assert internal == expected
        assert len(internal) == 32

    def test_internal_to_display(self) -> None:
        """Convert internal format txid to display format."""
        internal = bytes.fromhex("0102030405060708091011121314151617181920212223242526272829303132")

        display = txid_internal_to_display(internal)

        # Should be reversed hex
        assert display == "3231302928272625242322212019181716151413121110090807060504030201"

    def test_round_trip(self) -> None:
        """Converting display -> internal -> display should be identity."""
        original_display = "deadbeef" * 8  # 32 bytes = 64 hex chars

        internal = txid_display_to_internal(original_display)
        back_to_display = txid_internal_to_display(internal)

        assert back_to_display == original_display

    def test_real_bitcoin_txid(self) -> None:
        """Test with a real Bitcoin transaction ID.

        This is the genesis block coinbase tx:
        Display: 4a5e1e4baab89f3a32518a88c31bc87f618f76673e2cc77ab2127b7afdeda33b
        """
        genesis_txid_display = (
            "4a5e1e4baab89f3a32518a88c31bc87f618f76673e2cc77ab2127b7afdeda33b"
        )

        internal = txid_display_to_internal(genesis_txid_display)

        # Internal format should be the reversed bytes
        assert len(internal) == 32
        assert internal[0] == 0x3B  # First byte of internal = last byte of display
        assert internal[31] == 0x4A  # Last byte of internal = first byte of display

        # Round trip
        assert txid_internal_to_display(internal) == genesis_txid_display


class TestBlockHeader:
    """Tests for BlockHeader parsing."""

    def test_parse_80_bytes(self) -> None:
        """Parse a valid 80-byte header."""
        # Construct a test header
        header_bytes = (
            b"\x01\x00\x00\x00"  # version = 1
            + b"\x00" * 32  # prev_block_hash
            + b"\x00" * 32  # merkle_root
            + b"\x78\x56\x34\x12"  # timestamp = 0x12345678
            + b"\xff\xff\x00\x1d"  # bits = 0x1d00ffff
            + b"\xef\xbe\xad\xde"  # nonce = 0xdeadbeef
        )
        assert len(header_bytes) == 80

        header = BlockHeader.from_bytes(header_bytes)

        assert header.version == 1
        assert header.timestamp == 0x12345678
        assert header.bits == 0x1D00FFFF
        assert header.nonce == 0xDEADBEEF

    def test_invalid_size(self) -> None:
        """Reject headers that aren't 80 bytes."""
        with pytest.raises(ValueError):
            BlockHeader.from_bytes(b"\x00" * 79)

    def test_round_trip(self) -> None:
        """Parse and serialize should be identity."""
        original = b"\x01\x00\x00\x00" + b"\xaa" * 32 + b"\xbb" * 32 + b"\x00" * 12
        header = BlockHeader.from_bytes(original)
        assert header.to_bytes() == original


class TestMerkleTree:
    """Tests for Merkle tree operations."""

    def test_single_tx(self) -> None:
        """Single transaction: root = txid."""
        txid = sha256d(b"test tx")
        root = compute_merkle_root([txid])
        assert root == txid

    def test_two_txs(self) -> None:
        """Two transactions."""
        txA = sha256d(b"txA")
        txB = sha256d(b"txB")
        root = compute_merkle_root([txA, txB])
        expected = sha256d(txA + txB)
        assert root == expected

    def test_three_txs(self) -> None:
        """Three transactions (odd, needs duplication)."""
        txA = sha256d(b"txA")
        txB = sha256d(b"txB")
        txC = sha256d(b"txC")

        # Level 1: hash(A,B), hash(C,C)
        # Level 0: hash(hash(A,B), hash(C,C))
        ab = sha256d(txA + txB)
        cc = sha256d(txC + txC)
        expected = sha256d(ab + cc)

        root = compute_merkle_root([txA, txB, txC])
        assert root == expected

    def test_proof_single_tx(self) -> None:
        """Proof for single transaction."""
        txid = sha256d(b"test tx")
        proof, root = generate_merkle_proof([txid], 0)
        assert proof == []
        assert root == txid
        assert verify_merkle_proof(txid, root, proof, 0)

    def test_proof_left_position(self) -> None:
        """Proof for left transaction."""
        txA = sha256d(b"txA")
        txB = sha256d(b"txB")

        proof, root = generate_merkle_proof([txA, txB], 0)

        assert len(proof) == 1
        assert proof[0] == txB
        assert verify_merkle_proof(txA, root, proof, 0)

    def test_proof_right_position(self) -> None:
        """Proof for right transaction."""
        txA = sha256d(b"txA")
        txB = sha256d(b"txB")

        proof, root = generate_merkle_proof([txA, txB], 1)

        assert len(proof) == 1
        assert proof[0] == txA
        assert verify_merkle_proof(txB, root, proof, 1)

    def test_proof_invalid(self) -> None:
        """Invalid proof should fail."""
        txA = sha256d(b"txA")
        txB = sha256d(b"txB")
        wrong_root = sha256d(b"wrong")

        proof, _ = generate_merkle_proof([txA, txB], 0)
        assert not verify_merkle_proof(txA, wrong_root, proof, 0)


class TestVarInt:
    """Tests for VarInt parsing."""

    def test_single_byte(self) -> None:
        """Values < 0xFD use single byte."""
        value, offset = parse_varint(b"\x42", 0)
        assert value == 0x42
        assert offset == 1

    def test_two_bytes(self) -> None:
        """0xFD prefix for 2-byte value."""
        # 0xFD followed by 0x0302 (little-endian) = 515
        value, offset = parse_varint(b"\xfd\x03\x02", 0)
        assert value == 515
        assert offset == 3

    def test_four_bytes(self) -> None:
        """0xFE prefix for 4-byte value."""
        value, offset = parse_varint(b"\xfe\x01\x02\x03\x04", 0)
        assert value == 0x04030201
        assert offset == 5


class TestScriptParsing:
    """Tests for scriptPubKey parsing."""

    def test_p2wpkh(self) -> None:
        """P2WPKH script: OP_0 <20 bytes>."""
        script = bytes.fromhex("00141234567890abcdef1234567890abcdef12345678")
        pubkey_hash, script_type = extract_pubkey_hash(script)

        assert script_type == "p2wpkh"
        assert pubkey_hash == bytes.fromhex("1234567890abcdef1234567890abcdef12345678")

    def test_p2pkh(self) -> None:
        """P2PKH script: OP_DUP OP_HASH160 <20 bytes> OP_EQUALVERIFY OP_CHECKSIG."""
        script = bytes.fromhex("76a9141234567890abcdef1234567890abcdef1234567888ac")
        pubkey_hash, script_type = extract_pubkey_hash(script)

        assert script_type == "p2pkh"
        assert pubkey_hash == bytes.fromhex("1234567890abcdef1234567890abcdef12345678")

    def test_unknown_script(self) -> None:
        """Unknown script type."""
        script = bytes.fromhex("deadbeef")
        pubkey_hash, script_type = extract_pubkey_hash(script)

        assert script_type == "unknown"
        assert pubkey_hash is None
