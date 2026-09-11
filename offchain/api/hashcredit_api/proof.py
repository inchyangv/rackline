"""
SPV Proof building logic.

Builds proofs for BtcSpvVerifier contract verification.
"""

import hashlib
from dataclasses import dataclass
from typing import Optional

from eth_abi import encode

from .bitcoin import BitcoinRPC, sha256d


def hex_le_to_bytes(hex_str: str) -> bytes:
    """Convert hex string (display format) to bytes (internal format)."""
    return bytes.fromhex(hex_str)[::-1]


@dataclass
class TxOutput:
    """Parsed transaction output."""

    value: int  # Satoshis
    script_pubkey: bytes


@dataclass
class BlockHeader:
    """Parsed Bitcoin block header."""

    version: int
    prev_block_hash: bytes
    merkle_root: bytes
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

    def block_hash(self) -> bytes:
        """Calculate block hash."""
        header_bytes = (
            self.version.to_bytes(4, "little")
            + self.prev_block_hash
            + self.merkle_root
            + self.timestamp.to_bytes(4, "little")
            + self.bits.to_bytes(4, "little")
            + self.nonce.to_bytes(4, "little")
        )
        return sha256d(header_bytes)


def parse_varint(data: bytes, offset: int) -> tuple[int, int]:
    """Parse Bitcoin varint, return (value, bytes_consumed)."""
    first = data[offset]
    if first < 0xFD:
        return first, 1
    elif first == 0xFD:
        return int.from_bytes(data[offset + 1 : offset + 3], "little"), 3
    elif first == 0xFE:
        return int.from_bytes(data[offset + 1 : offset + 5], "little"), 5
    else:
        return int.from_bytes(data[offset + 1 : offset + 9], "little"), 9


def parse_tx_outputs(raw_tx: bytes) -> list[TxOutput]:
    """Parse transaction outputs from raw tx."""
    outputs = []
    offset = 4  # Skip version

    # Check for segwit marker
    is_segwit = raw_tx[offset] == 0x00 and raw_tx[offset + 1] == 0x01
    if is_segwit:
        offset += 2

    # Skip inputs
    input_count, consumed = parse_varint(raw_tx, offset)
    offset += consumed

    for _ in range(input_count):
        offset += 36  # prevout (32 + 4)
        script_len, consumed = parse_varint(raw_tx, offset)
        offset += consumed + script_len + 4  # script + sequence

    # Parse outputs
    output_count, consumed = parse_varint(raw_tx, offset)
    offset += consumed

    for _ in range(output_count):
        value = int.from_bytes(raw_tx[offset : offset + 8], "little")
        offset += 8
        script_len, consumed = parse_varint(raw_tx, offset)
        offset += consumed
        script_pubkey = raw_tx[offset : offset + script_len]
        offset += script_len
        outputs.append(TxOutput(value=value, script_pubkey=script_pubkey))

    return outputs


def extract_pubkey_hash(script_pubkey: bytes) -> tuple[Optional[bytes], str]:
    """
    Extract pubkey hash from script.

    Returns (pubkey_hash, script_type) or (None, "unknown").
    """
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

    # P2WPKH: OP_0 <20 bytes>
    if len(script_pubkey) == 22 and script_pubkey[0] == 0x00 and script_pubkey[1] == 0x14:
        return script_pubkey[2:22], "p2wpkh"

    return None, "unknown"


def generate_merkle_proof(txids: list[bytes], tx_index: int) -> tuple[list[bytes], bytes]:
    """
    Generate Merkle proof for transaction at index.

    Returns (proof, merkle_root).
    """
    if not txids:
        raise ValueError("Empty txid list")

    proof = []
    current_level = list(txids)
    index = tx_index

    while len(current_level) > 1:
        # Duplicate last element if odd count
        if len(current_level) % 2 == 1:
            current_level.append(current_level[-1])

        # Sibling index
        sibling_index = index ^ 1
        if sibling_index < len(current_level):
            proof.append(current_level[sibling_index])

        # Build next level
        next_level = []
        for i in range(0, len(current_level), 2):
            combined = current_level[i] + current_level[i + 1]
            next_level.append(sha256d(combined))

        current_level = next_level
        index //= 2

    return proof, current_level[0]


def verify_merkle_proof(
    txid: bytes,
    merkle_root: bytes,
    proof: list[bytes],
    tx_index: int,
) -> bool:
    """Verify a Merkle proof."""
    current = txid
    index = tx_index

    for sibling in proof:
        if index % 2 == 0:
            current = sha256d(current + sibling)
        else:
            current = sha256d(sibling + current)
        index //= 2

    return current == merkle_root


@dataclass
class SpvProof:
    """SPV proof for on-chain verification."""

    checkpoint_height: int
    headers: list[bytes]
    raw_tx: bytes
    merkle_proof: list[bytes]
    tx_index: int
    output_index: int
    borrower: str

    def encode_for_contract(self) -> bytes:
        """ABI-encode the proof for BtcSpvVerifier."""
        merkle_proof_bytes32 = [p.ljust(32, b"\x00")[:32] for p in self.merkle_proof]

        return encode(
            ["(uint32,bytes[],bytes,bytes32[],uint256,uint32,address)"],
            [
                (
                    self.checkpoint_height,
                    self.headers,
                    self.raw_tx,
                    merkle_proof_bytes32,
                    self.tx_index,
                    self.output_index,
                    self.borrower,
                )
            ],
        )


@dataclass
class ProofBuildResult:
    """Result of proof building."""

    proof: SpvProof
    txid: bytes
    amount_sats: int
    pubkey_hash: bytes
    script_type: str
    block_height: int
    block_timestamp: int


class ProofBuilder:
    """Builds SPV proofs for Bitcoin transactions."""

    def __init__(self, rpc: BitcoinRPC):
        self.rpc = rpc

    async def build_proof(
        self,
        txid: str,
        output_index: int,
        checkpoint_height: int,
        target_height: int,
        borrower: str,
    ) -> ProofBuildResult:
        """Build an SPV proof for the given transaction."""

        # 1. Get raw transaction
        raw_tx_hex = await self.rpc.get_raw_transaction(txid, verbose=False)
        if isinstance(raw_tx_hex, dict):
            raise ValueError("Expected raw hex, got verbose response")
        raw_tx = bytes.fromhex(str(raw_tx_hex))

        # 2. Calculate and verify txid
        txid_internal = sha256d(raw_tx)
        txid_display_check = txid_internal[::-1].hex()
        if txid_display_check != txid.lower():
            raise ValueError(f"TXID mismatch: computed {txid_display_check}, expected {txid}")

        # 3. Parse outputs
        outputs = parse_tx_outputs(raw_tx)
        if output_index >= len(outputs):
            raise ValueError(
                f"Output index {output_index} out of range (tx has {len(outputs)} outputs)"
            )
        output = outputs[output_index]

        # 4. Extract pubkey hash
        pubkey_hash, script_type = extract_pubkey_hash(output.script_pubkey)
        if pubkey_hash is None:
            raise ValueError(f"Unsupported script type: {output.script_pubkey.hex()}")

        # 5. Get header chain
        headers_data = await self.rpc.get_headers_in_range(
            checkpoint_height + 1, target_height
        )
        headers = [bytes.fromhex(h[2]) for h in headers_data]

        # 6. Build Merkle proof
        target_block_hash = await self.rpc.get_block_hash(target_height)
        block_txids = await self.rpc.get_block_txids(target_block_hash)

        try:
            tx_index = block_txids.index(txid)
        except ValueError:
            raise ValueError(f"Transaction {txid} not found in block {target_block_hash}")

        txids_internal = [hex_le_to_bytes(t) for t in block_txids]
        merkle_proof, merkle_root = generate_merkle_proof(txids_internal, tx_index)

        # Verify Merkle root
        target_header = BlockHeader.from_bytes(headers[-1])
        if merkle_root != target_header.merkle_root:
            raise ValueError("Computed Merkle root does not match block header")

        # 7. Build proof
        proof = SpvProof(
            checkpoint_height=checkpoint_height,
            headers=headers,
            raw_tx=raw_tx,
            merkle_proof=merkle_proof,
            tx_index=tx_index,
            output_index=output_index,
            borrower=borrower,
        )

        return ProofBuildResult(
            proof=proof,
            txid=txid_internal,
            amount_sats=output.value,
            pubkey_hash=pubkey_hash,
            script_type=script_type,
            block_height=target_height,
            block_timestamp=target_header.timestamp,
        )
