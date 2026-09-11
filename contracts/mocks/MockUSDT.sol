// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * @title MockUSDT
 * @notice Mock ERC20 that requires approve(0) before setting new allowance (USDT-style)
 * @dev Used for testing SafeERC20 forceApprove compatibility
 */
contract MockUSDT {
    string public name = "Tether USD";
    string public symbol = "USDT";
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

    function approve(address spender, uint256 amount) external returns (bool) {
        // USDT-style: require current allowance to be 0 or new amount to be 0
        require(amount == 0 || allowance[msg.sender][spender] == 0, "USDT: approve from non-zero to non-zero allowance");
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
            require(allowed >= amount, "USDT: insufficient allowance");
            allowance[from][msg.sender] = allowed - amount;
        }
        return _transfer(from, to, amount);
    }

    function _transfer(address from, address to, uint256 amount) internal returns (bool) {
        require(balanceOf[from] >= amount, "USDT: insufficient balance");
        balanceOf[from] -= amount;
        balanceOf[to] += amount;
        emit Transfer(from, to, amount);
        return true;
    }
}
