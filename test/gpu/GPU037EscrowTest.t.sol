// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import { Test } from "forge-std/Test.sol";
import { MockERC20 } from "../../contracts/mocks/MockERC20.sol";
import { GpuTypes } from "../../contracts/gpu/types/GpuTypes.sol";
import { ProtocolRoles } from "../../contracts/gpu/ProtocolRoles.sol";
import { AuthorizationVerifier } from "../../contracts/gpu/AuthorizationVerifier.sol";
import { ProviderRegistry } from "../../contracts/gpu/ProviderRegistry.sol";
import { AccountRegistry } from "../../contracts/gpu/AccountRegistry.sol";
import { ControlRegistry } from "../../contracts/gpu/ControlRegistry.sol";
import { DebtLedger } from "../../contracts/gpu/DebtLedger.sol";
import { RevenueEscrow, ISourceEscrowOwner } from "../../contracts/gpu/RevenueEscrow.sol";
import { SourceEscrow } from "../../contracts/gpu/source/SourceEscrow.sol";
import { ISourceEscrow } from "../../contracts/gpu/source/ISourceEscrow.sol";
import { MockDePINPayout } from "../../contracts/gpu/mocks/MockDePINPayout.sol";
import { IProviderRegistry } from "../../contracts/gpu/interfaces/IProviderRegistry.sol";
import { IControlRegistry } from "../../contracts/gpu/interfaces/IControlRegistry.sol";
import { IDebtLedger } from "../../contracts/gpu/interfaces/IDebtLedger.sol";
import { IRevenueEscrow } from "../../contracts/gpu/interfaces/IRevenueEscrow.sol";

/// @dev TEST_ONLY upstream "reward" contract: pays `amount` of `token` to `to` on claim; can re-enter the escrow.
contract UpstreamMock {
    MockERC20 public token;
    address public reenterTarget;
    bytes public reenterData;

    constructor(MockERC20 t) {
        token = t;
    }

    function setReenter(address target, bytes calldata data) external {
        reenterTarget = target;
        reenterData = data;
    }

    function claimRewards(address to, uint256 amount) external {
        token.mint(to, amount);
        if (reenterTarget != address(0)) {
            (bool ok, bytes memory ret) = reenterTarget.call(reenterData);
            if (!ok) {
                assembly ("memory-safe") {
                    revert(add(ret, 32), mload(ret))
                }
            }
        }
    }

    function drainTo(address to, uint256 amount) external {
        token.mint(to, amount);
    }
}

/// @dev TEST_ONLY fee-on-transfer token (1% fee) with the ERC-20 surface SourceEscrow needs.
contract FeeToken {
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    function mint(address to, uint256 amount) external {
        balanceOf[to] += amount;
    }

    function approve(address spender, uint256 amount) external returns (bool) {
        allowance[msg.sender][spender] = amount;
        return true;
    }

    function transfer(address to, uint256 amount) external returns (bool) {
        return _move(msg.sender, to, amount);
    }

    function transferFrom(address from, address to, uint256 amount) external returns (bool) {
        allowance[from][msg.sender] -= amount;
        return _move(from, to, amount);
    }

    function _move(address from, address to, uint256 amount) internal returns (bool) {
        balanceOf[from] -= amount;
        uint256 fee = amount / 100;
        balanceOf[to] += amount - fee;
        return true;
    }
}

/**
 * @title GPU037EscrowTest
 * @notice Controlled account + waterfall + restricted claim + release (GPU-037) composed over GPU-077 SourceEscrow,
 *         GPU-032 ControlRegistry and GPU-033 DebtLedger. LOCAL only: upstream is a mock, E2 is a registry entry
 *         with a PoC reference — real control is GPU-009/056 evidence.
 */
contract GPU037EscrowTest is Test {
    ProtocolRoles roles;
    AuthorizationVerifier auth;
    ProviderRegistry providers;
    AccountRegistry accounts;
    DebtLedger ledger;
    ControlRegistry control;
    MockERC20 usdc;
    SourceEscrow source;
    MockDePINPayout payer;
    RevenueEscrow escrow;
    UpstreamMock upstream;

    address admin = address(0xAD);
    address registrar = address(0x4E6);
    address underwriter = address(0x0DE);
    address guardian = address(0x6A);
    address servicer = address(0x5E);
    address treasury = address(0x7E);
    address writer = address(0x3A); // ledger writer (manager double)
    address issuer = address(0x155);
    address borrowerWallet = address(0xB0B);
    address mallory = address(0xBAD);
    address constant OPS = address(0x0A5);
    address constant LEG = address(0x1E6); // settlement leg (bridge / conversion venue double)
    address constant RECEIVER = address(0xE5C);

    bytes32 constant BORROWER_A = keccak256("borrower-A");
    bytes32 constant AGR = keccak256("agreement-A-1");
    bytes32 constant HASH_V1 = keccak256("agreement-text-v1");
    bytes32 constant HASH_V2 = keccak256("agreement-text-v2");
    bytes32 constant POC = keccak256("gpu-009-poc-PASS-ref");
    bytes32 constant MANIFEST = 0x2b0162d0c206f421138269a721c6338d8cf294d67dc644bb8b35ebb9bfbff6bb;
    bytes32 constant REF_A = keccak256("inv-2026-08-A");
    bytes32 constant REF_B = keccak256("inv-2026-08-B");
    GpuTypes.ProviderId MOCK = GpuTypes.ProviderId.wrap(keccak256("mockdepin-testonly"));
    GpuTypes.AccountKey ACCT = GpuTypes.AccountKey.wrap(keccak256("mockdepin-testonly:acct-A"));
    bytes32 ACCT_RAW = keccak256("mockdepin-testonly:acct-A");
    bytes32 constant OTHER_ACCT = keccak256("mockdepin-testonly:acct-Z");
    GpuTypes.FacilityId FAC = GpuTypes.FacilityId.wrap(keccak256("facility-A"));
    GpuTypes.FacilityId FAC2 = GpuTypes.FacilityId.wrap(keccak256("facility-A-junior"));
    uint64 constant MAX_AGE = 6 hours;
    uint64 T0 = 1_800_000_000;
    uint256 constant DRAW = 10_000e6;

    function setUp() public {
        vm.warp(T0);
        roles = new ProtocolRoles(admin);
        auth = new AuthorizationVerifier(roles, 15 minutes);
        providers = new ProviderRegistry(roles);
        accounts = new AccountRegistry(roles, auth, providers);
        ledger = new DebtLedger(roles);
        control = new ControlRegistry(roles, accounts, IDebtLedger(address(ledger)), MAX_AGE);
        usdc = new MockERC20("USD Coin", "USDC", 6);
        upstream = new UpstreamMock(usdc);

        vm.startPrank(admin);
        roles.grantRole(roles.REGISTRAR(), registrar);
        roles.grantRole(roles.UNDERWRITER(), underwriter);
        roles.grantRole(roles.GUARDIAN(), guardian);
        roles.grantRole(roles.SERVICER(), servicer);
        roles.grantRole(roles.TREASURY(), treasury);
        ledger.setWriter(writer, true);
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
        vm.stopPrank();

        // facility with real debt in the single ledger (release gate + "debt never changes here" assertions)
        vm.startPrank(writer);
        ledger.open(
            FAC,
            IDebtLedger.Terms({
                loanAsset: GpuTypes.AssetRef({ chainId: 102_031, token: address(usdc), decimals: 6 }),
                rateBps: 1000,
                maturityAt: 0,
                termsVersionId: keccak256("terms-v1"),
                policyVersionId: keccak256("policy-v1"),
                executionProfile: GpuTypes.ExecutionProfile.LOCAL_MOCK,
                capitalizeUnpaidInterest: false
            })
        );
        ledger.recordDraw(FAC, DRAW);
        vm.stopPrank();

        // E2 agreement, observed, bound to the facility
        vm.prank(underwriter);
        control.createAgreement(
            AGR, BORROWER_A, ACCT, GpuTypes.ControlGrade.E2, RECEIVER, 11_155_111, HASH_V1, T0, 0, POC
        );
        vm.prank(servicer);
        control.observe(AGR, GpuTypes.ControlGrade.E2, RECEIVER);
        vm.prank(underwriter);
        control.bindFacility(AGR, FAC);

        // source escrow (GPU-077) owned by this test at first, then handed to the controlled account
        source = new SourceEscrow(address(this), address(0));
        source.admitToken(address(usdc), 6, false);
        source.registerAccount(ACCT_RAW, borrowerWallet);
        source.registerAccount(OTHER_ACCT, address(0xC0DE));
        source.setIssuer(issuer, true);
        payer = new MockDePINPayout(source, address(this));
        source.setPayer(address(payer), true);
        escrow = new RevenueEscrow(roles, control, ISourceEscrowOwner(address(source)), AGR);
        source.setPayer(address(escrow), true); // forwardClaimed path
        source.transferOwnership(address(escrow));

        vm.prank(underwriter);
        escrow.setWaterfall(_waterfall(1));
    }

    // ------------------------------------------------------------------ helpers

    function _waterfall(uint32 version) internal view returns (IRevenueEscrow.Waterfall memory w) {
        w.version = version;
        w.token = address(usdc);
        w.operatingBps = 1000; // 10%
        w.operatingCapPerSweep = 500e6;
        w.operatingRecipient = OPS;
        w.reserveTarget = 1000e6;
        w.settlementLeg = LEG;
        w.residualRecipient = borrowerWallet;
        w.facilities = new IRevenueEscrow.FacilityAllocation[](2);
        w.facilities[0] = IRevenueEscrow.FacilityAllocation({ facilityId: FAC, target: 5000e6 });
        w.facilities[1] = IRevenueEscrow.FacilityAllocation({ facilityId: FAC2, target: 3000e6 });
        w.claimTargets = new IRevenueEscrow.ClaimTarget[](1);
        w.claimTargets[0] = IRevenueEscrow.ClaimTarget({
            target: address(upstream), selector: UpstreamMock.claimRewards.selector, recipientArgIndex: 0
        });
    }

    function _recognize(bytes32 ref, uint256 amount) internal {
        vm.prank(issuer);
        source.recognizeObligation(ACCT_RAW, ref, address(payer), address(usdc), amount, uint64(T0 + 30 days));
    }

    function _pay(bytes32 ref, uint256 amount, string memory sid) internal returns (uint64 seq) {
        usdc.mint(address(payer), amount);
        (seq,) = payer.payout(ACCT_RAW, ref, address(usdc), amount, keccak256(bytes(sid)));
    }

    function _sweep(uint64 seq) internal {
        vm.prank(servicer);
        escrow.sweep(seq);
    }

    function _debtNow() internal view returns (uint256) {
        return ledger.legalDebtAt(FAC, uint64(block.timestamp));
    }

    // ------------------------------------------------------------------ waterfall

    function test_sweep_fullWaterfall_twoFacilitiesBySeniority_debtUntouched() public {
        _recognize(REF_A, 12_000e6);
        uint64 seq = _pay(REF_A, 12_000e6, "S1");
        uint256 debtBefore = _debtNow();

        vm.expectEmit(true, true, true, true, address(escrow));
        emit IRevenueEscrow.SweptToSettlement(FAC, escrow.settlementIdOf(seq, 1, FAC), seq, 5000e6);
        vm.expectEmit(true, true, true, true, address(escrow));
        emit IRevenueEscrow.SweptToSettlement(FAC2, escrow.settlementIdOf(seq, 1, FAC2), seq, 3000e6);
        vm.expectEmit(true, true, true, true, address(escrow));
        emit IRevenueEscrow.PayoutSwept(seq, 1, 12_000e6, 500e6, 1000e6, 8000e6, 2500e6);
        _sweep(seq);

        assertEq(usdc.balanceOf(OPS), 500e6, "operating allowance capped per sweep (10% = 1,200 > cap 500)");
        assertEq(escrow.reserveBalance(address(usdc)), 1000e6, "reserve filled to target, held in escrow");
        assertEq(usdc.balanceOf(LEG), 8000e6, "debt sweep handed to the settlement leg");
        assertEq(escrow.sweptToFacility(FAC), 5000e6);
        assertEq(escrow.sweptToFacility(FAC2), 3000e6);
        assertEq(usdc.balanceOf(borrowerWallet), 2500e6, "residual to the borrower");
        assertEq(usdc.balanceOf(address(escrow)), 1000e6, "only the reserve stays");
        assertTrue(escrow.isSwept(seq));
        assertEq(escrow.settlementSeq(), 1);
        assertEq(_debtNow(), debtBefore, "a sweep never changes debt (R2-D07): allocation is leg 5");
        assertEq(source.trackedBalance(address(usdc)), 0);
    }

    function test_partialPayouts_continuePriorityAcrossSweeps() public {
        _recognize(REF_A, 12_000e6);
        uint64 s1 = _pay(REF_A, 3000e6, "S1");
        _sweep(s1);
        // 3,000: ops 300 (10% < cap), reserve 1,000, FAC 1,700
        assertEq(usdc.balanceOf(OPS), 300e6);
        assertEq(escrow.reserveBalance(address(usdc)), 1000e6);
        assertEq(escrow.sweptToFacility(FAC), 1700e6);
        assertEq(escrow.sweptToFacility(FAC2), 0);
        uint64 s2 = _pay(REF_A, 3000e6, "S2");
        _sweep(s2);
        // 3,000: ops 300, reserve already full, FAC 2,700 (total 4,400 < 5,000 target), nothing to FAC2 yet
        assertEq(usdc.balanceOf(OPS), 600e6);
        assertEq(escrow.sweptToFacility(FAC), 4400e6);
        assertEq(escrow.sweptToFacility(FAC2), 0);
        assertEq(usdc.balanceOf(LEG), 4400e6);
        assertEq(usdc.balanceOf(borrowerWallet), 0);
        uint64 s3 = _pay(REF_A, 6000e6, "S3");
        _sweep(s3);
        // 6,000: ops 500 (cap), FAC 600 (to target), FAC2 3,000 (target), residual 1,900
        assertEq(escrow.sweptToFacility(FAC), 5000e6);
        assertEq(escrow.sweptToFacility(FAC2), 3000e6);
        assertEq(usdc.balanceOf(borrowerWallet), 1900e6);
        ISourceEscrow.Obligation memory o = source.obligation(ACCT_RAW, REF_A);
        assertEq(uint8(o.status), uint8(ISourceEscrow.ObligationStatus.PAID));
    }

    function test_roundingFloorsBeneficiaries_remainderToResidual() public {
        _recognize(REF_A, 12_000e6);
        uint64 seq = _pay(REF_A, 1_234_567, "S1"); // 1.234567 USDC
        _sweep(seq);
        // 10% = 123456.7 -> 123456 ops; reserve takes the rest (target 1,000e6 not reached); residual 0
        assertEq(usdc.balanceOf(OPS), 123_456);
        assertEq(escrow.reserveBalance(address(usdc)), 1_234_567 - 123_456);
        assertEq(usdc.balanceOf(borrowerWallet), 0);
    }

    function test_multiPayoutInOneTx_eachSweptOnce() public {
        _recognize(REF_A, 5000e6);
        _recognize(REF_B, 5000e6);
        uint64 a = _pay(REF_A, 5000e6, "S1");
        uint64 b = _pay(REF_B, 5000e6, "S2");
        assertEq(b, a + 1);
        _sweep(b); // order of sweeping is free; each payout is swept at most once
        _sweep(a);
        assertEq(
            usdc.balanceOf(LEG) + escrow.reserveBalance(address(usdc)) + usdc.balanceOf(OPS)
                + usdc.balanceOf(borrowerWallet),
            10_000e6
        );
        vm.expectRevert(abi.encodeWithSelector(IRevenueEscrow.AlreadySwept.selector, a));
        _sweep(a);
    }

    // ------------------------------------------------------------------ sweep refusals

    function test_duplicateSweep_cancelled_unknown_otherAccount_rejected() public {
        _recognize(REF_A, 5000e6);
        uint64 seq = _pay(REF_A, 1000e6, "S1");
        _sweep(seq);
        vm.expectRevert(abi.encodeWithSelector(IRevenueEscrow.AlreadySwept.selector, seq));
        _sweep(seq);

        vm.expectRevert(abi.encodeWithSelector(IRevenueEscrow.PayoutNotSweepable.selector, uint64(99), "unknown"));
        _sweep(99);

        uint64 s2 = _pay(REF_A, 1000e6, "S2");
        vm.prank(issuer);
        source.cancelPayout(s2);
        vm.expectRevert(abi.encodeWithSelector(IRevenueEscrow.PayoutNotSweepable.selector, s2, "cancelled"));
        _sweep(s2);

        // a payout for another account on the same source escrow is not this controlled account's revenue
        usdc.mint(address(payer), 10e6);
        (uint64 s3,) = payer.payout(OTHER_ACCT, bytes32(0), address(usdc), 10e6, keccak256("S3"));
        vm.expectRevert(abi.encodeWithSelector(IRevenueEscrow.PayoutNotSweepable.selector, s3, "other account"));
        _sweep(s3);
    }

    function test_sweepRequiresUsableE2Agreement() public {
        _recognize(REF_A, 5000e6);
        uint64 seq = _pay(REF_A, 1000e6, "S1");
        // stale observation
        vm.warp(T0 + MAX_AGE + 1);
        vm.expectRevert(abi.encodeWithSelector(IControlRegistry.ObservationStale.selector, uint64(T0), MAX_AGE));
        _sweep(seq);
        vm.prank(servicer);
        control.observe(AGR, GpuTypes.ControlGrade.E2, RECEIVER);
        // observed receiver changed upstream => not effective
        vm.prank(servicer);
        control.observe(AGR, GpuTypes.ControlGrade.E2, address(0xDEAD));
        vm.expectRevert(abi.encodeWithSelector(IControlRegistry.AgreementNotEffective.selector, AGR, uint32(1)));
        _sweep(seq);
        vm.prank(servicer);
        control.observe(AGR, GpuTypes.ControlGrade.E2, RECEIVER);
        // downgrade observed to E1 => grade insufficient (isEffective false first)
        vm.prank(servicer);
        control.observe(AGR, GpuTypes.ControlGrade.E1, RECEIVER);
        vm.expectRevert(abi.encodeWithSelector(IControlRegistry.AgreementNotEffective.selector, AGR, uint32(1)));
        _sweep(seq);
        vm.prank(servicer);
        control.observe(AGR, GpuTypes.ControlGrade.E2, RECEIVER);
        // revoked
        vm.prank(guardian);
        control.revoke(AGR, "incident");
        vm.expectRevert(abi.encodeWithSelector(IControlRegistry.AgreementNotEffective.selector, AGR, uint32(1)));
        _sweep(seq);
        // only SERVICER may sweep at all
        vm.prank(mallory);
        vm.expectRevert(abi.encodeWithSelector(IRevenueEscrow.NotRole.selector, keccak256("SERVICER"), mallory));
        escrow.sweep(seq);
    }

    function test_newRegistryVersionNeedsNewWaterfall() public {
        _recognize(REF_A, 5000e6);
        uint64 seq = _pay(REF_A, 1000e6, "S1");
        vm.prank(underwriter);
        control.bumpVersion(
            AGR, GpuTypes.ControlGrade.E2, RECEIVER, 11_155_111, HASH_V2, uint64(block.timestamp), 0, POC
        );
        vm.prank(servicer);
        control.observe(AGR, GpuTypes.ControlGrade.E2, RECEIVER);
        vm.expectRevert(abi.encodeWithSelector(IRevenueEscrow.NoWaterfall.selector, uint32(2)));
        _sweep(seq);
        vm.prank(underwriter);
        escrow.setWaterfall(_waterfall(2));
        _sweep(seq);
        // 1,000: ops 100, reserve 900 (target not reached)
        assertEq(escrow.reserveBalance(address(usdc)), 900e6);
        assertEq(escrow.sweptToFacility(FAC), 0);
    }

    // ------------------------------------------------------------------ admin cannot bypass beneficiaries

    function test_adminBypassAttemptsRejected() public {
        // no generic execute / approve surface
        (bool ok,) = address(escrow).call(abi.encodeWithSignature("execute(address,bytes)", address(usdc), ""));
        assertFalse(ok);
        (ok,) = address(escrow)
            .call(abi.encodeWithSignature("approve(address,address,uint256)", address(usdc), mallory, 1));
        assertFalse(ok);
        (ok,) = address(escrow).call(abi.encodeWithSignature("notify(uint256)", 1e6));
        assertFalse(ok);
        (ok,) = address(source).call(abi.encodeWithSignature("notify(uint256)", 1e6));
        assertFalse(ok);
        // the source escrow's owner is the controlled account: admin/test cannot withdraw directly
        vm.expectRevert(abi.encodeWithSelector(ISourceEscrow.NotOwner.selector, address(this)));
        source.withdraw(address(usdc), mallory, 1);
        vm.prank(admin);
        vm.expectRevert(abi.encodeWithSelector(ISourceEscrow.NotOwner.selector, admin));
        source.withdraw(address(usdc), admin, 1);
        // waterfall / allowlist are immutable for the active version
        IRevenueEscrow.Waterfall memory w = _waterfall(1);
        w.residualRecipient = mallory;
        vm.prank(underwriter);
        vm.expectRevert(abi.encodeWithSelector(IRevenueEscrow.WaterfallExists.selector, uint32(1)));
        escrow.setWaterfall(w);
        w.version = 2;
        vm.prank(underwriter);
        vm.expectRevert(abi.encodeWithSelector(IRevenueEscrow.WaterfallVersionMismatch.selector, uint32(1), uint32(2)));
        escrow.setWaterfall(w);
        vm.prank(admin);
        vm.expectRevert(abi.encodeWithSelector(IRevenueEscrow.NotRole.selector, keccak256("UNDERWRITER"), admin));
        escrow.setWaterfall(w);
        // waterfall cannot route to itself or zero
        w = _waterfall(1);
        w.settlementLeg = address(escrow);
        vm.prank(underwriter);
        control.bumpVersion(
            AGR, GpuTypes.ControlGrade.E2, RECEIVER, 11_155_111, HASH_V2, uint64(block.timestamp), 0, POC
        );
        w.version = 2;
        vm.prank(underwriter);
        vm.expectRevert(abi.encodeWithSelector(IRevenueEscrow.InvalidWaterfall.selector, "self recipient"));
        escrow.setWaterfall(w);
    }

    // ------------------------------------------------------------------ restricted upstream claim

    function test_claim_allowlistedOnly_recipientForced_notControlEvidence() public {
        bytes memory good = abi.encodeCall(UpstreamMock.claimRewards, (address(escrow), 700e6));
        uint8 gradeBefore = uint8(control.effectiveGrade(AGR));
        vm.prank(servicer);
        uint256 measured = escrow.claim(address(upstream), good);
        assertEq(measured, 700e6);
        assertEq(escrow.claimedBalance(address(usdc)), 700e6, "claim proceeds are unclassified, not swept");
        assertEq(usdc.balanceOf(LEG), 0, "a claim never reaches the settlement leg by itself");
        assertEq(uint8(control.effectiveGrade(AGR)), gradeBefore, "upstream claim success is not control evidence");
        assertEq(uint8(control.agreement(AGR).grade), uint8(GpuTypes.ControlGrade.E2));

        // wrong recipient
        bytes memory wrong = abi.encodeCall(UpstreamMock.claimRewards, (mallory, 1e6));
        vm.prank(servicer);
        vm.expectRevert(
            abi.encodeWithSelector(IRevenueEscrow.ClaimRecipientMismatch.selector, address(escrow), mallory)
        );
        escrow.claim(address(upstream), wrong);
        // selector not allow-listed
        bytes memory drain = abi.encodeCall(UpstreamMock.drainTo, (address(escrow), 1e6));
        vm.prank(servicer);
        vm.expectRevert(
            abi.encodeWithSelector(
                IRevenueEscrow.ClaimNotAllowed.selector, address(upstream), UpstreamMock.drainTo.selector
            )
        );
        escrow.claim(address(upstream), drain);
        // target not allow-listed
        vm.prank(servicer);
        vm.expectRevert(
            abi.encodeWithSelector(
                IRevenueEscrow.ClaimNotAllowed.selector, address(usdc), UpstreamMock.claimRewards.selector
            )
        );
        escrow.claim(address(usdc), good);
        // non-servicer
        vm.prank(mallory);
        vm.expectRevert(abi.encodeWithSelector(IRevenueEscrow.NotRole.selector, keccak256("SERVICER"), mallory));
        escrow.claim(address(upstream), good);
    }

    function test_claim_reentrancyBlocked() public {
        vm.startPrank(admin);
        roles.grantRole(roles.SERVICER(), address(upstream)); // worst case: the upstream holds the sweep role
        vm.stopPrank();
        _recognize(REF_A, 5000e6);
        uint64 seq = _pay(REF_A, 1000e6, "S1");
        upstream.setReenter(address(escrow), abi.encodeCall(RevenueEscrow.sweep, (seq)));
        bytes memory good = abi.encodeCall(UpstreamMock.claimRewards, (address(escrow), 1e6));
        vm.prank(servicer);
        vm.expectRevert(
            abi.encodeWithSelector(
                IRevenueEscrow.ClaimFailed.selector, abi.encodeWithSelector(IRevenueEscrow.Reentrancy.selector)
            )
        );
        escrow.claim(address(upstream), good);
        assertFalse(escrow.isSwept(seq));
        assertEq(escrow.claimedBalance(address(usdc)), 0);
    }

    function test_forwardClaimed_goesThroughMeasuredSourcePath() public {
        _recognize(REF_A, 5000e6);
        bytes memory good = abi.encodeCall(UpstreamMock.claimRewards, (address(escrow), 700e6));
        vm.prank(servicer);
        escrow.claim(address(upstream), good);
        vm.prank(servicer);
        escrow.forwardClaimed(REF_A, 700e6, keccak256("claim-S1"));
        assertEq(escrow.claimedBalance(address(usdc)), 0);
        ISourceEscrow.Payout memory p = source.payout(1);
        assertEq(p.amount, 700e6);
        assertEq(p.payer, address(escrow));
        assertEq(source.obligation(ACCT_RAW, REF_A).paid, 700e6);
        _sweep(1);
        // 700: ops 70, reserve 630 (target 1,000 not yet reached), nothing left for the debt leg
        assertEq(escrow.reserveBalance(address(usdc)), 630e6);
        assertEq(escrow.sweptToFacility(FAC), 0);
        vm.prank(servicer);
        vm.expectRevert(abi.encodeWithSelector(IRevenueEscrow.InvalidWaterfall.selector, "claimed amount"));
        escrow.forwardClaimed(REF_A, 1, keccak256("claim-S2"));
    }

    // ------------------------------------------------------------------ donations / provenance

    function test_donationNeverSweptAsRevenue_refundExactDespiteWithdrawQuirk() public {
        // borrower self-transfer through the module: unattributed bucket, no payout seq exists
        usdc.mint(borrowerWallet, 700e6);
        vm.startPrank(borrowerWallet);
        usdc.approve(address(source), 700e6);
        (uint64 dseq,) = source.depositUnattributed(address(usdc), 700e6);
        vm.stopPrank();
        assertEq(dseq, 1);
        assertEq(source.settlementSeq(), 0, "no payout was created");
        assertEq(escrow.refundableUnattributed(address(usdc)), 700e6);
        vm.expectRevert(abi.encodeWithSelector(IRevenueEscrow.PayoutNotSweepable.selector, uint64(1), "unknown"));
        _sweep(1);

        // a real payout is swept: SourceEscrow.withdraw books against the unattributed bucket first (GPU-077),
        // but the controlled account keeps the refundable donation exact
        _recognize(REF_A, 5000e6);
        uint64 seq = _pay(REF_A, 1000e6, "S1");
        _sweep(seq);
        assertEq(source.unattributedBalance(address(usdc)), 0, "GPU-077 quirk: bucket consumed by the withdraw");
        assertEq(escrow.refundableUnattributed(address(usdc)), 700e6, "shadowed: donation still refundable");
        assertEq(usdc.balanceOf(address(source)), 700e6);

        vm.prank(treasury);
        escrow.refundUnattributed(address(usdc), borrowerWallet, 700e6);
        assertEq(escrow.refundableUnattributed(address(usdc)), 0);
        assertEq(usdc.balanceOf(address(source)), 0);
        vm.prank(treasury);
        vm.expectRevert(abi.encodeWithSelector(IRevenueEscrow.InvalidWaterfall.selector, "unattributed amount"));
        escrow.refundUnattributed(address(usdc), borrowerWallet, 1);
    }

    function test_feeOnTransferRejectedBySourceEscrow_measuredDelta() public {
        FeeToken fee = new FeeToken();
        // token admission is an owner action on the source escrow; the owner is the controlled account, which has no
        // admit passthrough — so a nonstandard token cannot even be admitted mid-agreement. Prove the measured-delta
        // refusal on a fresh source escrow with the same payer path.
        SourceEscrow s2 = new SourceEscrow(address(this), address(0));
        s2.admitToken(address(fee), 6, false);
        s2.registerAccount(ACCT_RAW, borrowerWallet);
        s2.setIssuer(issuer, true);
        MockDePINPayout p2 = new MockDePINPayout(s2, address(this));
        s2.setPayer(address(p2), true);
        vm.prank(issuer);
        s2.recognizeObligation(ACCT_RAW, REF_A, address(p2), address(fee), 1000e6, uint64(T0 + 1 days));
        fee.mint(address(p2), 1000e6);
        vm.expectRevert(abi.encodeWithSelector(ISourceEscrow.MeasuredDeltaMismatch.selector, 1000e6, 990e6));
        p2.payout(ACCT_RAW, REF_A, address(fee), 1000e6, keccak256("S1"));
        (bool ok,) =
            address(escrow).call(abi.encodeWithSignature("admitToken(address,uint8,bool)", address(fee), 6, true));
        assertFalse(ok, "no admit passthrough on the controlled account");
    }

    function test_sweepRefusesFeeOnTransferOnTheSweepLeg() public {
        // simulate a token that loses value on the withdraw leg: mutate the mock by burning after payout
        _recognize(REF_A, 5000e6);
        uint64 seq = _pay(REF_A, 1000e6, "S1");
        usdc.burn(address(source), 1); // SourceEscrow now holds less than it tracked
        vm.prank(servicer);
        vm.expectRevert(); // MockERC20 underflow on transfer -> TransferFailed bubbled from SourceEscrow
        escrow.sweep(seq);
        assertFalse(escrow.isSwept(seq));
    }

    // ------------------------------------------------------------------ release

    function _settleAllDebt() internal {
        // destination leg 5: the writer (manager) allocates actual received cash; the escrow never does this
        uint256 debt = _debtNow();
        vm.prank(writer);
        ledger.allocate(FAC, debt);
        assertEq(_debtNow(), 0);
    }

    function test_release_requiresRegistryRelease_refundFlag_andNoUnsweptPayout() public {
        _recognize(REF_A, 5000e6);
        uint64 seq = _pay(REF_A, 5000e6, "S1");
        _sweep(seq);
        _settleAllDebt();
        // registry has not released yet
        vm.prank(treasury);
        vm.expectRevert(
            abi.encodeWithSelector(
                IRevenueEscrow.ReleaseBlocked.selector, "control registry has not released the agreement"
            )
        );
        escrow.release(address(usdc), borrowerWallet);
        // servicer approval + window + treasury release in the registry
        vm.prank(servicer);
        control.approveRelease(
            AGR,
            ControlRegistry.ReleaseTerms({
                version: 1, reconciliationClosesAt: uint64(block.timestamp + 1 days), refundPending: false
            })
        );
        vm.warp(block.timestamp + 1 days);
        vm.prank(treasury);
        control.release(AGR, 1);
        assertTrue(control.status(AGR).released);
        // escrow-side refund flag blocks
        vm.prank(servicer);
        escrow.setRefundPending(true, "chargeback expected");
        vm.prank(treasury);
        vm.expectRevert(abi.encodeWithSelector(IRevenueEscrow.ReleaseBlocked.selector, "refund pending"));
        escrow.release(address(usdc), borrowerWallet);
        vm.prank(servicer);
        escrow.setRefundPending(false, "cleared");
        vm.prank(treasury);
        escrow.release(address(usdc), borrowerWallet);
        assertTrue(escrow.isReleased());
    }

    function test_release_unsweptPayoutBlocks_thenResidualReturned() public {
        _recognize(REF_A, 5000e6);
        uint64 seq = _pay(REF_A, 4000e6, "S1");
        _sweep(seq);
        _settleAllDebt();
        vm.prank(servicer);
        control.approveRelease(
            AGR,
            ControlRegistry.ReleaseTerms({
                version: 1, reconciliationClosesAt: uint64(block.timestamp + 1 days), refundPending: false
            })
        );
        vm.warp(block.timestamp + 1 days);
        vm.prank(treasury);
        control.release(AGR, 1);
        uint64 lateSeq = _pay(REF_A, 1000e6, "S2");
        vm.prank(treasury);
        vm.expectRevert(abi.encodeWithSelector(IRevenueEscrow.ReleaseBlocked.selector, "unswept classified payout"));
        escrow.release(address(usdc), borrowerWallet);
        // the late payout cannot be swept either: the registry says released => not effective
        vm.expectRevert(abi.encodeWithSelector(IControlRegistry.AgreementNotEffective.selector, AGR, uint32(1)));
        _sweep(lateSeq);
        // issuer cancels it (funds go back to the payer through the measured path) -> release proceeds
        vm.prank(issuer);
        source.cancelPayout(lateSeq);
        // wrong return address rejected
        vm.prank(treasury);
        vm.expectRevert(
            abi.encodeWithSelector(IRevenueEscrow.ReleaseBlocked.selector, "return address is not the borrower wallet")
        );
        escrow.release(address(usdc), mallory);
        uint256 reserve = escrow.reserveBalance(address(usdc));
        assertEq(reserve, 1000e6);
        uint256 walletBefore = usdc.balanceOf(borrowerWallet);
        vm.prank(treasury);
        escrow.release(address(usdc), borrowerWallet);
        assertTrue(escrow.isReleased());
        assertEq(escrow.reserveBalance(address(usdc)), 0);
        assertEq(usdc.balanceOf(borrowerWallet), walletBefore + reserve, "reserve is borrower-owned and returned");
        assertEq(source.owner(), borrowerWallet, "authority over the source escrow returned");
        vm.prank(treasury);
        vm.expectRevert(IRevenueEscrow.AlreadyReleased.selector);
        escrow.release(address(usdc), borrowerWallet);
        vm.prank(servicer);
        vm.expectRevert(IRevenueEscrow.AlreadyReleased.selector);
        escrow.sweep(1);
    }

    function test_release_debtZeroAlone_orOldVersionApproval_doesNotRelease() public {
        _recognize(REF_A, 5000e6);
        uint64 seq = _pay(REF_A, 5000e6, "S1");
        _sweep(seq);
        _settleAllDebt();
        // debt == 0 but no servicer approval / window: registry refuses, escrow refuses
        vm.prank(treasury);
        vm.expectRevert(
            abi.encodeWithSelector(IControlRegistry.ReleaseBlocked.selector, "servicer approval missing or stale")
        );
        control.release(AGR, 1);
        vm.prank(treasury);
        vm.expectRevert(
            abi.encodeWithSelector(
                IRevenueEscrow.ReleaseBlocked.selector, "control registry has not released the agreement"
            )
        );
        escrow.release(address(usdc), borrowerWallet);
        // approval for version 1, then a new version: the old approval cannot release the new version
        vm.prank(servicer);
        control.approveRelease(
            AGR,
            ControlRegistry.ReleaseTerms({
                version: 1, reconciliationClosesAt: uint64(block.timestamp), refundPending: false
            })
        );
        vm.prank(underwriter);
        control.bumpVersion(
            AGR, GpuTypes.ControlGrade.E2, RECEIVER, 11_155_111, HASH_V2, uint64(block.timestamp), 0, POC
        );
        vm.prank(treasury);
        vm.expectRevert(abi.encodeWithSelector(IControlRegistry.AgreementNotEffective.selector, AGR, uint32(1)));
        control.release(AGR, 1);
        vm.prank(treasury);
        vm.expectRevert(
            abi.encodeWithSelector(IControlRegistry.ReleaseBlocked.selector, "servicer approval missing or stale")
        );
        control.release(AGR, 2);
        assertFalse(control.status(AGR).released);
        assertFalse(escrow.isReleased());
    }

    function test_roleSeparation_treasuryOnlyRefundsAndReleases_servicerOnlyFlags() public {
        vm.prank(servicer);
        vm.expectRevert(abi.encodeWithSelector(IRevenueEscrow.NotRole.selector, keccak256("TREASURY"), servicer));
        escrow.refundUnattributed(address(usdc), borrowerWallet, 1);
        vm.prank(treasury);
        vm.expectRevert(abi.encodeWithSelector(IRevenueEscrow.NotRole.selector, keccak256("SERVICER"), treasury));
        escrow.setRefundPending(true, "x");
        vm.prank(servicer);
        vm.expectRevert(abi.encodeWithSelector(IRevenueEscrow.NotRole.selector, keccak256("TREASURY"), servicer));
        escrow.release(address(usdc), borrowerWallet);
        assertEq(escrow.accountKey(), ACCT_RAW);
        assertEq(escrow.controller(), address(escrow));
        assertEq(escrow.currentVersion(), 1);
        IRevenueEscrow.Waterfall memory w = escrow.waterfall(1);
        assertEq(w.facilities.length, 2);
        assertEq(w.claimTargets.length, 1);
    }
}
