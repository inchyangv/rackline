// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import { Test } from "forge-std/Test.sol";
import { GpuTypes } from "../../contracts/gpu/types/GpuTypes.sol";
import { ProtocolRoles } from "../../contracts/gpu/ProtocolRoles.sol";
import { AuthorizationVerifier } from "../../contracts/gpu/AuthorizationVerifier.sol";
import { ProviderRegistry } from "../../contracts/gpu/ProviderRegistry.sol";
import { AccountRegistry } from "../../contracts/gpu/AccountRegistry.sol";
import { ControlRegistry } from "../../contracts/gpu/ControlRegistry.sol";
import { IProviderRegistry } from "../../contracts/gpu/interfaces/IProviderRegistry.sol";
import { IControlRegistry } from "../../contracts/gpu/interfaces/IControlRegistry.sol";
import { IDebtLedger } from "../../contracts/gpu/interfaces/IDebtLedger.sol";

/// @dev TEST_ONLY authoritative-debt double: only `legalDebtAt` is consulted by the registry.
contract DebtStub {
    mapping(bytes32 => uint256) public debt;

    function set(GpuTypes.FacilityId f, uint256 d) external {
        debt[GpuTypes.FacilityId.unwrap(f)] = d;
    }

    function legalDebtAt(GpuTypes.FacilityId f, uint64) external view returns (uint256) {
        return debt[GpuTypes.FacilityId.unwrap(f)];
    }
}

/**
 * @title GPU032ControlTest
 * @notice Control agreement registry: versions, grades, observations, revocation, two-role release (GPU-032).
 *         Registry entries are configuration; E2 reality is SANDBOX/LIVE evidence of GPU-009/056, not this suite.
 */
contract GPU032ControlTest is Test {
    ProtocolRoles roles;
    AuthorizationVerifier auth;
    ProviderRegistry providers;
    AccountRegistry accounts;
    DebtStub debt;
    ControlRegistry control;

    address admin = address(0xAD);
    address registrar = address(0x4E6);
    address underwriter = address(0x0DE);
    address guardian = address(0x6A);
    address servicer = address(0x5E);
    address treasury = address(0x7E);
    address keeper = address(0x0E1);
    address mallory = address(0xBAD);

    bytes32 constant BORROWER_A = keccak256("borrower-A");
    bytes32 constant BORROWER_B = keccak256("borrower-B");
    bytes32 constant AGR = keccak256("agreement-A-1");
    bytes32 constant HASH_V1 = keccak256("agreement-text-v1");
    bytes32 constant HASH_V2 = keccak256("agreement-text-v2");
    bytes32 constant POC = keccak256("gpu-009-poc-PASS-ref");
    bytes32 constant MANIFEST = 0x2b0162d0c206f421138269a721c6338d8cf294d67dc644bb8b35ebb9bfbff6bb;
    GpuTypes.ProviderId MOCK = GpuTypes.ProviderId.wrap(keccak256("mockdepin-testonly"));
    GpuTypes.AccountKey ACCT = GpuTypes.AccountKey.wrap(keccak256("mockdepin-testonly:acct-A"));
    GpuTypes.AccountKey ACCT_B = GpuTypes.AccountKey.wrap(keccak256("mockdepin-testonly:acct-B"));
    GpuTypes.FacilityId FAC = GpuTypes.FacilityId.wrap(keccak256("facility-A"));
    address constant RECEIVER = address(0xE5C);
    address constant OTHER_RECEIVER = address(0xE5D);
    uint64 constant MAX_AGE = 6 hours;
    uint64 T0 = 1_800_000_000;

    function setUp() public {
        vm.warp(T0);
        roles = new ProtocolRoles(admin);
        auth = new AuthorizationVerifier(roles, 15 minutes);
        providers = new ProviderRegistry(roles);
        accounts = new AccountRegistry(roles, auth, providers);
        debt = new DebtStub();
        control = new ControlRegistry(roles, accounts, IDebtLedger(address(debt)), MAX_AGE);

        vm.startPrank(admin);
        roles.grantRole(roles.REGISTRAR(), registrar);
        roles.grantRole(roles.UNDERWRITER(), underwriter);
        roles.grantRole(roles.GUARDIAN(), guardian);
        roles.grantRole(roles.SERVICER(), servicer);
        roles.grantRole(roles.TREASURY(), treasury);
        roles.grantRole(roles.RELAYER(), keeper);
        vm.stopPrank();

        vm.startPrank(registrar);
        providers.registerProvider(
            MOCK,
            IProviderRegistry.ProviderConfig({
                sourceChain: GpuTypes.SourceChainRef({
                    envIdHash: keccak256("cc3-testnet"),
                    chainKey: 1,
                    chainId: 11_155_111,
                    encoding: 1,
                    manifestHash: MANIFEST
                }),
                executionProfile: GpuTypes.ExecutionProfile.LOCAL_MOCK,
                testOnly: true,
                policyVersionId: keccak256("policy-v1"),
                admissionEnabled: true
            })
        );
        accounts.linkAccount(BORROWER_A, MOCK, ACCT);
        accounts.linkAccount(BORROWER_B, MOCK, ACCT_B);
        vm.stopPrank();
    }

    // ------------------------------------------------------------------ helpers

    function _createE1() internal {
        vm.prank(registrar);
        control.createAgreement(
            AGR, BORROWER_A, ACCT, GpuTypes.ControlGrade.E1, RECEIVER, 11_155_111, HASH_V1, T0, 0, bytes32(0)
        );
    }

    function _createE2() internal {
        vm.prank(underwriter);
        control.createAgreement(
            AGR, BORROWER_A, ACCT, GpuTypes.ControlGrade.E2, RECEIVER, 11_155_111, HASH_V1, T0, T0 + 365 days, POC
        );
    }

    function _observeOk() internal {
        vm.prank(servicer);
        control.observe(AGR, GpuTypes.ControlGrade.E2, RECEIVER);
    }

    function _bumpE2(address receiver, bytes32 h) internal {
        vm.prank(underwriter);
        control.bumpVersion(AGR, GpuTypes.ControlGrade.E2, receiver, 11_155_111, h, uint64(block.timestamp), 0, POC);
    }

    function _approveRelease(uint32 version, uint64 closesAt, bool refund) internal {
        vm.prank(servicer);
        control.approveRelease(
            AGR,
            ControlRegistry.ReleaseTerms({ version: version, reconciliationClosesAt: closesAt, refundPending: refund })
        );
    }

    // ------------------------------------------------------------------ creation / grade authority

    function test_accountLink_neverPromotesGrade_registrarCannotCreateE2() public {
        // the account is linked (AccountRegistry) but that gives E1 at most from the registrar
        vm.expectRevert(
            abi.encodeWithSelector(ControlRegistry.GradeNotAllowedForRole.selector, GpuTypes.ControlGrade.E2, registrar)
        );
        vm.prank(registrar);
        control.createAgreement(
            AGR, BORROWER_A, ACCT, GpuTypes.ControlGrade.E2, RECEIVER, 11_155_111, HASH_V1, T0, 0, POC
        );
        _createE1();
        assertEq(uint8(control.agreement(AGR).grade), uint8(GpuTypes.ControlGrade.E1));
        assertEq(uint8(control.effectiveGrade(AGR)), uint8(GpuTypes.ControlGrade.E1));
    }

    function test_e2RequiresPocRef_evenForUnderwriter() public {
        vm.expectRevert(abi.encodeWithSelector(IControlRegistry.E2RequiresPoc.selector, AGR));
        vm.prank(underwriter);
        control.createAgreement(
            AGR, BORROWER_A, ACCT, GpuTypes.ControlGrade.E2, RECEIVER, 11_155_111, HASH_V1, T0, 0, bytes32(0)
        );
        _createE2();
        IControlRegistry.Agreement memory a = control.agreement(AGR);
        assertEq(a.version, 1);
        assertEq(a.pocRef, POC);
        assertEq(uint8(a.grade), uint8(GpuTypes.ControlGrade.E2));
    }

    function test_create_requiresAccountOwnedByBorrower_andUniqueId() public {
        vm.expectRevert(abi.encodeWithSelector(ControlRegistry.AccountNotOwnedByBorrower.selector, ACCT_B, BORROWER_A));
        vm.prank(registrar);
        control.createAgreement(
            AGR, BORROWER_A, ACCT_B, GpuTypes.ControlGrade.E1, RECEIVER, 11_155_111, HASH_V1, T0, 0, bytes32(0)
        );
        _createE1();
        vm.expectRevert(abi.encodeWithSelector(ControlRegistry.AgreementExists.selector, AGR));
        vm.prank(registrar);
        control.createAgreement(
            AGR, BORROWER_B, ACCT_B, GpuTypes.ControlGrade.E1, RECEIVER, 11_155_111, HASH_V1, T0, 0, bytes32(0)
        );
    }

    function test_roleChecks_everyMutation() public {
        _createE2();
        vm.startPrank(mallory);
        vm.expectRevert(
            abi.encodeWithSelector(ControlRegistry.GradeNotAllowedForRole.selector, GpuTypes.ControlGrade.E1, mallory)
        );
        control.bumpVersion(AGR, GpuTypes.ControlGrade.E1, RECEIVER, 11_155_111, HASH_V2, T0, 0, bytes32(0));
        vm.expectRevert(abi.encodeWithSelector(ControlRegistry.NotRole.selector, roles.SERVICER(), mallory));
        control.observe(AGR, GpuTypes.ControlGrade.E2, RECEIVER);
        vm.expectRevert(abi.encodeWithSelector(ControlRegistry.NotRole.selector, roles.GUARDIAN(), mallory));
        control.revoke(AGR, "x");
        vm.expectRevert(abi.encodeWithSelector(ControlRegistry.NotRole.selector, roles.SERVICER(), mallory));
        control.approveRelease(AGR, ControlRegistry.ReleaseTerms(1, uint64(block.timestamp), false));
        vm.expectRevert(abi.encodeWithSelector(ControlRegistry.NotRole.selector, roles.TREASURY(), mallory));
        control.release(AGR, 1);
        vm.expectRevert(abi.encodeWithSelector(ControlRegistry.NotRole.selector, roles.UNDERWRITER(), mallory));
        control.bindFacility(AGR, FAC);
        vm.stopPrank();
        // the keeper (RELAYER) may observe but never version / receiver-change / release
        vm.startPrank(keeper);
        control.observe(AGR, GpuTypes.ControlGrade.E2, RECEIVER);
        vm.expectRevert(
            abi.encodeWithSelector(ControlRegistry.GradeNotAllowedForRole.selector, GpuTypes.ControlGrade.E2, keeper)
        );
        control.bumpVersion(AGR, GpuTypes.ControlGrade.E2, OTHER_RECEIVER, 11_155_111, HASH_V2, T0, 0, POC);
        vm.stopPrank();
    }

    // ------------------------------------------------------------------ effectiveness / freshness

    function test_effective_requiresCurrentVersionWindowAndFreshObservation() public {
        _createE2();
        assertTrue(control.isEffective(AGR, 1, T0));
        assertFalse(control.isEffective(AGR, 0, T0));
        assertFalse(control.isEffective(AGR, 2, T0));
        assertFalse(control.isEffective(AGR, 1, T0 - 1), "before effectiveFrom");
        assertFalse(control.isEffective(AGR, 1, T0 + 365 days), "at effectiveTo");
        assertFalse(control.isEffective(keccak256("nope"), 1, T0));
        // never observed => not fresh => draw-time check refuses even though effective
        assertFalse(control.isFresh(AGR, MAX_AGE));
        vm.expectRevert(abi.encodeWithSelector(IControlRegistry.ObservationStale.selector, uint64(0), MAX_AGE));
        control.requireUsable(AGR, 1, GpuTypes.ControlGrade.E2);
        _observeOk();
        assertTrue(control.isFresh(AGR, MAX_AGE));
        control.requireUsable(AGR, 1, GpuTypes.ControlGrade.E2);
        // stale after max age
        vm.warp(T0 + MAX_AGE + 1);
        assertFalse(control.isFresh(AGR, MAX_AGE));
        vm.expectRevert(abi.encodeWithSelector(IControlRegistry.ObservationStale.selector, T0, MAX_AGE));
        control.requireUsable(AGR, 1, GpuTypes.ControlGrade.E2);
    }

    function test_expiry_makesAgreementIneffective() public {
        _createE2();
        _observeOk();
        vm.warp(T0 + 365 days);
        assertFalse(control.isEffective(AGR, 1, uint64(block.timestamp)));
        assertEq(uint8(control.effectiveGrade(AGR)), uint8(GpuTypes.ControlGrade.E0));
        vm.expectRevert(abi.encodeWithSelector(IControlRegistry.AgreementNotEffective.selector, AGR, uint32(1)));
        control.requireUsable(AGR, 1, GpuTypes.ControlGrade.E2);
    }

    function test_gradeInsufficient_forE1Agreement() public {
        _createE1();
        vm.prank(servicer);
        control.observe(AGR, GpuTypes.ControlGrade.E1, RECEIVER);
        control.requireUsable(AGR, 1, GpuTypes.ControlGrade.E1);
        vm.expectRevert(
            abi.encodeWithSelector(
                IControlRegistry.GradeInsufficient.selector, GpuTypes.ControlGrade.E2, GpuTypes.ControlGrade.E1
            )
        );
        control.requireUsable(AGR, 1, GpuTypes.ControlGrade.E2);
    }

    // ------------------------------------------------------------------ observations

    function test_observation_cannotUpgrade_butDowngradeFreezes() public {
        _createE1();
        vm.expectRevert(
            abi.encodeWithSelector(
                ControlRegistry.ObservationCannotUpgrade.selector, GpuTypes.ControlGrade.E1, GpuTypes.ControlGrade.E2
            )
        );
        vm.prank(servicer);
        control.observe(AGR, GpuTypes.ControlGrade.E2, RECEIVER);

        // E2 agreement: an observation of E1 (support override / lock lost) makes it ineffective, no auto-default
        vm.prank(underwriter);
        control.bumpVersion(AGR, GpuTypes.ControlGrade.E2, RECEIVER, 11_155_111, HASH_V2, T0, 0, POC);
        _observeOk();
        assertTrue(control.isEffective(AGR, 2, T0));
        vm.prank(keeper);
        control.observe(AGR, GpuTypes.ControlGrade.E1, RECEIVER);
        assertFalse(control.isEffective(AGR, 2, T0));
        assertEq(uint8(control.agreement(AGR).grade), uint8(GpuTypes.ControlGrade.E2), "agreement text unchanged");
        // a later confirming observation restores effectiveness (cause cleared)
        _observeOk();
        assertTrue(control.isEffective(AGR, 2, T0));
    }

    function test_observedReceiverChange_upstream_freezes() public {
        _createE2();
        _observeOk();
        vm.prank(servicer);
        control.observe(AGR, GpuTypes.ControlGrade.E2, OTHER_RECEIVER);
        assertFalse(control.isEffective(AGR, 1, T0), "receiver changed upstream => not effective");
        assertTrue(control.isFresh(AGR, MAX_AGE), "fresh, but contradicting");
        vm.expectRevert(abi.encodeWithSelector(IControlRegistry.AgreementNotEffective.selector, AGR, uint32(1)));
        control.requireUsable(AGR, 1, GpuTypes.ControlGrade.E2);
    }

    // ------------------------------------------------------------------ versions / receiver change race

    function test_versionBump_invalidatesOldVersion_andRequiresNewObservation() public {
        _createE2();
        _observeOk();
        assertTrue(control.isEffective(AGR, 1, T0));
        _bumpE2(OTHER_RECEIVER, HASH_V2);
        IControlRegistry.Agreement memory a = control.agreement(AGR);
        assertEq(a.version, 2);
        assertEq(a.receiver, OTHER_RECEIVER);
        // a draw that still references version 1 is refused (draw <-> version-change race)
        assertFalse(control.isEffective(AGR, 1, T0));
        assertTrue(control.isEffective(AGR, 2, T0));
        // the old observation vouched for the old receiver: freshness resets
        assertFalse(control.isFresh(AGR, MAX_AGE));
        assertEq(a.lastObservedAt, 0);
        vm.prank(servicer);
        control.observe(AGR, GpuTypes.ControlGrade.E2, OTHER_RECEIVER);
        control.requireUsable(AGR, 2, GpuTypes.ControlGrade.E2);
    }

    function test_unauthorizedReceiverChange_rejected_registrarCannotKeepE2() public {
        _createE2();
        // registrar may only produce an E0/E1 version: a receiver change that keeps E2 needs the underwriter + PoC
        vm.expectRevert(
            abi.encodeWithSelector(ControlRegistry.GradeNotAllowedForRole.selector, GpuTypes.ControlGrade.E2, registrar)
        );
        vm.prank(registrar);
        control.bumpVersion(AGR, GpuTypes.ControlGrade.E2, OTHER_RECEIVER, 11_155_111, HASH_V2, T0, 0, POC);
        vm.expectRevert(abi.encodeWithSelector(IControlRegistry.E2RequiresPoc.selector, AGR));
        vm.prank(underwriter);
        control.bumpVersion(AGR, GpuTypes.ControlGrade.E2, OTHER_RECEIVER, 11_155_111, HASH_V2, T0, 0, bytes32(0));
        // servicer / borrower-like callers cannot change the receiver at all
        vm.expectRevert(
            abi.encodeWithSelector(ControlRegistry.GradeNotAllowedForRole.selector, GpuTypes.ControlGrade.E1, servicer)
        );
        vm.prank(servicer);
        control.bumpVersion(AGR, GpuTypes.ControlGrade.E1, OTHER_RECEIVER, 11_155_111, HASH_V2, T0, 0, bytes32(0));
        assertEq(control.agreement(AGR).receiver, RECEIVER);
    }

    function test_badWindow_andZeroFields_rejected() public {
        vm.expectRevert(abi.encodeWithSelector(ControlRegistry.BadEffectiveWindow.selector, T0, T0));
        vm.prank(registrar);
        control.createAgreement(
            AGR, BORROWER_A, ACCT, GpuTypes.ControlGrade.E1, RECEIVER, 11_155_111, HASH_V1, T0, T0, bytes32(0)
        );
        vm.expectRevert(ControlRegistry.ZeroAddress.selector);
        vm.prank(registrar);
        control.createAgreement(
            AGR, BORROWER_A, ACCT, GpuTypes.ControlGrade.E1, address(0), 11_155_111, HASH_V1, T0, 0, bytes32(0)
        );
    }

    // ------------------------------------------------------------------ revocation

    function test_revoke_failsClosed_dropsToE1_untilReattested() public {
        _createE2();
        _observeOk();
        vm.prank(guardian);
        control.revoke(AGR, "support override observed");
        assertFalse(control.isEffective(AGR, 1, T0));
        assertFalse(control.isFresh(AGR, MAX_AGE));
        assertEq(uint8(control.agreement(AGR).grade), uint8(GpuTypes.ControlGrade.E1));
        assertEq(uint8(control.effectiveGrade(AGR)), uint8(GpuTypes.ControlGrade.E0));
        // a confirming observation alone cannot lift a revocation
        vm.prank(servicer);
        control.observe(AGR, GpuTypes.ControlGrade.E1, RECEIVER);
        assertFalse(control.isEffective(AGR, 1, T0));
        // only a new version (underwriter + PoC for E2) continues the agreement
        _bumpE2(RECEIVER, HASH_V2);
        _observeOk();
        assertTrue(control.isEffective(AGR, 2, T0));
        assertFalse(control.isEffective(AGR, 1, T0), "old version stays dead");
    }

    // ------------------------------------------------------------------ release

    function test_release_twoRoles_debtZero_windowClosed_noRefund() public {
        _createE2();
        _observeOk();
        vm.prank(underwriter);
        control.bindFacility(AGR, FAC);
        debt.set(FAC, 1000e6);
        _approveRelease(1, T0 + 7 days, false);

        vm.prank(treasury);
        vm.expectRevert(abi.encodeWithSelector(IControlRegistry.ReleaseBlocked.selector, "reconciliation window open"));
        control.release(AGR, 1);

        vm.warp(T0 + 7 days);
        vm.prank(treasury);
        vm.expectRevert(abi.encodeWithSelector(IControlRegistry.ReleaseBlocked.selector, "debt outstanding"));
        control.release(AGR, 1);

        debt.set(FAC, 0);
        vm.prank(treasury);
        vm.expectEmit(true, false, false, true, address(control));
        emit IControlRegistry.ControlReleased(AGR, uint64(block.timestamp));
        control.release(AGR, 1);
        assertFalse(control.isEffective(AGR, 1, uint64(block.timestamp)));
        assertEq(control.agreement(AGR).effectiveTo, uint64(block.timestamp));
        // terminal: no new versions, no re-observation, no second release, id not reusable
        vm.expectRevert(abi.encodeWithSelector(ControlRegistry.AgreementTerminal.selector, AGR));
        _bumpE2(RECEIVER, HASH_V2);
        vm.expectRevert(abi.encodeWithSelector(ControlRegistry.AgreementTerminal.selector, AGR));
        vm.prank(servicer);
        control.observe(AGR, GpuTypes.ControlGrade.E2, RECEIVER);
        vm.expectRevert(abi.encodeWithSelector(ControlRegistry.AgreementTerminal.selector, AGR));
        vm.prank(treasury);
        control.release(AGR, 1);
        vm.expectRevert(abi.encodeWithSelector(ControlRegistry.AgreementExists.selector, AGR));
        vm.prank(registrar);
        control.createAgreement(
            AGR, BORROWER_B, ACCT_B, GpuTypes.ControlGrade.E1, RECEIVER, 11_155_111, HASH_V1, T0, 0, bytes32(0)
        );
    }

    function test_release_blockedByPendingRefund_afterDebtZero() public {
        _createE2();
        vm.prank(underwriter);
        control.bindFacility(AGR, FAC);
        debt.set(FAC, 0);
        _approveRelease(1, T0, true);
        vm.prank(treasury);
        vm.expectRevert(abi.encodeWithSelector(IControlRegistry.ReleaseBlocked.selector, "refund pending"));
        control.release(AGR, 1);
        // servicer clears the refund after settlement
        _approveRelease(1, T0, false);
        vm.prank(treasury);
        control.release(AGR, 1);
    }

    function test_release_requiresServicerApprovalForCurrentVersion_oldProofRejected() public {
        _createE2();
        vm.prank(underwriter);
        control.bindFacility(AGR, FAC);
        debt.set(FAC, 0);
        // no approval at all
        vm.prank(treasury);
        vm.expectRevert(
            abi.encodeWithSelector(IControlRegistry.ReleaseBlocked.selector, "servicer approval missing or stale")
        );
        control.release(AGR, 1);
        // approval for version 1, then a version bump: the old approval must not release version 2
        _approveRelease(1, T0, false);
        _bumpE2(OTHER_RECEIVER, HASH_V2);
        vm.prank(treasury);
        vm.expectRevert(abi.encodeWithSelector(IControlRegistry.AgreementNotEffective.selector, AGR, uint32(1)));
        control.release(AGR, 1);
        vm.prank(treasury);
        vm.expectRevert(
            abi.encodeWithSelector(IControlRegistry.ReleaseBlocked.selector, "servicer approval missing or stale")
        );
        control.release(AGR, 2);
        // servicer cannot approve a non-current version either
        vm.prank(servicer);
        vm.expectRevert(abi.encodeWithSelector(IControlRegistry.AgreementNotEffective.selector, AGR, uint32(1)));
        control.approveRelease(AGR, ControlRegistry.ReleaseTerms(1, T0, false));
        // revocation also wipes a standing approval
        _approveRelease(2, T0, false);
        vm.prank(guardian);
        control.revoke(AGR, "incident");
        vm.prank(treasury);
        vm.expectRevert(
            abi.encodeWithSelector(IControlRegistry.ReleaseBlocked.selector, "servicer approval missing or stale")
        );
        control.release(AGR, 2);
    }

    function test_release_blockedWithoutFacilityOrDebtSource() public {
        _createE2();
        _approveRelease(1, T0, false);
        vm.prank(treasury);
        vm.expectRevert(abi.encodeWithSelector(IControlRegistry.ReleaseBlocked.selector, "no facility bound"));
        control.release(AGR, 1);

        ControlRegistry noDebt = new ControlRegistry(roles, accounts, IDebtLedger(address(0)), MAX_AGE);
        vm.prank(underwriter);
        noDebt.createAgreement(
            AGR, BORROWER_A, ACCT, GpuTypes.ControlGrade.E2, RECEIVER, 11_155_111, HASH_V1, T0, 0, POC
        );
        vm.prank(underwriter);
        noDebt.bindFacility(AGR, FAC);
        vm.prank(servicer);
        noDebt.approveRelease(AGR, ControlRegistry.ReleaseTerms(1, T0, false));
        vm.prank(treasury);
        vm.expectRevert(
            abi.encodeWithSelector(IControlRegistry.ReleaseBlocked.selector, "no authoritative debt source")
        );
        noDebt.release(AGR, 1);
    }

    function test_registryHasNoLockOrNativeProofSurface() public view {
        // grade inputs are role decisions + pocRef only; no function accepts a proof/lock event.
        assertEq(control.controlObservationMaxAge(), MAX_AGE);
        assertEq(address(control.DEBT()), address(debt));
    }
}
