"""
SPV Proof Builder for HashCredit.

Builds proofs that can be verified by the BtcSpvVerifier contract.
"""

from dataclasses import dataclass
from typing import Protocol
from eth_abi import encode

from .bitcoin import (
    sha256d,
    hex_le_to_bytes,
    generate_merkle_proof,
    parse_tx_outputs,
    extract_pubkey_hash,
    BlockHeader,
)


class BitcoinRPCProtocol(Protocol):
    """Protocol for Bitcoin RPC client (real or mock)."""

    async def get_block_hash(self, height: int) -> str: ...
    async def get_block_header_hex(self, block_hash: str) -> str: ...
    async def get_block_txids(self, block_hash: str) -> list[str]: ...
    async def get_raw_transaction(self, txid: str, verbose: bool = False) -> str: ...
    async def get_headers_in_range(
        self, start_height: int, end_height: int
    ) -> list[tuple[int, str, str]]: ...


@dataclass
class SpvProof:
    """
    SPV proof for on-chain verification.

    Matches the SpvProof struct in BtcSpvVerifier.sol:
    - checkpointHeight: uint32
    - headers: bytes[] (80 bytes each, from checkpoint+1 to tip)
    - txBlockIndex: uint32 (index within headers[] where tx is included)
    - rawTx: bytes
    - merkleProof: bytes32[]
    - txIndex: uint256 (position in block's tx list)
    - outputIndex: uint32
    - borrower: address

    Confirmations are calculated as: headers.length - txBlockIndex
    """

    checkpoint_height: int
    headers: list[bytes]  # List of 80-byte headers
    tx_block_index: int  # Index within headers where tx is included (0-based)
    raw_tx: bytes
    merkle_proof: list[bytes]  # List of 32-byte hashes
    tx_index: int
    output_index: int
    borrower: str  # EVM address (0x...)

    def encode_for_contract(self) -> bytes:
        """
        ABI-encode the proof for submission to BtcSpvVerifier.verifyPayout().

        The contract expects:
        struct SpvProof {
            uint32 checkpointHeight;
            bytes[] headers;
            uint32 txBlockIndex;
            bytes rawTx;
            bytes32[] merkleProof;
            uint256 txIndex;
            uint32 outputIndex;
            address borrower;
        }
        """
        # Convert merkle proof to bytes32 array
        merkle_proof_bytes32 = [bytes.ljust(p, b"\x00")[:32] for p in self.merkle_proof]

        # Encode as tuple
        return encode(
            ["(uint32,bytes[],uint32,bytes,bytes32[],uint256,uint32,address)"],
            [
                (
                    self.checkpoint_height,
                    self.headers,
                    self.tx_block_index,
                    self.raw_tx,
                    merkle_proof_bytes32,
                    self.tx_index,
                    self.output_index,
                    self.borrower,
                )
            ],
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "checkpointHeight": self.checkpoint_height,
            "headers": [h.hex() for h in self.headers],
            "txBlockIndex": self.tx_block_index,
            "rawTx": self.raw_tx.hex(),
            "merkleProof": [p.hex() for p in self.merkle_proof],
            "txIndex": self.tx_index,
            "outputIndex": self.output_index,
            "borrower": self.borrower,
        }


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
    """
    Builds SPV proofs for Bitcoin transactions.

    Usage:
        rpc = BitcoinRPC(config)
        builder = ProofBuilder(rpc)
        result = await builder.build_proof(
            txid="abc123...",
            output_index=0,
            checkpoint_height=800000,
            target_height=800006,  # Block where tx is confirmed
            borrower="0x1234...",
            tip_height=800012,  # Optional, defaults to target_height + 5 for 6 confirmations
        )
        encoded = result.proof.encode_for_contract()
    """

    MIN_CONFIRMATIONS = 6

    def __init__(self, rpc: BitcoinRPCProtocol):
        self.rpc = rpc

    async def build_proof(
        self,
        txid: str,  # Transaction ID (display format, reversed hex)
        output_index: int,  # Which output is the payout
        checkpoint_height: int,  # Height of anchor checkpoint
        target_height: int,  # Height of block containing transaction
        borrower: str,  # Borrower's EVM address
        tip_height: int | None = None,  # Height of tip block (defaults to target_height + MIN_CONFIRMATIONS - 1)
    ) -> ProofBuildResult:
        """
        Build an SPV proof for the given transaction.

        Args:
            txid: Transaction ID in display format (reversed hex, as shown in block explorers)
            output_index: Index of the output to prove
            checkpoint_height: Block height of the checkpoint anchor
            target_height: Block height where the transaction is confirmed
            borrower: Borrower's EVM address (checksummed)
            tip_height: Block height of the tip (defaults to target_height + MIN_CONFIRMATIONS - 1)

        Returns:
            ProofBuildResult containing the proof and extracted transaction data

        Note:
            Confirmations = tip_height - target_height + 1
            The proof includes headers from checkpoint+1 to tip_height.
            txBlockIndex = target_height - checkpoint_height - 1 (0-based index in headers)
        """
        # Default tip_height to provide MIN_CONFIRMATIONS
        if tip_height is None:
            tip_height = target_height + self.MIN_CONFIRMATIONS - 1

        # Validate heights
        if target_height <= checkpoint_height:
            raise ValueError(
                f"target_height ({target_height}) must be > checkpoint_height ({checkpoint_height})"
            )
        if tip_height < target_height:
            raise ValueError(
                f"tip_height ({tip_height}) must be >= target_height ({target_height})"
            )

        # Calculate confirmations and txBlockIndex
        confirmations = tip_height - target_height + 1
        if confirmations < self.MIN_CONFIRMATIONS:
            raise ValueError(
                f"Insufficient confirmations: {confirmations} < {self.MIN_CONFIRMATIONS}"
            )

        tx_block_index = target_height - checkpoint_height - 1  # 0-based index in headers

        # 1. Get raw transaction
        raw_tx_hex = await self.rpc.get_raw_transaction(txid, verbose=False)
        if isinstance(raw_tx_hex, dict):
            raise ValueError("Expected raw hex, got verbose response")
        raw_tx = bytes.fromhex(raw_tx_hex)

        # 2. Calculate txid (internal byte order)
        txid_internal = sha256d(raw_tx)
        # Note: Display format txid is reversed
        txid_display_check = txid_internal[::-1].hex()
        if txid_display_check != txid.lower():
            raise ValueError(f"TXID mismatch: computed {txid_display_check}, expected {txid}")

        # 3. Parse transaction outputs
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

        # 5. Get header chain from checkpoint+1 to tip
        headers_data = await self.rpc.get_headers_in_range(
            checkpoint_height + 1, tip_height
        )
        headers = [bytes.fromhex(h[2]) for h in headers_data]

        # 6. Get target block (where tx is included) and build Merkle proof
        target_block_hash = await self.rpc.get_block_hash(target_height)
        block_txids = await self.rpc.get_block_txids(target_block_hash)

        # Find transaction index in block
        try:
            tx_index = block_txids.index(txid)
        except ValueError:
            raise ValueError(f"Transaction {txid} not found in block {target_block_hash}")

        # Convert txids to internal byte order for Merkle proof
        txids_internal = [hex_le_to_bytes(t) for t in block_txids]

        # Generate Merkle proof
        merkle_proof, merkle_root = generate_merkle_proof(txids_internal, tx_index)

        # Verify against tx block header's Merkle root (not tip)
        tx_block_header = BlockHeader.from_bytes(headers[tx_block_index])
        if merkle_root != tx_block_header.merkle_root:
            raise ValueError("Computed Merkle root does not match block header")

        # 7. Build proof structure
        proof = SpvProof(
            checkpoint_height=checkpoint_height,
            headers=headers,
            tx_block_index=tx_block_index,
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
            block_timestamp=tx_block_header.timestamp,
        )

    async def verify_proof_locally(self, result: ProofBuildResult) -> bool:
        """
        Verify a proof locally before submission.
        Checks all the same conditions as the on-chain verifier.
        """
        from .bitcoin import verify_merkle_proof, BlockHeader

        # 1. Verify header chain
        if not result.proof.headers:
            return False

        # Verify txBlockIndex is within bounds
        if result.proof.tx_block_index >= len(result.proof.headers):
            return False

        # Verify confirmations
        confirmations = len(result.proof.headers) - result.proof.tx_block_index
        if confirmations < self.MIN_CONFIRMATIONS:
            return False

        # Parse and verify each header
        prev_hash = None
        for i, header_bytes in enumerate(result.proof.headers):
            header = BlockHeader.from_bytes(header_bytes)

            if i > 0 and header.prev_block_hash != prev_hash:
                return False

            # Note: We skip PoW verification here as it's expensive
            # The on-chain verifier will do this

            prev_hash = header.block_hash()

        # 2. Verify Merkle proof using the tx block header (not the tip)
        tx_block_header = BlockHeader.from_bytes(result.proof.headers[result.proof.tx_block_index])
        txid = sha256d(result.proof.raw_tx)

        if not verify_merkle_proof(
            txid,
            tx_block_header.merkle_root,
            result.proof.merkle_proof,
            result.proof.tx_index,
        ):
            return False

        return True
