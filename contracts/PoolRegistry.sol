// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import { IPoolRegistry } from "./interfaces/IPoolRegistry.sol";

/**
 * @title PoolRegistry
 * @notice Registry for eligible mining pool payout sources
 * @dev MVP implementation with permissive mode for hackathon
 *
 * In permissive mode (default for MVP), all sources are considered eligible.
 * In strict mode, only registered pools are eligible.
 */
contract PoolRegistry is IPoolRegistry {
    // ============================================
    // State Variables
    // ============================================

    /// @notice Owner address
    address public owner;

    /// @notice Whether permissive mode is enabled (allow all sources)
    bool public override isPermissiveMode;

    /// @notice Mapping of pool ID to whether it's registered
    mapping(bytes32 => bool) public registeredPools;

    /// @notice Mapping of pool ID to name
    mapping(bytes32 => string) public poolNames;

    // ============================================
    // Constructor
    // ============================================

    constructor(bool permissiveMode_) {
        owner = msg.sender;
        isPermissiveMode = permissiveMode_;

        if (permissiveMode_) {
            emit PermissiveModeChanged(true);
        }
    }

    // ============================================
    // Modifiers
    // ============================================

    modifier onlyOwner() {
        require(msg.sender == owner, "PoolRegistry: not owner");
        _;
    }

    // ============================================
    // Admin Functions
    // ============================================

    /**
     * @inheritdoc IPoolRegistry
     */
    function addPool(bytes32 poolId, string calldata name) external override onlyOwner {
        if (registeredPools[poolId]) revert PoolAlreadyRegistered();

        registeredPools[poolId] = true;
        poolNames[poolId] = name;

        emit PoolAdded(poolId, name);
    }

    /**
     * @inheritdoc IPoolRegistry
     */
    function removePool(bytes32 poolId) external override onlyOwner {
        if (!registeredPools[poolId]) revert PoolNotFound();

        delete registeredPools[poolId];
        delete poolNames[poolId];

        emit PoolRemoved(poolId);
    }

    /**
     * @inheritdoc IPoolRegistry
     */
    function setPermissiveMode(bool enabled) external override onlyOwner {
        isPermissiveMode = enabled;
        emit PermissiveModeChanged(enabled);
    }

    /**
     * @notice Transfer ownership
     * @param newOwner New owner address
     */
    function transferOwnership(address newOwner) external onlyOwner {
        require(newOwner != address(0), "PoolRegistry: zero address");
        owner = newOwner;
    }

    // ============================================
    // View Functions
    // ============================================

    /**
     * @inheritdoc IPoolRegistry
     */
    function isEligiblePayoutSource(bytes32 sourceIdentifier) external view override returns (bool) {
        // In permissive mode, all sources are eligible
        if (isPermissiveMode) {
            return true;
        }

        // Otherwise, check if source is a registered pool
        return registeredPools[sourceIdentifier];
    }
}
