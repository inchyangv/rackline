// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * @title MockNoReturnERC20
 * @notice Mock ERC20 that doesn't return bool on transfer/transferFrom/approve
 * @dev Used for testing SafeERC20 compatibility with legacy tokens
 */
contract MockNoReturnERC20 {
    string public name = "No Return Token";
    string public symbol = "NRT";
    uint8 public decimals = 6;

    uint256 public totalSupply;
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    event Transfer(address indexed from, address indexed to, uint256 value);
    event Approval(address indexed owner, address indexed spender, uint256 value);

    function mint(address to, uint256 amount) external {
        totalSupply += amount;
        balanceOf[to] += amount;
        emit Transfer(address(0), to, amount);
    }

    // No return value (reverts on failure)
    function approve(address spender, uint256 amount) external {
        allowance[msg.sender][spender] = amount;
        emit Approval(msg.sender, spender, amount);
    }

    // No return value (reverts on failure)
    function transfer(address to, uint256 amount) external {
        _transfer(msg.sender, to, amount);
    }

    // No return value (reverts on failure)
    function transferFrom(address from, address to, uint256 amount) external {
        uint256 allowed = allowance[from][msg.sender];
        if (allowed != type(uint256).max) {
            require(allowed >= amount, "NRT: insufficient allowance");
            allowance[from][msg.sender] = allowed - amount;
        }
        _transfer(from, to, amount);
    }

    function _transfer(address from, address to, uint256 amount) internal {
        require(balanceOf[from] >= amount, "NRT: insufficient balance");
        balanceOf[from] -= amount;
        balanceOf[to] += amount;
        emit Transfer(from, to, amount);
    }
}
