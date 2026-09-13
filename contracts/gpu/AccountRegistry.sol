// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import { GpuTypes } from "./types/GpuTypes.sol";
import { IAccountRegistry } from "./interfaces/IAccountRegistry.sol";
import { IAuthorizationVerifier } from "./interfaces/IAuthorizationVerifier.sol";
import { IProtocolRoles } from "./interfaces/IProtocolRoles.sol";
import { IProviderRegistry } from "./interfaces/IProviderRegistry.sol";

/**
 * @title AccountRegistry
 * @notice Canonical borrower <-> provider account <-> wallet bindings with change history (GPU-030).
 * @dev  - Wallet link: the wallet signs a `WALLET_LINK` assertion whose subject binds (borrowerId, wallet, chainId,
 *         this registry). The assertion is verified and its nonce consumed by the AuthorizationVerifier, so a copied
 *         signature cannot attach the wallet to another borrower, another chain, or another registry (AR-07).
 *       - One borrower per wallet and per provider account at a time; release before re-link.
 *       - Account links are recorded with `from/to` so evidence can be attributed to the borrower that owned the
 *         account at event time (`borrowerOfAccountAt`).
 *       - Registration here is not GPU ownership and not E2 control; this contract has no notion of grade.
 */
contract AccountRegistry is IAccountRegistry {
    IProtocolRoles public immutable ROLES;
    IAuthorizationVerifier public immutable AUTH;
    IProviderRegistry public immutable PROVIDERS;

    struct AccountLink {
        bytes32 borrowerId;
        uint64 from;
        uint64 to; // 0 = open
    }

    mapping(address wallet => bytes32 borrowerId) private _walletOwner;
    mapping(bytes32 borrowerId => mapping(address wallet => bool)) private _isWallet;
    mapping(GpuTypes.AccountKey => AccountLink[]) private _accountHistory;
    mapping(GpuTypes.AccountKey => GpuTypes.ProviderId) private _accountProvider;

    error NotRegistrar(address caller);
    error ProviderNotRegistered(GpuTypes.ProviderId providerId);
    error AccountNotLinked(GpuTypes.AccountKey accountKey);
    error WalletNotLinked(address wallet);

    constructor(IProtocolRoles roles, IAuthorizationVerifier auth, IProviderRegistry providers) {
        ROLES = roles;
        AUTH = auth;
        PROVIDERS = providers;
    }

    modifier onlyRegistrar() {
        if (!ROLES.hasRole(ROLES.REGISTRAR(), msg.sender)) revert NotRegistrar(msg.sender);
        _;
    }

    // ------------------------------------------------------------------ wallets

    /// @notice Subject the wallet must sign: binds borrower, wallet, chain and this registry.
    function walletLinkSubject(bytes32 borrowerId, address wallet) public view returns (bytes32) {
        return keccak256(abi.encode("WALLET_LINK", borrowerId, wallet, block.chainid, address(this)));
    }

    /**
     * @notice Link `assertion.signer` as a wallet of `borrowerId`. Callable by the registrar (onboarding) or by the
     *         wallet itself. The assertion must be signed by the wallet (EOA or ERC-1271 contract wallet).
     */
    function linkWallet(bytes32 borrowerId, GpuTypes.SupplementaryAssertion calldata assertion) external {
        address wallet = assertion.signer;
        if (msg.sender != wallet && !ROLES.hasRole(ROLES.REGISTRAR(), msg.sender)) revert NotRegistrar(msg.sender);
        bytes32 existing = _walletOwner[wallet];
        if (existing != bytes32(0)) revert WalletAlreadyLinked(wallet, existing);
        // reverts with the verifier's specific error (expired, nonce used, bad signature, wrong subject/purpose)
        AUTH.verifyAndConsume(assertion, GpuTypes.AssertionPurpose.WALLET_LINK, walletLinkSubject(borrowerId, wallet));
        _walletOwner[wallet] = borrowerId;
        _isWallet[borrowerId][wallet] = true;
        emit WalletLinked(borrowerId, wallet, uint64(block.chainid), uint64(block.timestamp));
    }

    /// @notice Release a wallet from its borrower (borrower's own wallet or registrar). Enables a later re-link.
    function releaseWallet(address wallet) external {
        bytes32 borrowerId = _walletOwner[wallet];
        if (borrowerId == bytes32(0)) revert WalletNotLinked(wallet);
        if (msg.sender != wallet && !ROLES.hasRole(ROLES.REGISTRAR(), msg.sender)) revert NotRegistrar(msg.sender);
        delete _walletOwner[wallet];
        delete _isWallet[borrowerId][wallet];
        emit WalletReleased(borrowerId, wallet, uint64(block.timestamp));
    }

    // ------------------------------------------------------------------ provider accounts (REGISTRAR)

    function accountKey(
        GpuTypes.ProviderId providerId,
        string calldata providerSlug,
        string calldata externalAccountId
    ) public pure returns (GpuTypes.AccountKey) {
        // providerId must be keccak256(bytes(providerSlug)); the key namespaces the external id by provider slug.
        require(GpuTypes.ProviderId.unwrap(providerId) == keccak256(bytes(providerSlug)), "slug mismatch");
        return GpuTypes.AccountKey.wrap(keccak256(bytes(string.concat(providerSlug, ":", externalAccountId))));
    }

    function linkAccount(bytes32 borrowerId, GpuTypes.ProviderId providerId, GpuTypes.AccountKey key)
        external
        onlyRegistrar
    {
        if (!_providerExists(providerId)) revert ProviderNotRegistered(providerId);
        AccountLink[] storage hist = _accountHistory[key];
        if (hist.length != 0 && hist[hist.length - 1].to == 0) {
            revert AccountAlreadyLinked(key, hist[hist.length - 1].borrowerId);
        }
        hist.push(AccountLink({ borrowerId: borrowerId, from: uint64(block.timestamp), to: 0 }));
        _accountProvider[key] = providerId;
        emit AccountLinked(borrowerId, key, providerId, uint64(block.timestamp));
    }

    function unlinkAccount(GpuTypes.AccountKey key) external onlyRegistrar {
        AccountLink[] storage hist = _accountHistory[key];
        if (hist.length == 0 || hist[hist.length - 1].to != 0) revert AccountNotLinked(key);
        hist[hist.length - 1].to = uint64(block.timestamp);
        emit AccountUnlinked(hist[hist.length - 1].borrowerId, key, uint64(block.timestamp));
    }

    // ------------------------------------------------------------------ views

    function borrowerOfAccount(GpuTypes.AccountKey key) external view override returns (bytes32) {
        AccountLink[] storage hist = _accountHistory[key];
        if (hist.length == 0 || hist[hist.length - 1].to != 0) return bytes32(0);
        return hist[hist.length - 1].borrowerId;
    }

    function borrowerOfAccountAt(GpuTypes.AccountKey key, uint64 at) external view override returns (bytes32) {
        AccountLink[] storage hist = _accountHistory[key];
        for (uint256 i = hist.length; i > 0; i--) {
            AccountLink storage l = hist[i - 1];
            if (l.from <= at && (l.to == 0 || at < l.to)) return l.borrowerId;
        }
        return bytes32(0);
    }

    function providerOfAccount(GpuTypes.AccountKey key) external view returns (GpuTypes.ProviderId) {
        return _accountProvider[key];
    }

    function accountHistoryLength(GpuTypes.AccountKey key) external view returns (uint256) {
        return _accountHistory[key].length;
    }

    function borrowerOfWallet(address wallet) external view override returns (bytes32) {
        return _walletOwner[wallet];
    }

    function isWalletOf(bytes32 borrowerId, address wallet) external view override returns (bool) {
        return _isWallet[borrowerId][wallet];
    }

    function _providerExists(GpuTypes.ProviderId providerId) internal view returns (bool) {
        (bool ok, bytes memory ret) =
            address(PROVIDERS).staticcall(abi.encodeWithSignature("exists(bytes32)", providerId));
        return ok && ret.length == 32 && abi.decode(ret, (bool));
    }
}
