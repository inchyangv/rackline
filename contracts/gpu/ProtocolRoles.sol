// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import { IProtocolRoles } from "./interfaces/IProtocolRoles.sol";

/**
 * @title ProtocolRoles
 * @notice Role registry with per-role key epochs (GPU-030; docs/gpu/permissions-and-states.md §1).
 * @dev `ADMIN_ROLE` is meant to be a timelocked multisig. Separation rule: no account may hold two of
 *      {UNDERWRITER, TREASURY, GUARDIAN}. RELAYER only submits proofs and is never a transition authority
 *      (enforced by consumers; this contract just names the roles).
 *      Self-contained on purpose: OpenZeppelin 5.5 emits Cancun `mcopy`, and this project targets the `london` EVM.
 */
contract ProtocolRoles is IProtocolRoles {
    bytes32 public constant ADMIN_ROLE = keccak256("ADMIN");
    bytes32 private constant _REGISTRAR = keccak256("REGISTRAR");
    bytes32 private constant _UNDERWRITER = keccak256("UNDERWRITER");
    bytes32 private constant _GUARDIAN = keccak256("GUARDIAN");
    bytes32 private constant _TREASURY = keccak256("TREASURY");
    bytes32 private constant _RELAYER = keccak256("RELAYER");
    bytes32 private constant _SERVICER = keccak256("SERVICER");

    struct Epoch {
        uint64 current;
        uint64 previousGraceUntil;
    }

    mapping(bytes32 role => mapping(address account => bool)) private _members;
    mapping(bytes32 role => Epoch) private _epochs;

    error ZeroAddress();

    constructor(address admin) {
        if (admin == address(0)) revert ZeroAddress();
        _members[ADMIN_ROLE][admin] = true;
        emit RoleGranted(ADMIN_ROLE, admin, 0);
    }

    modifier onlyAdmin() {
        if (!_members[ADMIN_ROLE][msg.sender]) revert NotRoleAdmin(ADMIN_ROLE, msg.sender);
        _;
    }

    function REGISTRAR() external pure override returns (bytes32) {
        return _REGISTRAR;
    }

    function UNDERWRITER() external pure override returns (bytes32) {
        return _UNDERWRITER;
    }

    function GUARDIAN() external pure override returns (bytes32) {
        return _GUARDIAN;
    }

    function TREASURY() external pure override returns (bytes32) {
        return _TREASURY;
    }

    function RELAYER() external pure override returns (bytes32) {
        return _RELAYER;
    }

    function SERVICER() external pure override returns (bytes32) {
        return _SERVICER;
    }

    function hasRole(bytes32 role, address account) public view override returns (bool) {
        return _members[role][account];
    }

    function keyEpoch(bytes32 role) external view override returns (uint64 epoch, uint64 graceUntil) {
        Epoch storage e = _epochs[role];
        return (e.current, e.previousGraceUntil);
    }

    /// @notice An epoch is valid if it is current, or the immediately previous one within its grace window.
    function isEpochValid(bytes32 role, uint64 epoch) external view override returns (bool) {
        Epoch storage e = _epochs[role];
        if (epoch == e.current) return true;
        return epoch + 1 == e.current && block.timestamp <= e.previousGraceUntil;
    }

    function grantRole(bytes32 role, address account) external onlyAdmin {
        if (account == address(0)) revert ZeroAddress();
        _checkConflict(role, account);
        if (_members[role][account]) return;
        _members[role][account] = true;
        emit RoleGranted(role, account, _epochs[role].current);
    }

    function revokeRole(bytes32 role, address account) external onlyAdmin {
        if (!_members[role][account]) return;
        _members[role][account] = false;
        emit RoleRevoked(role, account, _epochs[role].current);
    }

    /// @notice Rotate a role's key epoch; the previous epoch stays valid until `graceSeconds` elapse.
    function rotateKeyEpoch(bytes32 role, uint64 graceSeconds) external onlyAdmin {
        Epoch storage e = _epochs[role];
        uint64 old = e.current;
        e.current = old + 1;
        e.previousGraceUntil = uint64(block.timestamp) + graceSeconds;
        emit KeyEpochRotated(role, old, e.current, e.previousGraceUntil);
    }

    function _checkConflict(bytes32 role, address account) internal view {
        if (role == _UNDERWRITER || role == _TREASURY || role == _GUARDIAN) {
            if (role != _UNDERWRITER && _members[_UNDERWRITER][account]) {
                revert RoleConflict(_UNDERWRITER, role, account);
            }
            if (role != _TREASURY && _members[_TREASURY][account]) revert RoleConflict(_TREASURY, role, account);
            if (role != _GUARDIAN && _members[_GUARDIAN][account]) revert RoleConflict(_GUARDIAN, role, account);
        }
    }
}
