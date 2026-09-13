// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import { GpuTypes } from "../types/GpuTypes.sol";

/**
 * @title IAccountRegistry
 * @notice Canonical borrower <-> provider account <-> wallet bindings with change history (GPU-030).
 * @dev A wallet is linked to one borrower at a time; linking uses a `WALLET_LINK` assertion bound to caller,
 *      chain id, this contract, nonce and deadline (AR-07 regression). Copying a proof signature can never attach an
 *      account to another borrower. Registration is not GPU ownership and not E2.
 */
interface IAccountRegistry {
    event AccountLinked(
        bytes32 indexed borrowerId,
        GpuTypes.AccountKey indexed accountKey,
        GpuTypes.ProviderId indexed providerId,
        uint64 at
    );
    event AccountUnlinked(bytes32 indexed borrowerId, GpuTypes.AccountKey indexed accountKey, uint64 at);
    event WalletLinked(bytes32 indexed borrowerId, address indexed wallet, uint64 chainId, uint64 at);
    event WalletReleased(bytes32 indexed borrowerId, address indexed wallet, uint64 at);

    error WalletAlreadyLinked(address wallet, bytes32 borrowerId);
    error AccountAlreadyLinked(GpuTypes.AccountKey accountKey, bytes32 borrowerId);
    error AssertionInvalid(string reason);
    error NotBorrowerWallet(bytes32 borrowerId, address caller);

    function borrowerOfAccount(GpuTypes.AccountKey accountKey) external view returns (bytes32 borrowerId);
    function borrowerOfWallet(address wallet) external view returns (bytes32 borrowerId);
    function isWalletOf(bytes32 borrowerId, address wallet) external view returns (bool);
    /// @notice Which borrower the account belonged to at `at` (for evidence attribution at event time).
    function borrowerOfAccountAt(GpuTypes.AccountKey accountKey, uint64 at) external view returns (bytes32 borrowerId);
}
