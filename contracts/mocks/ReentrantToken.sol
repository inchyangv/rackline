// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import { IERC20 } from "@openzeppelin/contracts/token/ERC20/IERC20.sol";

/**
 * @title ReentrantToken
 * @notice Mock ERC20 with transfer hooks for reentrancy testing
 * @dev Simulates ERC777-style callbacks to test reentrancy guards
 */
contract ReentrantToken {
    string public name = "Reentrant Token";
    string public symbol = "RENT";
    uint8 public decimals = 6;

    uint256 public totalSupply;
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    // Callback settings
    address public callbackTarget;
    bytes public callbackData;
    bool public callbackEnabled;

    event Transfer(address indexed from, address indexed to, uint256 value);
    event Approval(address indexed owner, address indexed spender, uint256 value);

    function mint(address to, uint256 amount) external {
        totalSupply += amount;
        balanceOf[to] += amount;
        emit Transfer(address(0), to, amount);
    }

    /// @notice Set up a callback to be invoked during transfers
    function setCallback(address target, bytes calldata data) external {
        callbackTarget = target;
        callbackData = data;
        callbackEnabled = true;
    }

    function clearCallback() external {
        callbackEnabled = false;
    }

    function approve(address spender, uint256 amount) external returns (bool) {
        allowance[msg.sender][spender] = amount;
        emit Approval(msg.sender, spender, amount);
        return true;
    }

    function transfer(address to, uint256 amount) external returns (bool) {
        return _transfer(msg.sender, to, amount);
    }

    function transferFrom(address from, address to, uint256 amount) external returns (bool) {
        uint256 allowed = allowance[from][msg.sender];
        if (allowed != type(uint256).max) {
            require(allowed >= amount, "RENT: insufficient allowance");
            allowance[from][msg.sender] = allowed - amount;
        }
        return _transfer(from, to, amount);
    }

    function _transfer(address from, address to, uint256 amount) internal returns (bool) {
        require(balanceOf[from] >= amount, "RENT: insufficient balance");
        balanceOf[from] -= amount;
        balanceOf[to] += amount;
        emit Transfer(from, to, amount);

        // ERC777-style callback after transfer
        if (callbackEnabled && callbackTarget != address(0)) {
            (bool success,) = callbackTarget.call(callbackData);
            // Ignore callback result for testing
        }

        return true;
    }
}

/**
 * @title ReentrantAttacker
 * @notice Contract that attempts reentrancy attacks
 */
contract ReentrantAttacker {
    address public target;
    bytes public attackData;
    uint256 public attackCount;
    uint256 public maxAttacks;

    constructor(address target_) {
        target = target_;
    }

    function setAttack(bytes calldata data, uint256 maxAttempts) external {
        attackData = data;
        maxAttacks = maxAttempts;
        attackCount = 0;
    }

    // Called by ReentrantToken during transfer
    fallback() external {
        if (attackCount < maxAttacks) {
            attackCount++;
            (bool success,) = target.call(attackData);
            // Don't check success - we expect it to fail with reentrancy guard
        }
    }

    receive() external payable { }
}
