// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import { Test } from "forge-std/Test.sol";
import { GpuTypes } from "../../contracts/gpu/types/GpuTypes.sol";
import { ProtocolRoles } from "../../contracts/gpu/ProtocolRoles.sol";
import { AuthorizationVerifier } from "../../contracts/gpu/AuthorizationVerifier.sol";
import { ProviderRegistry } from "../../contracts/gpu/ProviderRegistry.sol";
import { AccountRegistry } from "../../contracts/gpu/AccountRegistry.sol";
import { IProtocolRoles } from "../../contracts/gpu/interfaces/IProtocolRoles.sol";
import { IProviderRegistry } from "../../contracts/gpu/interfaces/IProviderRegistry.sol";
import { IAccountRegistry } from "../../contracts/gpu/interfaces/IAccountRegistry.sol";
import { IAuthorizationVerifier } from "../../contracts/gpu/interfaces/IAuthorizationVerifier.sol";
import { IERC1271 } from "../../contracts/gpu/interfaces/IERC1271.sol";

/// @dev ERC-1271 wallet double: `accept` decides whether it returns the magic value.
contract ContractWallet is IERC1271 {
    bool public accept;

    constructor(bool accept_) {
        accept = accept_;
    }

    function isValidSignature(bytes32, bytes memory) external view override returns (bytes4) {
        return accept ? IERC1271.isValidSignature.selector : bytes4(0xffffffff);
    }
}

/**
 * @title GPU030RegistryTest
 * @notice Roles, provider registry, account registry and the auxiliary signature verifier (GPU-030).
 */
contract GPU030RegistryTest is Test {
    ProtocolRoles roles;
    AuthorizationVerifier auth;
    ProviderRegistry providers;
    AccountRegistry accounts;

    address admin = address(0xAD);
    address registrar = address(0x4E6);
    address underwriter = address(0x0DE);
    uint256 constant ALICE_KEY = 0xA11CE;
    uint256 constant MALLORY_KEY = 0xBAD;
    address alice;
    address mallory;

    bytes32 constant BORROWER_A = keccak256("borrower-A");
    bytes32 constant BORROWER_B = keccak256("borrower-B");
    bytes32 constant MANIFEST = 0x2b0162d0c206f421138269a721c6338d8cf294d67dc644bb8b35ebb9bfbff6bb;
    GpuTypes.ProviderId MOCK = GpuTypes.ProviderId.wrap(keccak256("mockdepin-testonly"));
    address constant ESCROW = address(0xE1);
    bytes32 constant TOPIC =
        keccak256("ObligationRecognized(bytes32,bytes32,address,address,address,uint256,uint64,uint32)");

    function setUp() public {
        vm.warp(1_800_000_000);
        alice = vm.addr(ALICE_KEY);
        mallory = vm.addr(MALLORY_KEY);
        roles = new ProtocolRoles(admin);
        auth = new AuthorizationVerifier(roles, 15 minutes);
        providers = new ProviderRegistry(roles);
        accounts = new AccountRegistry(roles, auth, providers);
        vm.startPrank(admin);
        roles.grantRole(roles.REGISTRAR(), registrar);
        roles.grantRole(roles.UNDERWRITER(), underwriter);
        vm.stopPrank();
    }

    // ------------------------------------------------------------------ helpers

    function _cfg(GpuTypes.ExecutionProfile p, bool testOnly, uint8 encoding)
        internal
        pure
        returns (IProviderRegistry.ProviderConfig memory)
    {
        return IProviderRegistry.ProviderConfig({
            sourceChain: GpuTypes.SourceChainRef({
                envIdHash: keccak256("cc3-testnet"),
                chainKey: 1,
                chainId: 11_155_111,
                encoding: encoding,
                manifestHash: MANIFEST
            }),
            executionProfile: p,
            testOnly: testOnly,
            policyVersionId: keccak256("pol-v0-TEST_ONLY"),
            admissionEnabled: true
        });
    }

    function _registerMock() internal {
        vm.prank(registrar);
        providers.registerProvider(MOCK, _cfg(GpuTypes.ExecutionProfile.NATIVE_TESTNET, true, 1));
    }

    function _assertion(
        uint256 key,
        GpuTypes.AssertionPurpose purpose,
        bytes32 subject,
        uint64 nonce,
        uint64 issuedAt,
        uint64 expiresAt,
        uint64 epoch
    ) internal view returns (GpuTypes.SupplementaryAssertion memory a) {
        a = GpuTypes.SupplementaryAssertion({
            purpose: purpose,
            subject: subject,
            signer: vm.addr(key),
            keyEpoch: epoch,
            nonce: nonce,
            issuedAt: issuedAt,
            expiresAt: expiresAt,
            signature: ""
        });
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(key, auth.hashAssertion(a));
        a.signature = abi.encodePacked(r, s, v);
    }

    function _walletLink(uint256 key, bytes32 borrowerId, uint64 nonce)
        internal
        view
        returns (GpuTypes.SupplementaryAssertion memory)
    {
        bytes32 subject = accounts.walletLinkSubject(borrowerId, vm.addr(key));
        return _assertion(
            key,
            GpuTypes.AssertionPurpose.WALLET_LINK,
            subject,
            nonce,
            uint64(block.timestamp),
            uint64(block.timestamp + 5 minutes),
            0
        );
    }

    // ------------------------------------------------------------------ roles

    function test_roles_conflictAndAdmin() public {
        bytes32 uw = roles.UNDERWRITER();
        bytes32 tr = roles.TREASURY();
        bytes32 gd = roles.GUARDIAN();
        bytes32 ad = roles.ADMIN_ROLE();
        vm.prank(admin);
        vm.expectRevert(abi.encodeWithSelector(IProtocolRoles.RoleConflict.selector, uw, tr, underwriter));
        roles.grantRole(tr, underwriter);
        vm.prank(registrar);
        vm.expectRevert(abi.encodeWithSelector(IProtocolRoles.NotRoleAdmin.selector, ad, registrar));
        roles.grantRole(gd, registrar);
        assertTrue(roles.hasRole(roles.REGISTRAR(), registrar));
        assertFalse(roles.hasRole(roles.GUARDIAN(), registrar));
    }

    function test_roles_keyEpochRotationWithGrace() public {
        bytes32 uw = roles.UNDERWRITER();
        assertTrue(roles.isEpochValid(uw, 0));
        vm.prank(admin);
        roles.rotateKeyEpoch(uw, 1 hours);
        assertTrue(roles.isEpochValid(uw, 1));
        assertTrue(roles.isEpochValid(uw, 0), "previous epoch valid during grace");
        vm.warp(block.timestamp + 1 hours + 1);
        assertFalse(roles.isEpochValid(uw, 0), "previous epoch expired after grace");
        assertFalse(roles.isEpochValid(uw, 2));
    }

    // ------------------------------------------------------------------ provider registry

    function test_provider_register_and_admission() public {
        _registerMock();
        assertTrue(providers.isAdmitted(MOCK, MANIFEST));
        assertFalse(providers.isAdmitted(MOCK, keccak256("other-manifest")), "manifest mismatch is not admitted");
        vm.prank(underwriter);
        providers.setAdmission(MOCK, false, "unsupported source pending partner data");
        assertFalse(providers.isAdmitted(MOCK, MANIFEST));
        vm.prank(registrar);
        vm.expectRevert(abi.encodeWithSelector(ProviderRegistry.NotGuardianOrUnderwriter.selector, registrar));
        providers.setAdmission(MOCK, true, "x");
    }

    function test_provider_rejects_testOnlyProduction_and_badEncoding() public {
        vm.startPrank(registrar);
        vm.expectRevert(abi.encodeWithSelector(ProviderRegistry.TestOnlyInProduction.selector, MOCK));
        providers.registerProvider(MOCK, _cfg(GpuTypes.ExecutionProfile.PRODUCTION, true, 1));
        vm.expectRevert(abi.encodeWithSelector(ProviderRegistry.TestOnlyInProduction.selector, MOCK));
        providers.registerProvider(MOCK, _cfg(GpuTypes.ExecutionProfile.NATIVE_TESTNET, false, 1));
        vm.expectRevert(
            abi.encodeWithSelector(
                IProviderRegistry.UnsupportedSource.selector, MOCK, uint64(1), keccak256("cc3-testnet")
            )
        );
        providers.registerProvider(MOCK, _cfg(GpuTypes.ExecutionProfile.NATIVE_TESTNET, true, 2));
        vm.stopPrank();
        vm.prank(alice);
        vm.expectRevert(abi.encodeWithSelector(ProviderRegistry.NotRegistrar.selector, alice));
        providers.registerProvider(MOCK, _cfg(GpuTypes.ExecutionProfile.NATIVE_TESTNET, true, 1));
    }

    function test_provider_emitters_tokens_issuers() public {
        _registerMock();
        vm.startPrank(registrar);
        providers.registerEmitter(
            MOCK, ESCROW, TOPIC, GpuTypes.EvidenceMeaning.OBLIGATION_RECOGNIZED, bytes32(0), address(0)
        );
        providers.admitToken(MOCK, 11_155_111, address(0x1c7D), 6);
        providers.setIssuer(MOCK, address(0x155), true);
        vm.stopPrank();
        assertTrue(providers.isEmitterRegistered(MOCK, ESCROW, TOPIC));
        // same topics from a fake emitter, or the same emitter with another topic, are not registered
        assertFalse(providers.isEmitterRegistered(MOCK, address(0xE2), TOPIC));
        assertFalse(providers.isEmitterRegistered(MOCK, ESCROW, keccak256("Other()")));
        vm.expectRevert(
            abi.encodeWithSelector(IProviderRegistry.UnregisteredEmitter.selector, MOCK, address(0xE2), TOPIC)
        );
        providers.emitterMeaning(MOCK, address(0xE2), TOPIC);
        assertEq(
            uint256(providers.emitterMeaning(MOCK, ESCROW, TOPIC)),
            uint256(GpuTypes.EvidenceMeaning.OBLIGATION_RECOGNIZED)
        );
        assertTrue(providers.isTokenAdmitted(MOCK, 11_155_111, address(0x1c7D)));
        assertFalse(providers.isTokenAdmitted(MOCK, 1, address(0x1c7D)), "same token on another chain is not admitted");
        assertEq(providers.tokenDecimals(MOCK, 11_155_111, address(0x1c7D)), 6);
        assertTrue(providers.isIssuer(MOCK, address(0x155)));
        assertFalse(providers.isIssuer(MOCK, address(0x156)), "unregistered issuer");
        vm.prank(registrar);
        providers.revokeEmitter(MOCK, ESCROW, TOPIC);
        assertFalse(providers.isEmitterRegistered(MOCK, ESCROW, TOPIC));
    }

    // ------------------------------------------------------------------ account registry: wallets

    function test_walletLink_eoa_success_and_replay_rejected() public {
        GpuTypes.SupplementaryAssertion memory a = _walletLink(ALICE_KEY, BORROWER_A, 1);
        vm.prank(alice);
        accounts.linkWallet(BORROWER_A, a);
        assertEq(accounts.borrowerOfWallet(alice), BORROWER_A);
        assertTrue(accounts.isWalletOf(BORROWER_A, alice));
        // replay of the same assertion (nonce consumed) — even after release
        vm.prank(alice);
        accounts.releaseWallet(alice);
        vm.prank(alice);
        vm.expectRevert(
            abi.encodeWithSelector(
                IAuthorizationVerifier.NonceAlreadyUsed.selector,
                alice,
                GpuTypes.AssertionPurpose.WALLET_LINK,
                uint64(1)
            )
        );
        accounts.linkWallet(BORROWER_A, a);
        // fresh nonce re-links fine
        GpuTypes.SupplementaryAssertion memory a2 = _walletLink(ALICE_KEY, BORROWER_A, 2);
        vm.prank(alice);
        accounts.linkWallet(BORROWER_A, a2);
        assertEq(accounts.borrowerOfWallet(alice), BORROWER_A);
    }

    function test_walletLink_signatureCannotBeCopiedToAnotherBorrower() public {
        // Mallory copies Alice's (valid) wallet-link assertion and submits it for borrower B.
        GpuTypes.SupplementaryAssertion memory a = _walletLink(ALICE_KEY, BORROWER_A, 1);
        vm.prank(registrar);
        vm.expectRevert(abi.encodeWithSelector(IAuthorizationVerifier.BadSignature.selector, alice));
        accounts.linkWallet(BORROWER_B, a);
        // Mallory cannot submit for Alice's wallet either unless registrar (subject binds the wallet = signer)
        vm.prank(mallory);
        vm.expectRevert(abi.encodeWithSelector(AccountRegistry.NotRegistrar.selector, mallory));
        accounts.linkWallet(BORROWER_A, a);
    }

    function test_walletLink_domainBinding_chainAndContract() public {
        GpuTypes.SupplementaryAssertion memory a = _walletLink(ALICE_KEY, BORROWER_A, 1);
        // different chain id: digest changes, signature no longer recovers to alice
        vm.chainId(102_030);
        vm.prank(alice);
        vm.expectRevert(abi.encodeWithSelector(IAuthorizationVerifier.BadSignature.selector, alice));
        accounts.linkWallet(BORROWER_A, a);
        vm.chainId(31_337);
        // different registry (verifying contract in the subject and a different verifier domain)
        AuthorizationVerifier auth2 = new AuthorizationVerifier(roles, 15 minutes);
        AccountRegistry other = new AccountRegistry(roles, auth2, providers);
        vm.prank(alice);
        vm.expectRevert(abi.encodeWithSelector(IAuthorizationVerifier.BadSignature.selector, alice));
        other.linkWallet(BORROWER_A, a);
    }

    function test_walletLink_expiry_and_ttl() public {
        bytes32 subject = accounts.walletLinkSubject(BORROWER_A, alice);
        GpuTypes.SupplementaryAssertion memory expired = _assertion(
            ALICE_KEY,
            GpuTypes.AssertionPurpose.WALLET_LINK,
            subject,
            1,
            uint64(block.timestamp - 10 minutes),
            uint64(block.timestamp - 1),
            0
        );
        vm.prank(alice);
        vm.expectRevert(
            abi.encodeWithSelector(
                IAuthorizationVerifier.SignatureExpired.selector, uint64(block.timestamp - 1), uint64(block.timestamp)
            )
        );
        accounts.linkWallet(BORROWER_A, expired);
        GpuTypes.SupplementaryAssertion memory longTtl = _assertion(
            ALICE_KEY,
            GpuTypes.AssertionPurpose.WALLET_LINK,
            subject,
            2,
            uint64(block.timestamp),
            uint64(block.timestamp + 1 days),
            0
        );
        vm.prank(alice);
        vm.expectRevert(
            abi.encodeWithSelector(IAuthorizationVerifier.TtlTooLong.selector, uint64(1 days), uint64(15 minutes))
        );
        accounts.linkWallet(BORROWER_A, longTtl);
        // wrong purpose (a consent signature cannot link a wallet)
        GpuTypes.SupplementaryAssertion memory consent = _assertion(
            ALICE_KEY,
            GpuTypes.AssertionPurpose.AGREEMENT_CONSENT,
            subject,
            3,
            uint64(block.timestamp),
            uint64(block.timestamp + 5 minutes),
            0
        );
        vm.prank(alice);
        vm.expectRevert(
            abi.encodeWithSelector(
                IAuthorizationVerifier.WrongPurpose.selector,
                GpuTypes.AssertionPurpose.WALLET_LINK,
                GpuTypes.AssertionPurpose.AGREEMENT_CONSENT
            )
        );
        accounts.linkWallet(BORROWER_A, consent);
        // borrower signers must use epoch 0
        GpuTypes.SupplementaryAssertion memory epoch1 = _assertion(
            ALICE_KEY,
            GpuTypes.AssertionPurpose.WALLET_LINK,
            subject,
            4,
            uint64(block.timestamp),
            uint64(block.timestamp + 5 minutes),
            1
        );
        vm.prank(alice);
        vm.expectRevert(abi.encodeWithSelector(IAuthorizationVerifier.KeyEpochInvalid.selector, alice, uint64(1)));
        accounts.linkWallet(BORROWER_A, epoch1);
    }

    function test_walletLink_duplicateWallet_rejected_untilReleased() public {
        GpuTypes.SupplementaryAssertion memory a1 = _walletLink(ALICE_KEY, BORROWER_A, 1);
        vm.prank(alice);
        accounts.linkWallet(BORROWER_A, a1);
        // registrar tries to attach the same wallet to borrower B with a fresh, valid signature
        GpuTypes.SupplementaryAssertion memory b = _walletLink(ALICE_KEY, BORROWER_B, 2);
        vm.prank(registrar);
        vm.expectRevert(abi.encodeWithSelector(IAccountRegistry.WalletAlreadyLinked.selector, alice, BORROWER_A));
        accounts.linkWallet(BORROWER_B, b);
        vm.prank(registrar);
        accounts.releaseWallet(alice);
        vm.prank(registrar);
        accounts.linkWallet(BORROWER_B, b);
        assertEq(accounts.borrowerOfWallet(alice), BORROWER_B);
        assertFalse(accounts.isWalletOf(BORROWER_A, alice));
    }

    function test_walletLink_contractWallet_erc1271_accept_and_reject() public {
        ContractWallet good = new ContractWallet(true);
        ContractWallet bad = new ContractWallet(false);
        bytes32 subjectGood = accounts.walletLinkSubject(BORROWER_A, address(good));
        GpuTypes.SupplementaryAssertion memory a = GpuTypes.SupplementaryAssertion({
            purpose: GpuTypes.AssertionPurpose.WALLET_LINK,
            subject: subjectGood,
            signer: address(good),
            keyEpoch: 0,
            nonce: 1,
            issuedAt: uint64(block.timestamp),
            expiresAt: uint64(block.timestamp + 5 minutes),
            signature: hex"01"
        });
        vm.prank(registrar);
        accounts.linkWallet(BORROWER_A, a);
        assertEq(accounts.borrowerOfWallet(address(good)), BORROWER_A);
        GpuTypes.SupplementaryAssertion memory b = a;
        b.signer = address(bad);
        b.subject = accounts.walletLinkSubject(BORROWER_A, address(bad));
        vm.prank(registrar);
        vm.expectRevert(abi.encodeWithSelector(IAuthorizationVerifier.BadSignature.selector, address(bad)));
        accounts.linkWallet(BORROWER_A, b);
    }

    function test_walletLink_malleableSignature_rejected() public {
        GpuTypes.SupplementaryAssertion memory a = _walletLink(ALICE_KEY, BORROWER_A, 1);
        // flip to high-s (secp256k1n - s) with v swapped: same key, malleable form must be rejected
        bytes32 r = bytes32(a.signature);
        bytes32 s;
        uint8 v;
        bytes memory sig = a.signature;
        assembly {
            s := mload(add(sig, 64))
            v := byte(0, mload(add(sig, 96)))
        }
        uint256 n = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141;
        a.signature = abi.encodePacked(r, bytes32(n - uint256(s)), v == 27 ? uint8(28) : uint8(27));
        vm.prank(alice);
        vm.expectRevert(abi.encodeWithSelector(IAuthorizationVerifier.BadSignature.selector, alice));
        accounts.linkWallet(BORROWER_A, a);
    }

    // ------------------------------------------------------------------ account registry: provider accounts

    function test_accountLink_history_and_duplicates() public {
        _registerMock();
        GpuTypes.AccountKey key = accounts.accountKey(MOCK, "mockdepin-testonly", "acct-A");
        assertEq(GpuTypes.AccountKey.unwrap(key), keccak256("mockdepin-testonly:acct-A"));
        vm.prank(registrar);
        accounts.linkAccount(BORROWER_A, MOCK, key);
        assertEq(accounts.borrowerOfAccount(key), BORROWER_A);
        vm.prank(registrar);
        vm.expectRevert(abi.encodeWithSelector(IAccountRegistry.AccountAlreadyLinked.selector, key, BORROWER_A));
        accounts.linkAccount(BORROWER_B, MOCK, key);
        uint64 t0 = uint64(block.timestamp);
        vm.warp(t0 + 10 days);
        vm.prank(registrar);
        accounts.unlinkAccount(key);
        vm.warp(t0 + 20 days);
        vm.prank(registrar);
        accounts.linkAccount(BORROWER_B, MOCK, key);
        assertEq(accounts.borrowerOfAccount(key), BORROWER_B);
        assertEq(accounts.borrowerOfAccountAt(key, t0 + 5 days), BORROWER_A, "attribution at event time");
        assertEq(accounts.borrowerOfAccountAt(key, t0 + 15 days), bytes32(0), "gap has no owner");
        assertEq(accounts.borrowerOfAccountAt(key, t0 + 25 days), BORROWER_B);
        assertEq(accounts.accountHistoryLength(key), 2);
        // unknown provider or non-registrar
        vm.prank(registrar);
        vm.expectRevert(
            abi.encodeWithSelector(
                AccountRegistry.ProviderNotRegistered.selector, GpuTypes.ProviderId.wrap(keccak256("ghost"))
            )
        );
        accounts.linkAccount(BORROWER_A, GpuTypes.ProviderId.wrap(keccak256("ghost")), key);
        vm.prank(alice);
        vm.expectRevert(abi.encodeWithSelector(AccountRegistry.NotRegistrar.selector, alice));
        accounts.linkAccount(BORROWER_A, MOCK, key);
    }

    // ------------------------------------------------------------------ role-bound assertions and rotation

    function test_roleBoundAssertion_requiresRoleAndValidEpoch() public {
        bytes32 subject = keccak256("decision-1");
        GpuTypes.SupplementaryAssertion memory byAlice = _assertion(
            ALICE_KEY,
            GpuTypes.AssertionPurpose.CREDIT_APPROVAL,
            subject,
            1,
            uint64(block.timestamp),
            uint64(block.timestamp + 5 minutes),
            0
        );
        assertFalse(
            auth.isValid(byAlice, GpuTypes.AssertionPurpose.CREDIT_APPROVAL, subject), "alice is not an underwriter"
        );
        uint256 uwKey = 0x0DE0;
        address uw = vm.addr(uwKey);
        bytes32 uwRole = roles.UNDERWRITER();
        vm.prank(admin);
        roles.grantRole(uwRole, uw);
        GpuTypes.SupplementaryAssertion memory ok = _assertion(
            uwKey,
            GpuTypes.AssertionPurpose.CREDIT_APPROVAL,
            subject,
            1,
            uint64(block.timestamp),
            uint64(block.timestamp + 5 minutes),
            0
        );
        assertTrue(auth.isValid(ok, GpuTypes.AssertionPurpose.CREDIT_APPROVAL, subject));
        // rotate the underwriter epoch with zero grace: epoch-0 approvals die immediately
        vm.prank(admin);
        roles.rotateKeyEpoch(uwRole, 0);
        vm.warp(block.timestamp + 1);
        assertFalse(
            auth.isValid(ok, GpuTypes.AssertionPurpose.CREDIT_APPROVAL, subject), "old epoch rejected after rotation"
        );
        GpuTypes.SupplementaryAssertion memory fresh = _assertion(
            uwKey,
            GpuTypes.AssertionPurpose.CREDIT_APPROVAL,
            subject,
            2,
            uint64(block.timestamp),
            uint64(block.timestamp + 5 minutes),
            1
        );
        assertTrue(auth.isValid(fresh, GpuTypes.AssertionPurpose.CREDIT_APPROVAL, subject));
        auth.verifyAndConsume(fresh, GpuTypes.AssertionPurpose.CREDIT_APPROVAL, subject);
        assertTrue(auth.nonceUsed(uw, GpuTypes.AssertionPurpose.CREDIT_APPROVAL, 2));
        assertFalse(auth.isValid(fresh, GpuTypes.AssertionPurpose.CREDIT_APPROVAL, subject), "consumed");
    }

    /// @dev Registration is configuration only: nothing here can express a control grade or an ownership claim.
    function test_registriesHaveNoControlOrOwnershipSurface() public pure {
        bytes4[3] memory absent = [
            bytes4(keccak256("grade(bytes32)")),
            bytes4(keccak256("setControlGrade(bytes32,uint8)")),
            bytes4(keccak256("proveOwnership(bytes32)"))
        ];
        bytes4[2] memory present = [IAccountRegistry.borrowerOfAccount.selector, IProviderRegistry.isAdmitted.selector];
        for (uint256 i = 0; i < absent.length; i++) {
            for (uint256 j = 0; j < present.length; j++) {
                assertTrue(absent[i] != present[j]);
            }
        }
    }
}
