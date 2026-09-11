"""
Tests for Bitcoin address decoding.
"""

import pytest
from hashcredit_prover.address import decode_btc_address, bech32_decode, base58check_decode


class TestBech32Decode:
    """Test Bech32 decoding."""

    def test_decode_mainnet_p2wpkh(self) -> None:
        """Test decoding mainnet P2WPKH address."""
        # Example from BIP-173
        address = "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4"
        result = bech32_decode(address)
        assert result is not None
        hrp, data = result
        assert hrp == "bc"
        assert data[0] == 0  # witness version
        assert len(data) == 21  # 1 version + 20 bytes

    def test_decode_testnet_p2wpkh(self) -> None:
        """Test decoding testnet P2WPKH address."""
        # Testnet example
        address = "tb1qw508d6qejxtdg4y5r3zarvary0c5xw7kxpjzsx"
        result = bech32_decode(address)
        assert result is not None
        hrp, data = result
        assert hrp == "tb"
        assert data[0] == 0
        assert len(data) == 21

    def test_decode_invalid_checksum(self) -> None:
        """Test that invalid checksum fails."""
        # Corrupted address
        address = "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t5"  # changed last char
        result = bech32_decode(address)
        assert result is None

    def test_decode_invalid_chars(self) -> None:
        """Test that invalid characters fail."""
        address = "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3ti"  # 'i' is invalid
        result = bech32_decode(address)
        assert result is None


class TestBase58CheckDecode:
    """Test Base58Check decoding."""

    def test_decode_mainnet_p2pkh(self) -> None:
        """Test decoding mainnet P2PKH address."""
        # Example mainnet address
        address = "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2"
        result = base58check_decode(address)
        assert result is not None
        version, payload = result
        assert version == 0x00
        assert len(payload) == 20

    def test_decode_testnet_p2pkh(self) -> None:
        """Test decoding testnet P2PKH address."""
        # Example testnet address
        address = "mipcBbFg9gMiCh81Kj8tqqdgoZub1ZJRfn"
        result = base58check_decode(address)
        assert result is not None
        version, payload = result
        assert version == 0x6F  # testnet
        assert len(payload) == 20

    def test_decode_invalid_checksum(self) -> None:
        """Test that invalid checksum fails."""
        # Corrupted address
        address = "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN3"  # changed last char
        result = base58check_decode(address)
        assert result is None


class TestDecodeBtcAddress:
    """Test high-level address decoding."""

    def test_mainnet_p2wpkh(self) -> None:
        """Test mainnet P2WPKH."""
        address = "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4"
        result = decode_btc_address(address)
        assert result is not None
        pubkey_hash, addr_type = result
        assert addr_type == "p2wpkh"
        assert len(pubkey_hash) == 20

    def test_testnet_p2wpkh(self) -> None:
        """Test testnet P2WPKH."""
        address = "tb1qw508d6qejxtdg4y5r3zarvary0c5xw7kxpjzsx"
        result = decode_btc_address(address)
        assert result is not None
        pubkey_hash, addr_type = result
        assert addr_type == "p2wpkh"
        assert len(pubkey_hash) == 20
        # Known pubkey hash for this address
        assert pubkey_hash.hex() == "751e76e8199196d454941c45d1b3a323f1433bd6"

    def test_mainnet_p2pkh(self) -> None:
        """Test mainnet P2PKH."""
        address = "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2"
        result = decode_btc_address(address)
        assert result is not None
        pubkey_hash, addr_type = result
        assert addr_type == "p2pkh"
        assert len(pubkey_hash) == 20

    def test_testnet_p2pkh(self) -> None:
        """Test testnet P2PKH."""
        address = "mipcBbFg9gMiCh81Kj8tqqdgoZub1ZJRfn"
        result = decode_btc_address(address)
        assert result is not None
        pubkey_hash, addr_type = result
        assert addr_type == "p2pkh"
        assert len(pubkey_hash) == 20

    def test_unsupported_p2sh(self) -> None:
        """Test that P2SH is not supported."""
        # P2SH address (version 0x05 for mainnet)
        address = "3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy"
        result = decode_btc_address(address)
        assert result is None

    def test_invalid_address(self) -> None:
        """Test invalid address."""
        address = "notavalidaddress"
        result = decode_btc_address(address)
        assert result is None

    def test_empty_address(self) -> None:
        """Test empty address."""
        result = decode_btc_address("")
        assert result is None
