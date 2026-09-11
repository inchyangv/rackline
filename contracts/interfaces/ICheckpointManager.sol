// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * @title ICheckpointManager
 * @notice Interface for managing Bitcoin block checkpoints
 * @dev Checkpoints are trusted anchors for SPV verification.
 *      They are set by authorized attestors (owner/multisig).
 */
interface ICheckpointManager {
    /**
     * @notice Bitcoin block checkpoint data
     * @param blockHash The 32-byte block hash (little-endian, as in Bitcoin)
     * @param height The block height
     * @param chainWork Cumulative chain work (optional, for fork resistance)
     * @param timestamp Block timestamp (seconds since epoch)
     * @param bits Difficulty target in compact format (for difficulty validation)
     */
    struct Checkpoint {
        bytes32 blockHash;
        uint32 height;
        uint256 chainWork;
        uint32 timestamp;
        uint32 bits;
    }

    /**
     * @notice Emitted when a new checkpoint is set
     * @param height The checkpoint block height
     * @param blockHash The checkpoint block hash
     * @param chainWork Cumulative chain work
     * @param timestamp Block timestamp
     * @param bits Difficulty target in compact format
     */
    event CheckpointSet(
        uint32 indexed height, bytes32 indexed blockHash, uint256 chainWork, uint32 timestamp, uint32 bits
    );

    /**
     * @notice Set a new checkpoint
     * @param height Block height (must be greater than current latest)
     * @param blockHash Block hash (32 bytes, little-endian)
     * @param chainWork Cumulative chain work
     * @param timestamp Block timestamp
     * @param bits Difficulty target in compact format
     * @dev Only callable by authorized attestors (owner/multisig)
     *      Height must be monotonically increasing
     */
    function setCheckpoint(uint32 height, bytes32 blockHash, uint256 chainWork, uint32 timestamp, uint32 bits) external;

    /**
     * @notice Get checkpoint by height
     * @param height The block height to query
     * @return checkpoint The checkpoint data (zero values if not set)
     */
    function getCheckpoint(uint32 height) external view returns (Checkpoint memory checkpoint);

    /**
     * @notice Check if a checkpoint exists and matches the given hash
     * @param height Block height
     * @param blockHash Expected block hash
     * @return True if checkpoint exists and hash matches
     */
    function isValidCheckpoint(uint32 height, bytes32 blockHash) external view returns (bool);

    /**
     * @notice Get the latest checkpoint height
     * @return The height of the most recent checkpoint (0 if none)
     */
    function latestCheckpointHeight() external view returns (uint32);

    /**
     * @notice Get the latest checkpoint
     * @return The most recent checkpoint data
     */
    function latestCheckpoint() external view returns (Checkpoint memory);
}
