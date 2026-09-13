// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

/// @notice TEST_ONLY faucet asset with no economic value. The native verifier is NEVER mocked by this token.
contract GpuTestToken {
    string public constant name = "Rackline Test USD (no monetary value)";
    string public constant symbol = "tUSD";
    uint8 public constant decimals = 6;
    bool public constant testOnly = true;
    uint256 public constant FAUCET_AMOUNT = 10_000e6;
    uint256 public totalSupply;
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;
    mapping(address => uint256) public nextClaimAt;
    event Transfer(address indexed from, address indexed to, uint256 amount);
    event Approval(address indexed owner, address indexed spender, uint256 amount);
    error TestnetOnly();
    error FaucetCooldown();
    error InvalidAddress();
    constructor() {
        if (block.chainid != 102_031 && block.chainid != 31_337 && block.chainid != 11_155_111) revert TestnetOnly();
    }
    function faucet() external {
        if (block.timestamp < nextClaimAt[msg.sender]) revert FaucetCooldown();
        nextClaimAt[msg.sender] = block.timestamp + 1 days;
        totalSupply += FAUCET_AMOUNT; balanceOf[msg.sender] += FAUCET_AMOUNT;
        emit Transfer(address(0), msg.sender, FAUCET_AMOUNT);
    }
    function approve(address spender, uint256 amount) external returns (bool) {
        allowance[msg.sender][spender] = amount; emit Approval(msg.sender, spender, amount); return true;
    }
    function transfer(address to, uint256 amount) external returns (bool) {
        _transfer(msg.sender, to, amount); return true;
    }
    function transferFrom(address from, address to, uint256 amount) external returns (bool) {
        if (allowance[from][msg.sender] != type(uint256).max) allowance[from][msg.sender] -= amount;
        _transfer(from, to, amount); return true;
    }
    function _transfer(address from, address to, uint256 amount) internal {
        if (to == address(0)) revert InvalidAddress();
        balanceOf[from] -= amount; balanceOf[to] += amount; emit Transfer(from, to, amount);
    }
}
