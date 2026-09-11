"""
Tests for HashCredit API endpoints.
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch, MagicMock

from hashcredit_api.main import app
from hashcredit_api.config import Settings


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def mock_settings():
    """Create mock settings."""
    return Settings(
        host="127.0.0.1",
        port=8000,
        bitcoin_rpc_url="http://localhost:18332",
        evm_rpc_url="http://localhost:8545",
        chain_id=102031,
    )


class TestHealthCheck:
    """Tests for /health endpoint."""

    def test_health_check_returns_status(self, client):
        """Health check should return status."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "version" in data
        assert "bitcoin_rpc" in data
        assert "evm_rpc" in data


class TestAddressDecoding:
    """Tests for address decoding utilities."""

    def test_decode_bech32_address(self):
        """Should decode bech32 P2WPKH address."""
        from hashcredit_api.address import decode_btc_address

        # Valid testnet bech32 address
        addr = "tb1qw508d6qejxtdg4y5r3zarvary0c5xw7kxpjzsx"
        result = decode_btc_address(addr)
        assert result is not None
        pubkey_hash, addr_type = result
        assert addr_type == "p2wpkh"
        assert len(pubkey_hash) == 20
        # Expected hash for this address
        expected = bytes.fromhex("751e76e8199196d454941c45d1b3a323f1433bd6")
        assert pubkey_hash == expected

    def test_decode_p2pkh_address(self):
        """Should decode base58 P2PKH address."""
        from hashcredit_api.address import decode_btc_address

        # Valid mainnet P2PKH address
        addr = "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2"
        result = decode_btc_address(addr)
        assert result is not None
        pubkey_hash, addr_type = result
        assert addr_type == "p2pkh"
        assert len(pubkey_hash) == 20

    def test_decode_invalid_address(self):
        """Should return None for invalid address."""
        from hashcredit_api.address import decode_btc_address

        result = decode_btc_address("invalid_address")
        assert result is None


class TestProofBuilding:
    """Tests for proof building logic."""

    def test_parse_varint(self):
        """Should parse Bitcoin varints correctly."""
        from hashcredit_api.proof import parse_varint

        # Single byte
        data = bytes([0x05, 0x00])
        val, consumed = parse_varint(data, 0)
        assert val == 5
        assert consumed == 1

        # 0xFD prefix (2 bytes)
        data = bytes([0xFD, 0x00, 0x01])
        val, consumed = parse_varint(data, 0)
        assert val == 256
        assert consumed == 3

    def test_sha256d(self):
        """Should compute double SHA256."""
        from hashcredit_api.bitcoin import sha256d

        data = b"test"
        result = sha256d(data)
        assert len(result) == 32
        # Known hash
        expected = bytes.fromhex(
            "954d5a49fd70d9b8bcdb35d252267829957f7ef7fa6c74f88419bdc5e82209f4"
        )
        assert result == expected

    def test_merkle_proof_generation(self):
        """Should generate valid Merkle proof."""
        from hashcredit_api.proof import generate_merkle_proof, verify_merkle_proof

        # Simple test with 4 txids
        txids = [
            bytes([i] * 32) for i in range(4)
        ]

        proof, root = generate_merkle_proof(txids, 1)
        assert len(proof) == 2  # log2(4) = 2 levels

        # Verify the proof
        assert verify_merkle_proof(txids[1], root, proof, 1)

        # Wrong index should fail
        assert not verify_merkle_proof(txids[1], root, proof, 0)

    def test_spv_proof_encoding(self):
        """Should encode proof for contract."""
        from hashcredit_api.proof import SpvProof

        proof = SpvProof(
            checkpoint_height=2500000,
            headers=[bytes(80)],
            raw_tx=bytes(100),
            merkle_proof=[bytes(32)],
            tx_index=0,
            output_index=0,
            borrower="0x1234567890123456789012345678901234567890",
        )

        encoded = proof.encode_for_contract()
        assert isinstance(encoded, bytes)
        assert len(encoded) > 0


class TestModels:
    """Tests for Pydantic models."""

    def test_build_proof_request_validation(self):
        """Should validate BuildProofRequest."""
        from hashcredit_api.models import BuildProofRequest

        # Valid request
        req = BuildProofRequest(
            txid="abc123",
            output_index=0,
            checkpoint_height=2500000,
            target_height=2500006,
            borrower="0x1234567890123456789012345678901234567890",
        )
        assert req.output_index == 0

        # Invalid output_index
        with pytest.raises(ValueError):
            BuildProofRequest(
                txid="abc123",
                output_index=-1,
                checkpoint_height=2500000,
                target_height=2500006,
                borrower="0x1234",
            )

    def test_set_checkpoint_request_validation(self):
        """Should validate SetCheckpointRequest."""
        from hashcredit_api.models import SetCheckpointRequest

        req = SetCheckpointRequest(height=2500000, dry_run=True)
        assert req.height == 2500000
        assert req.dry_run is True


class TestAuth:
    """Tests for authentication."""

    def test_local_request_without_token(self, client):
        """Local requests should work without token."""
        response = client.get("/health")
        assert response.status_code == 200


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
