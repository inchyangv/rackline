// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

/// @notice ERC-1271 standard signature validation for contract wallets.
interface IERC1271 {
    function isValidSignature(bytes32 hash, bytes memory signature) external view returns (bytes4 magicValue);
}
