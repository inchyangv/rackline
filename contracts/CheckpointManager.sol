// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ICheckpointManager} from "./interfaces/ICheckpointManager.sol";

/**
 * @title CheckpointManager
 * @notice Manages Bitcoin block checkpoints for SPV verification
 * @dev Checkpoints are trusted anchors set by owner (can be multisig).
 *      Used by BtcSpvVerifier to validate header chains.
 *
 * Security assumptions:
 * - Owner is trusted to submit valid Bitcoin block hashes
 * - Checkpoints should be sufficiently deep (100+ confirmations)
 * - Production deployment should use multisig as owner
 */
contract CheckpointManager is ICheckpointManager {
    /// @notice Contract owner
    address public owner;

    /// @notice Mapping from block height to checkpoint data
    mapping(uint32 => Checkpoint) private _checkpoints;

    /// @notice The height of the latest checkpoint
    uint32 private _latestHeight;

    /// @notice Error when caller is not owner
    error Unauthorized();

    /// @notice Error when height is not greater than latest
    error HeightMustIncrease(uint32 provided, uint32 latest);

    /// @notice Error when block hash is zero
    error InvalidBlockHash();

    /// @notice Error when timestamp is zero
    error InvalidTimestamp();

    /// @notice Error when checkpoint does not exist
    error CheckpointNotFound(uint32 height);

    /// @notice Error when address is invalid
    error InvalidAddress();

    /// @notice Emitted when ownership is transferred
    event OwnershipTransferred(address indexed previousOwner, address indexed newOwner);

    /**
     * @notice Only owner modifier
     */
    modifier onlyOwner() {
        if (msg.sender != owner) revert Unauthorized();
        _;
    }

    /**
     * @notice Constructor
     * @param owner_ The initial owner (should be multisig for production)
     */
    constructor(address owner_) {
        if (owner_ == address(0)) revert InvalidAddress();
        owner = owner_;
    }

    /**
     * @notice Transfer ownership
     * @param newOwner New owner address
     */
    function transferOwnership(address newOwner) external onlyOwner {
        if (newOwner == address(0)) revert InvalidAddress();
        address oldOwner = owner;
        owner = newOwner;
        emit OwnershipTransferred(oldOwner, newOwner);
    }

    /// @notice Error when bits is zero
    error InvalidBits();

    /**
     * @inheritdoc ICheckpointManager
     */
    function setCheckpoint(
        uint32 height,
        bytes32 blockHash,
        uint256 chainWork,
        uint32 timestamp,
        uint32 bits
    ) external onlyOwner {
        // Validate inputs
        if (blockHash == bytes32(0)) {
            revert InvalidBlockHash();
        }
        if (timestamp == 0) {
            revert InvalidTimestamp();
        }
        if (bits == 0) {
            revert InvalidBits();
        }

        // Enforce monotonic height increase
        if (height <= _latestHeight) {
            revert HeightMustIncrease(height, _latestHeight);
        }

        // Store checkpoint
        _checkpoints[height] = Checkpoint({
            blockHash: blockHash,
            height: height,
            chainWork: chainWork,
            timestamp: timestamp,
            bits: bits
        });

        // Update latest height
        _latestHeight = height;

        emit CheckpointSet(height, blockHash, chainWork, timestamp, bits);
    }

    /**
     * @inheritdoc ICheckpointManager
     */
    function getCheckpoint(uint32 height) external view returns (Checkpoint memory) {
        return _checkpoints[height];
    }

    /**
     * @inheritdoc ICheckpointManager
     */
    function isValidCheckpoint(uint32 height, bytes32 blockHash) external view returns (bool) {
        Checkpoint storage cp = _checkpoints[height];
        return cp.height == height && cp.blockHash == blockHash;
    }

    /**
     * @inheritdoc ICheckpointManager
     */
    function latestCheckpointHeight() external view returns (uint32) {
        return _latestHeight;
    }

    /**
     * @inheritdoc ICheckpointManager
     */
    function latestCheckpoint() external view returns (Checkpoint memory) {
        if (_latestHeight == 0) {
            revert CheckpointNotFound(0);
        }
        return _checkpoints[_latestHeight];
    }
}
