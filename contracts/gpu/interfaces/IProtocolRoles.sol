// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import { GpuTypes } from "../types/GpuTypes.sol";

/**
 * @title IProtocolRoles
 * @notice Role registry with key epochs (docs/gpu/permissions-and-states.md §1). Implemented by GPU-030.
 * @dev Role admin is a timelocked multisig. No account may hold two of {UNDERWRITER, TREASURY, GUARDIAN}.
 *      `RELAYER` (oracle keeper) can only submit proofs; it is never a transition authority.
 */
interface IProtocolRoles {
    event RoleGranted(bytes32 indexed role, address indexed account, uint64 epoch);
    event RoleRevoked(bytes32 indexed role, address indexed account, uint64 epoch);
    event KeyEpochRotated(bytes32 indexed role, uint64 oldEpoch, uint64 newEpoch, uint64 graceUntil);

    error RoleConflict(bytes32 roleA, bytes32 roleB, address account);
    error NotRoleAdmin(bytes32 role, address caller);
    error EpochExpired(bytes32 role, uint64 epoch);

    function REGISTRAR() external pure returns (bytes32);
    function UNDERWRITER() external pure returns (bytes32);
    function GUARDIAN() external pure returns (bytes32);
    function TREASURY() external pure returns (bytes32);
    function RELAYER() external pure returns (bytes32);
    function SERVICER() external pure returns (bytes32);

    function hasRole(bytes32 role, address account) external view returns (bool);
    /// @notice Current key epoch of a role; signatures from older epochs are valid only until the grace end.
    function keyEpoch(bytes32 role) external view returns (uint64 epoch, uint64 graceUntil);
    function isEpochValid(bytes32 role, uint64 epoch) external view returns (bool);
}
