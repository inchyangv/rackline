"""
Bitcoin data structures and utilities for SPV proof generation.
"""

import hashlib
from dataclasses import dataclass
from typing import List, Tuple


def sha256d(data: bytes) -> bytes:
    """Double SHA256 hash (Bitcoin standard)."""
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


def reverse_bytes(data: bytes) -> bytes:
    """Reverse byte order (for Bitcoin little-endian display)."""
    return data[::-1]


def bytes_to_hex_le(data: bytes) -> str:
    """Convert bytes to hex string in little-endian display format."""
    return reverse_bytes(data).hex()


def hex_le_to_bytes(hex_str: str) -> bytes:
    """Convert little-endian hex string to bytes."""
    return reverse_bytes(bytes.fromhex(hex_str))


@dataclass
class BlockHeader:
    """Bitcoin block header (80 bytes)."""

    version: int
    prev_block_hash: bytes  # 32 bytes, internal byte order
    merkle_root: bytes  # 32 bytes, internal byte order
    timestamp: int
    bits: int
    nonce: int

    @classmethod
    def from_bytes(cls, data: bytes) -> "BlockHeader":
        """Parse 80-byte header."""
        if len(data) != 80:
            raise ValueError(f"Header must be 80 bytes, got {len(data)}")

        return cls(
            version=int.from_bytes(data[0:4], "little"),
            prev_block_hash=data[4:36],
            merkle_root=data[36:68],
            timestamp=int.from_bytes(data[68:72], "little"),
            bits=int.from_bytes(data[72:76], "little"),
            nonce=int.from_bytes(data[76:80], "little"),
        )

    def to_bytes(self) -> bytes:
        """Serialize to 80 bytes."""
        return (
            self.version.to_bytes(4, "little")
            + self.prev_block_hash
            + self.merkle_root
            + self.timestamp.to_bytes(4, "little")
            + self.bits.to_bytes(4, "little")
            + self.nonce.to_bytes(4, "little")
        )

    def block_hash(self) -> bytes:
        """Calculate block hash (internal byte order)."""
        return sha256d(self.to_bytes())

    def block_hash_hex(self) -> str:
        """Block hash in display format (reversed, hex)."""
        return bytes_to_hex_le(self.block_hash())


@dataclass
class TxOutput:
    """Bitcoin transaction output."""

    value: int  # satoshis
    script_pubkey: bytes


@dataclass
class MerkleProof:
    """Merkle inclusion proof for a transaction."""

    txid: bytes  # 32 bytes, internal byte order
    merkle_root: bytes  # 32 bytes
    proof: List[bytes]  # list of 32-byte sibling hashes
    tx_index: int  # position in block


def compute_merkle_root(txids: List[bytes]) -> bytes:
    """
    Compute Merkle root from list of transaction IDs.
    Bitcoin uses double-SHA256 Merkle trees.
    """
    if not txids:
        raise ValueError("Cannot compute Merkle root of empty list")

    # Work with a copy
    hashes = list(txids)

    while len(hashes) > 1:
        # If odd number, duplicate last hash
        if len(hashes) % 2 == 1:
            hashes.append(hashes[-1])

        # Hash pairs
        new_hashes = []
        for i in range(0, len(hashes), 2):
            new_hashes.append(sha256d(hashes[i] + hashes[i + 1]))
        hashes = new_hashes

    return hashes[0]


def generate_merkle_proof(txids: List[bytes], tx_index: int) -> Tuple[List[bytes], bytes]:
    """
    Generate Merkle proof for transaction at given index.

    Returns:
        (proof, merkle_root) where proof is list of sibling hashes
    """
    if not txids:
        raise ValueError("Cannot generate proof for empty list")
    if tx_index < 0 or tx_index >= len(txids):
        raise ValueError(f"tx_index {tx_index} out of range [0, {len(txids)})")

    proof: List[bytes] = []
    hashes = list(txids)
    index = tx_index

    while len(hashes) > 1:
        # If odd number, duplicate last hash
        if len(hashes) % 2 == 1:
            hashes.append(hashes[-1])

        # Get sibling
        sibling_index = index ^ 1  # XOR to flip last bit
        proof.append(hashes[sibling_index])

        # Compute next level
        new_hashes = []
        for i in range(0, len(hashes), 2):
            new_hashes.append(sha256d(hashes[i] + hashes[i + 1]))
        hashes = new_hashes
        index //= 2

    return proof, hashes[0]


def verify_merkle_proof(
    txid: bytes, merkle_root: bytes, proof: List[bytes], tx_index: int
) -> bool:
    """Verify a Merkle proof."""
    current = txid
    index = tx_index

    for sibling in proof:
        if index & 1 == 0:
            # Current is left
            current = sha256d(current + sibling)
        else:
            # Current is right
            current = sha256d(sibling + current)
        index //= 2

    return current == merkle_root


def parse_varint(data: bytes, offset: int = 0) -> Tuple[int, int]:
    """
    Parse Bitcoin VarInt.
    Returns (value, new_offset).
    """
    first = data[offset]
    if first < 0xFD:
        return first, offset + 1
    elif first == 0xFD:
        return int.from_bytes(data[offset + 1 : offset + 3], "little"), offset + 3
    elif first == 0xFE:
        return int.from_bytes(data[offset + 1 : offset + 5], "little"), offset + 5
    else:
        return int.from_bytes(data[offset + 1 : offset + 9], "little"), offset + 9


def parse_tx_outputs(raw_tx: bytes) -> List[TxOutput]:
    """
    Parse transaction outputs from raw transaction.
    """
    offset = 4  # Skip version

    # Check for witness marker
    if raw_tx[offset] == 0x00 and raw_tx[offset + 1] == 0x01:
        offset += 2  # Skip marker and flag

    # Skip inputs
    input_count, offset = parse_varint(raw_tx, offset)
    for _ in range(input_count):
        offset += 32  # prev txid
        offset += 4  # prev vout
        script_len, offset = parse_varint(raw_tx, offset)
        offset += script_len  # script
        offset += 4  # sequence

    # Parse outputs
    output_count, offset = parse_varint(raw_tx, offset)
    outputs = []

    for _ in range(output_count):
        value = int.from_bytes(raw_tx[offset : offset + 8], "little")
        offset += 8
        script_len, offset = parse_varint(raw_tx, offset)
        script_pubkey = raw_tx[offset : offset + script_len]
        offset += script_len
        outputs.append(TxOutput(value=value, script_pubkey=script_pubkey))

    return outputs


def extract_pubkey_hash(script_pubkey: bytes) -> Tuple[bytes | None, str]:
    """
    Extract pubkey hash from scriptPubKey.

    Returns:
        (pubkey_hash, script_type) where script_type is "p2wpkh", "p2pkh", or "unknown"
    """
    # P2WPKH: OP_0 <20 bytes>
    if len(script_pubkey) == 22 and script_pubkey[0] == 0x00 and script_pubkey[1] == 0x14:
        return script_pubkey[2:22], "p2wpkh"

    # P2PKH: OP_DUP OP_HASH160 <20 bytes> OP_EQUALVERIFY OP_CHECKSIG
    if (
        len(script_pubkey) == 25
        and script_pubkey[0] == 0x76
        and script_pubkey[1] == 0xA9
        and script_pubkey[2] == 0x14
        and script_pubkey[23] == 0x88
        and script_pubkey[24] == 0xAC
    ):
        return script_pubkey[3:23], "p2pkh"

    return None, "unknown"
