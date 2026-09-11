// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * @title IPoolRegistry
 * @notice Interface for mining pool registry
 * @dev Manages allowlist of eligible payout sources to prevent self-transfer attacks
 *
 * MVP: Simple allowlist, returns true for all in permissive mode
 * Production: Can integrate with pool cluster detection and heuristics
 */
interface IPoolRegistry {
    // ============================================
    // Events
    // ============================================

    /// @notice Emitted when a pool is added to the registry
    event PoolAdded(bytes32 indexed poolId, string name);

    /// @notice Emitted when a pool is removed from the registry
    event PoolRemoved(bytes32 indexed poolId);

    /// @notice Emitted when permissive mode is toggled
    event PermissiveModeChanged(bool enabled);

    // ============================================
    // Errors
    // ============================================

    /// @notice Pool already registered
    error PoolAlreadyRegistered();

    /// @notice Pool not found
    error PoolNotFound();

    // ============================================
    // Functions
    // ============================================

    /**
     * @notice Check if a payout source is eligible for credit
     * @param sourceIdentifier Identifier of the payout source (e.g., hash of input UTXOs)
     * @return True if eligible
     * @dev In MVP/permissive mode, may return true for all
     *      In production, checks against registered pools
     */
    function isEligiblePayoutSource(bytes32 sourceIdentifier) external view returns (bool);

    /**
     * @notice Add a pool to the registry
     * @param poolId Unique identifier for the pool
     * @param name Human-readable pool name
     */
    function addPool(bytes32 poolId, string calldata name) external;

    /**
     * @notice Remove a pool from the registry
     * @param poolId Pool identifier to remove
     */
    function removePool(bytes32 poolId) external;

    /**
     * @notice Set permissive mode (MVP: allow all sources)
     * @param enabled True to enable permissive mode
     */
    function setPermissiveMode(bool enabled) external;

    /**
     * @notice Check if permissive mode is enabled
     */
    function isPermissiveMode() external view returns (bool);
}
