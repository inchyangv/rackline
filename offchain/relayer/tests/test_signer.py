"""
Tests for signer module, particularly txid conversion.

Protocol standard for txid:
- On-chain: internal byte order (sha256d result without reversal)
- Display format (block explorers, APIs): reversed byte order
"""

import pytest
from hashcredit_relayer.signer import txid_to_bytes32, bytes32_to_txid_display


class TestTxidConversion:
    """Tests for txid format conversion."""

    def test_txid_to_bytes32_reverses_bytes(self) -> None:
        """txid_to_bytes32 should reverse bytes for on-chain use."""
        # Display format (what mempool.space API returns)
        display_txid = "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789"

        internal = txid_to_bytes32(display_txid)

        # Should be 32 bytes
        assert len(internal) == 32

        # First byte of internal should be last byte of display
        assert internal[0] == 0x89  # Last byte of display hex
        assert internal[31] == 0xAB  # First byte of display hex

    def test_bytes32_to_txid_display(self) -> None:
        """bytes32_to_txid_display should reverse back to display format."""
        internal = bytes.fromhex(
            "0102030405060708091011121314151617181920212223242526272829303132"
        )

        display = bytes32_to_txid_display(internal)

        assert display == "3231302928272625242322212019181716151413121110090807060504030201"

    def test_round_trip(self) -> None:
        """Converting display -> internal -> display should be identity."""
        original_display = "deadbeef" * 8  # 32 bytes = 64 hex chars

        internal = txid_to_bytes32(original_display)
        back_to_display = bytes32_to_txid_display(internal)

        assert back_to_display == original_display

    def test_handles_0x_prefix(self) -> None:
        """txid_to_bytes32 should handle 0x prefix."""
        display_txid = "0xabcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789"

        internal = txid_to_bytes32(display_txid)

        assert len(internal) == 32
        # Should be same as without prefix
        expected = txid_to_bytes32(display_txid[2:])
        assert internal == expected

    def test_real_bitcoin_txid(self) -> None:
        """Test with a real Bitcoin transaction ID.

        Genesis block coinbase tx:
        Display: 4a5e1e4baab89f3a32518a88c31bc87f618f76673e2cc77ab2127b7afdeda33b
        """
        genesis_txid_display = (
            "4a5e1e4baab89f3a32518a88c31bc87f618f76673e2cc77ab2127b7afdeda33b"
        )

        internal = txid_to_bytes32(genesis_txid_display)

        # Internal format should be reversed
        assert len(internal) == 32
        assert internal[0] == 0x3B  # First byte of internal = last byte of display
        assert internal[31] == 0x4A  # Last byte of internal = first byte of display

        # Round trip
        assert bytes32_to_txid_display(internal) == genesis_txid_display


class TestTxidConsistency:
    """Tests to verify relayer and prover use consistent txid format."""

    def test_same_txid_same_internal_bytes(self) -> None:
        """Same display txid should produce same internal bytes in both modules."""
        # Import prover's conversion function
        from hashcredit_prover.bitcoin import txid_display_to_internal

        display_txid = "abc123def456789012345678901234567890123456789012345678901234abcd"

        relayer_internal = txid_to_bytes32(display_txid)
        prover_internal = txid_display_to_internal(display_txid)

        assert relayer_internal == prover_internal, (
            "Relayer and prover should produce identical internal bytes for same txid"
        )
