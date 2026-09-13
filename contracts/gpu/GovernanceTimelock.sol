// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

/// @notice Minimal non-upgradeable governance executor. The governor may be an external multisig. Delay cannot
/// be lowered, operation bytes are committed before execution, and a completed/cancelled salt cannot be replayed.
contract GovernanceTimelock {
    address public immutable GOVERNOR;
    uint64 public immutable DELAY;
    mapping(bytes32 => uint64) public readyAt;
    mapping(bytes32 => bool) public used;
    event Scheduled(bytes32 indexed operationId, address indexed target, uint256 value, bytes data, uint64 readyAt);
    event Cancelled(bytes32 indexed operationId);
    event Executed(bytes32 indexed operationId);
    error NotGovernor();
    error InvalidOperation();
    error NotReady();
    error ExecutionFailed(bytes reason);

    constructor(address governor, uint64 delay_) {
        if (governor == address(0) || delay_ == 0) revert InvalidOperation();
        GOVERNOR = governor;
        DELAY = delay_;
    }
    receive() external payable { }

    function operationId(address target, uint256 value, bytes calldata data, bytes32 salt)
        public
        view
        returns (bytes32)
    {
        return keccak256(abi.encode(block.chainid, address(this), target, value, data, salt));
    }

    function schedule(address target, uint256 value, bytes calldata data, bytes32 salt) external returns (bytes32 id) {
        if (msg.sender != GOVERNOR) revert NotGovernor();
        id = operationId(target, value, data, salt);
        if (target == address(0) || used[id] || readyAt[id] != 0) revert InvalidOperation();
        readyAt[id] = uint64(block.timestamp) + DELAY;
        emit Scheduled(id, target, value, data, readyAt[id]);
    }

    function cancel(bytes32 id) external {
        if (msg.sender != GOVERNOR) revert NotGovernor();
        if (readyAt[id] == 0 || used[id]) revert InvalidOperation();
        used[id] = true;
        emit Cancelled(id);
    }

    function execute(address target, uint256 value, bytes calldata data, bytes32 salt)
        external
        payable
        returns (bytes memory result)
    {
        bytes32 id = operationId(target, value, data, salt);
        if (readyAt[id] == 0 || block.timestamp < readyAt[id] || used[id]) revert NotReady();
        used[id] = true;
        (bool ok, bytes memory returned) = target.call{ value: value }(data);
        if (!ok) revert ExecutionFailed(returned);
        emit Executed(id);
        return returned;
    }
}
