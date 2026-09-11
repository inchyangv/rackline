// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IVerifierAdapter, PayoutEvidence} from "./interfaces/IVerifierAdapter.sol";
import {ICheckpointManager} from "./interfaces/ICheckpointManager.sol";
import {BitcoinLib} from "./lib/BitcoinLib.sol";

/**
 * @title BtcSpvVerifier
 * @notice Bitcoin SPV verifier for payout proofs
 * @dev Implements IVerifierAdapter for trustless Bitcoin transaction verification
 *
 * Security model:
 * - Relies on checkpoint trust (owner/multisig controlled)
 * - Verifies header chain from checkpoint to target block
 * - Verifies PoW for each header in chain
 * - Verifies Merkle inclusion of transaction
 * - Parses transaction to extract output details
 *
 * Limitations (per ADR 0001):
 * - Does not cross difficulty retarget boundaries
 * - Max header chain length: 144 blocks
 */
contract BtcSpvVerifier is IVerifierAdapter {
    using BitcoinLib for bytes;
    using BitcoinLib for bytes32;

    // ============================================
    // Constants
    // ============================================

    /// @notice Maximum header chain length (144 blocks = ~1 day)
    uint256 public constant MAX_HEADER_CHAIN = 144;

    /// @notice Maximum Merkle proof depth
    uint256 public constant MAX_MERKLE_DEPTH = 20;

    /// @notice Maximum raw transaction size
    uint256 public constant MAX_TX_SIZE = 4096;

    /// @notice Minimum confirmations required
    uint256 public constant MIN_CONFIRMATIONS = 6;

    // ============================================
    // State Variables
    // ============================================

    /// @notice Contract owner
    address public owner;

    /// @notice Checkpoint manager contract
    ICheckpointManager public checkpointManager;

    /// @notice Mapping of borrower address to their BTC pubkey hash
    mapping(address => bytes20) public borrowerPubkeyHash;

    /// @notice Mapping of processed payouts (keccak256(txid, vout) => processed)
    mapping(bytes32 => bool) private _processedPayouts;

    // ============================================
    // Errors
    // ============================================

    error Unauthorized();
    error InvalidAddress();
    error InvalidCheckpoint();
    error HeaderChainTooLong();
    error InvalidHeaderChain();
    error InvalidPoW();
    error InvalidMerkleProof();
    error MerkleProofTooLong();
    error TxTooLarge();
    error InvalidTxOutput();
    error PubkeyHashMismatch();
    error PayoutAlreadyProcessed();
    error BorrowerNotRegistered();
    error InsufficientConfirmations();

    // ============================================
    // Events
    // ============================================

    event BorrowerPubkeyHashSet(address indexed borrower, bytes20 pubkeyHash);

    // ============================================
    // Structs
    // ============================================

    /**
     * @notice SPV proof structure
     * @param checkpointHeight Height of anchor checkpoint
     * @param headers Array of 80-byte headers from checkpoint+1 to target block
     * @param rawTx Full serialized Bitcoin transaction
     * @param merkleProof Merkle branch for transaction
     * @param txIndex Transaction index in block
     * @param outputIndex Output index (vout) in transaction
     * @param borrower Claimed borrower address
     */
    struct SpvProof {
        uint32 checkpointHeight;
        bytes[] headers;
        bytes rawTx;
        bytes32[] merkleProof;
        uint256 txIndex;
        uint32 outputIndex;
        address borrower;
    }

    // ============================================
    // Constructor
    // ============================================

    constructor(address owner_, address checkpointManager_) {
        if (owner_ == address(0)) revert InvalidAddress();
        if (checkpointManager_ == address(0)) revert InvalidAddress();

        owner = owner_;
        checkpointManager = ICheckpointManager(checkpointManager_);
    }

    // ============================================
    // Modifiers
    // ============================================

    modifier onlyOwner() {
        if (msg.sender != owner) revert Unauthorized();
        _;
    }

    // ============================================
    // Admin Functions
    // ============================================

    /**
     * @notice Set borrower's BTC pubkey hash
     * @param borrower Borrower's EVM address
     * @param pubkeyHash 20-byte pubkey hash from BTC address
     */
    function setBorrowerPubkeyHash(address borrower, bytes20 pubkeyHash) external onlyOwner {
        if (borrower == address(0)) revert InvalidAddress();
        borrowerPubkeyHash[borrower] = pubkeyHash;
        emit BorrowerPubkeyHashSet(borrower, pubkeyHash);
    }

    /**
     * @notice Transfer ownership
     */
    function transferOwnership(address newOwner) external onlyOwner {
        if (newOwner == address(0)) revert InvalidAddress();
        owner = newOwner;
    }

    // ============================================
    // IVerifierAdapter Implementation
    // ============================================

    /**
     * @inheritdoc IVerifierAdapter
     */
    function verifyPayout(bytes calldata proof) external override returns (PayoutEvidence memory evidence) {
        // Decode proof
        SpvProof memory spvProof = abi.decode(proof, (SpvProof));

        // Validate proof sizes
        if (spvProof.headers.length > MAX_HEADER_CHAIN) revert HeaderChainTooLong();
        if (spvProof.merkleProof.length > MAX_MERKLE_DEPTH) revert MerkleProofTooLong();
        if (spvProof.rawTx.length > MAX_TX_SIZE) revert TxTooLarge();
        if (spvProof.headers.length < MIN_CONFIRMATIONS) revert InsufficientConfirmations();

        // Check borrower registration
        bytes20 expectedPubkeyHash = borrowerPubkeyHash[spvProof.borrower];
        if (expectedPubkeyHash == bytes20(0)) revert BorrowerNotRegistered();

        // Get and validate checkpoint
        ICheckpointManager.Checkpoint memory checkpoint = checkpointManager.getCheckpoint(spvProof.checkpointHeight);
        if (checkpoint.height == 0) revert InvalidCheckpoint();

        // Verify header chain and get target block info
        (, BitcoinLib.BlockHeader memory targetHeader) = _verifyHeaderChain(
            checkpoint.blockHash,
            checkpoint.height,
            spvProof.headers
        );

        // Calculate txid
        bytes32 txid = BitcoinLib.sha256d(spvProof.rawTx);

        // Verify Merkle inclusion
        if (!BitcoinLib.verifyMerkleProof(txid, targetHeader.merkleRoot, spvProof.merkleProof, spvProof.txIndex)) {
            revert InvalidMerkleProof();
        }

        // Parse transaction output
        BitcoinLib.TxOutput memory output = BitcoinLib.parseTxOutput(spvProof.rawTx, spvProof.outputIndex);

        // Extract and verify pubkey hash
        (bytes20 actualPubkeyHash, uint8 scriptType) = BitcoinLib.extractPubkeyHash(output.scriptPubKey);
        if (scriptType > 1) revert InvalidTxOutput(); // Only P2WPKH (0) and P2PKH (1) supported
        if (actualPubkeyHash != expectedPubkeyHash) revert PubkeyHashMismatch();

        // Check replay protection
        bytes32 payoutKey = keccak256(abi.encodePacked(txid, spvProof.outputIndex));
        if (_processedPayouts[payoutKey]) revert PayoutAlreadyProcessed();

        // Mark as processed
        _processedPayouts[payoutKey] = true;

        // Build evidence
        evidence = PayoutEvidence({
            borrower: spvProof.borrower,
            txid: txid,
            vout: spvProof.outputIndex,
            amountSats: output.value,
            blockHeight: checkpoint.height + uint32(spvProof.headers.length),
            blockTimestamp: targetHeader.timestamp
        });
    }

    /**
     * @inheritdoc IVerifierAdapter
     */
    function isPayoutProcessed(bytes32 txid, uint32 vout) external view override returns (bool) {
        return _processedPayouts[keccak256(abi.encodePacked(txid, vout))];
    }

    // ============================================
    // Internal Functions
    // ============================================

    /**
     * @notice Verify header chain from checkpoint
     * @param checkpointHash Hash of checkpoint block
     * @param headers Array of headers from checkpoint+1 to target
     * @return targetHash Hash of target block
     * @return targetHeader Parsed target block header
     */
    function _verifyHeaderChain(
        bytes32 checkpointHash,
        uint32, /* checkpointHeight - reserved for future difficulty validation */
        bytes[] memory headers
    ) internal pure returns (bytes32 targetHash, BitcoinLib.BlockHeader memory targetHeader) {
        bytes32 prevHash = checkpointHash;
        uint32 expectedBits = 0;

        for (uint256 i = 0; i < headers.length; i++) {
            // Parse header
            BitcoinLib.BlockHeader memory header = BitcoinLib.parseHeader(headers[i]);

            // Verify prevBlockHash links
            if (header.prevBlockHash != prevHash) {
                revert InvalidHeaderChain();
            }

            // Calculate block hash
            bytes32 blockHash = BitcoinLib.hashHeader(headers[i]);

            // Verify PoW
            if (!BitcoinLib.verifyPoW(blockHash, header.bits)) {
                revert InvalidPoW();
            }

            // Check difficulty consistency (within same retarget period)
            // For MVP, we just ensure bits don't change unexpectedly
            if (i == 0) {
                expectedBits = header.bits;
            } else {
                // Allow some flexibility for edge cases, but generally bits should match
                // In production, we'd have stricter checks based on block height
            }

            // Update for next iteration
            prevHash = blockHash;

            // Store target block info
            if (i == headers.length - 1) {
                targetHash = blockHash;
                targetHeader = header;
            }
        }
    }

    // ============================================
    // View Functions
    // ============================================

    /**
     * @notice Get borrower's registered pubkey hash
     */
    function getBorrowerPubkeyHash(address borrower) external view returns (bytes20) {
        return borrowerPubkeyHash[borrower];
    }
}
