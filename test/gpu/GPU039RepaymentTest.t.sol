// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import { Test } from "forge-std/Test.sol";
import { INativeQueryVerifier } from "@gluwa/asc-contracts/contracts/write-ability/common/INativeQueryVerifier.sol";
import { GpuTypes } from "../../contracts/gpu/types/GpuTypes.sol";
import { ProtocolRoles } from "../../contracts/gpu/ProtocolRoles.sol";
import { ProviderRegistry } from "../../contracts/gpu/ProviderRegistry.sol";
import { EvidenceBook } from "../../contracts/gpu/EvidenceBook.sol";
import { AttestcoinRevenueVerifier } from "../../contracts/gpu/AttestcoinRevenueVerifier.sol";
import { MockBlockProver } from "../../contracts/gpu/mocks/MockBlockProver.sol";
import { DebtLedger } from "../../contracts/gpu/DebtLedger.sol";
import { LendingVaultV2 } from "../../contracts/gpu/LendingVaultV2.sol";
import { RepaymentRouter, IFacilityWallets } from "../../contracts/gpu/RepaymentRouter.sol";
import { IRepaymentRouter } from "../../contracts/gpu/interfaces/IRepaymentRouter.sol";
import { IDebtLedger } from "../../contracts/gpu/interfaces/IDebtLedger.sol";
import { ILendingVaultV2 } from "../../contracts/gpu/interfaces/ILendingVaultV2.sol";
import { IProviderRegistry } from "../../contracts/gpu/interfaces/IProviderRegistry.sol";
import { IEvidenceBook } from "../../contracts/gpu/interfaces/IEvidenceBook.sol";
import { IRevenueVerifier } from "../../contracts/gpu/interfaces/IRevenueVerifier.sol";
import { MockERC20 } from "../../contracts/mocks/MockERC20.sol";
import { MockNoReturnERC20 } from "../../contracts/mocks/MockNoReturnERC20.sol";

/// @dev Stand-in for CreditFacilityManager.facilityInfo (same struct layout): facility → linked wallet.
contract FacilityWalletsStub {
    function recoveryManager() external pure returns (address) {
        return address(0);
    }
    function syncRepaid(GpuTypes.FacilityId) external pure { }
    mapping(GpuTypes.FacilityId => IFacilityWallets.Facility) private _f;

    function set(GpuTypes.FacilityId id, address wallet) external {
        IFacilityWallets.Facility memory f;
        f.wallet = wallet;
        f.exists = true;
        f.state = GpuTypes.FacilityState.ACTIVE;
        _f[id] = f;
    }

    function facilityInfo(GpuTypes.FacilityId id) external view returns (IFacilityWallets.Facility memory) {
        return _f[id];
    }
}

/// @dev TEST_ONLY token whose transferFrom re-enters the router with a second repayment.
contract ReenterToken {
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;
    RepaymentRouter public router;
    GpuTypes.FacilityId public target;
    bool public armed;
    bytes4 public lastError;

    function mint(address to, uint256 amount) external {
        balanceOf[to] += amount;
    }

    function arm(RepaymentRouter r, GpuTypes.FacilityId t) external {
        router = r;
        target = t;
        armed = true;
    }

    function approve(address spender, uint256 amount) external returns (bool) {
        allowance[msg.sender][spender] = amount;
        return true;
    }

    function transfer(address to, uint256 amount) external returns (bool) {
        balanceOf[msg.sender] -= amount;
        balanceOf[to] += amount;
        return true;
    }

    function transferFrom(address from, address to, uint256 amount) external returns (bool) {
        if (armed) {
            armed = false;
            // re-enter with a second repayment: must be rejected with Reentrancy (recorded, not propagated)
            try router.repayFor(target, 1, bytes32(0)) {
                lastError = bytes4(0);
            } catch (bytes memory reason) {
                lastError = bytes4(reason);
            }
        }
        allowance[from][msg.sender] -= amount;
        balanceOf[from] -= amount;
        balanceOf[to] += amount;
        return true;
    }
}

/// @dev Allowed consumer double for the EvidenceBook (proof-only path).
contract Consumer {
    IEvidenceBook public immutable BOOK;

    constructor(IEvidenceBook b) {
        BOOK = b;
    }

    function consume(
        GpuTypes.ProviderId p,
        GpuTypes.NativeProofEnvelope calldata e,
        address emitter,
        bytes32[] calldata t,
        IEvidenceBook.ConsumeInstruction[] calldata ins
    ) external returns (IEvidenceBook.EvidenceRecord[] memory) {
        return BOOK.consume(p, e, emitter, t, ins);
    }
}

/**
 * @title GPU039RepaymentTest
 * @notice RepaymentRouter: measured destination receipts split by the single ledger; excess is borrower-owned;
 *         settlement ids consumed once; no evidence dependency. LOCAL only (mock token, mock BlockProver).
 */
contract GPU039RepaymentTest is Test {
    address admin = address(0xAD);
    address registrar = address(0x4E6);
    address treasury = address(0x7E);
    address servicer = address(0x5E);
    address borrowerA = address(0xB0A);
    address borrowerB = address(0xB0B);
    address thirdParty = address(0x3D);
    address lp = address(0x1B);
    address mallory = address(0xBAD);

    ProtocolRoles roles;
    DebtLedger ledger;
    MockERC20 usd;
    LendingVaultV2 vault;
    FacilityWalletsStub wallets;
    RepaymentRouter router;

    // proof path (only to prove it changes nothing)
    ProviderRegistry providers;
    MockBlockProver prover;
    AttestcoinRevenueVerifier verifier;
    EvidenceBook evidence;
    Consumer consumer;
    string wireJson;

    GpuTypes.FacilityId FA = GpuTypes.FacilityId.wrap(keccak256("facility-A"));
    GpuTypes.FacilityId FB = GpuTypes.FacilityId.wrap(keccak256("facility-B"));
    GpuTypes.FacilityId FX = GpuTypes.FacilityId.wrap(keccak256("facility-unknown"));
    bytes32 constant MANIFEST = 0x2b0162d0c206f421138269a721c6338d8cf294d67dc644bb8b35ebb9bfbff6bb;
    bytes32 constant ENV_ID_HASH = keccak256("cc3-testnet");
    GpuTypes.ProviderId MOCK = GpuTypes.ProviderId.wrap(keccak256("mockdepin-testonly"));
    address constant ESCROW = address(0xE1);
    bytes32 constant TOPIC =
        keccak256("ObligationRecognized(bytes32,bytes32,address,address,address,uint256,uint64,uint32)");
    uint64 constant T0 = 1_750_000_000;
    uint256 constant PRINCIPAL = 5000e6;
    uint256 constant LP_CASH = 100_000e6;

    function setUp() public {
        vm.warp(T0);
        roles = new ProtocolRoles(admin);
        ledger = new DebtLedger(roles);
        usd = new MockERC20("TEST_ONLY USD", "tUSD", 6);
        vault = new LendingVaultV2(roles, ledger, address(usd));
        wallets = new FacilityWalletsStub();
        router = new RepaymentRouter(roles, ledger, vault, IFacilityWallets(address(wallets)));

        vm.startPrank(admin);
        roles.grantRole(roles.REGISTRAR(), registrar);
        roles.grantRole(roles.TREASURY(), treasury);
        roles.grantRole(roles.SERVICER(), servicer);
        ledger.setWriter(address(this), true); // test harness plays the manager for open/draw/fee
        ledger.setWriter(address(router), true);
        vault.setManager(address(this), true);
        vault.setManager(address(router), true);
        vm.stopPrank();

        usd.mint(lp, LP_CASH);
        vm.startPrank(lp);
        usd.approve(address(vault), LP_CASH);
        vault.deposit(LP_CASH, 0);
        vm.stopPrank();

        _openAndDraw(FA, borrowerA, PRINCIPAL);
        _openAndDraw(FB, borrowerB, 2000e6);

        usd.mint(borrowerA, 1_000_000e6);
        usd.mint(borrowerB, 1_000_000e6);
        usd.mint(thirdParty, 1_000_000e6);
        usd.mint(treasury, 1_000_000e6);
        vm.prank(borrowerA);
        usd.approve(address(router), type(uint256).max);
        vm.prank(borrowerB);
        usd.approve(address(router), type(uint256).max);
        vm.prank(thirdParty);
        usd.approve(address(router), type(uint256).max);
        vm.prank(treasury);
        usd.approve(address(router), type(uint256).max);

        _setupProofPath();
    }

    // ------------------------------------------------------------------ helpers

    function _terms() internal pure returns (IDebtLedger.Terms memory) {
        return IDebtLedger.Terms({
            loanAsset: GpuTypes.AssetRef({ chainId: 102_031, token: address(0), decimals: 6 }),
            rateBps: 1000,
            maturityAt: 0,
            termsVersionId: keccak256("terms-v1"),
            policyVersionId: keccak256("policy-v1"),
            executionProfile: GpuTypes.ExecutionProfile.LOCAL_MOCK,
            capitalizeUnpaidInterest: false
        });
    }

    function _openAndDraw(GpuTypes.FacilityId id, address wallet, uint256 amount) internal {
        ledger.open(id, _terms());
        ledger.recordDraw(id, amount);
        vault.lend(id, wallet, amount);
        wallets.set(id, wallet);
    }

    function _debt(GpuTypes.FacilityId id) internal view returns (uint256) {
        return ledger.legalDebtAt(id, uint64(block.timestamp));
    }

    function _assertSplit(GpuTypes.RepayResult memory r) internal pure {
        assertEq(r.received, r.feePaid + r.interestPaid + r.principalPaid + r.excess, "received == split");
        assertEq(r.applied, r.feePaid + r.interestPaid + r.principalPaid, "applied == paid parts");
    }

    function _setupProofPath() internal {
        wireJson = vm.readFile("test/fixtures/gpu/attestcoin/wire/synthetic-obligation-v1.json");
        providers = new ProviderRegistry(roles);
        prover = new MockBlockProver();
        GpuTypes.SourceChainRef memory src = GpuTypes.SourceChainRef({
            envIdHash: ENV_ID_HASH, chainKey: 1, chainId: 11_155_111, encoding: 1, manifestHash: MANIFEST
        });
        vm.startPrank(registrar);
        providers.registerProvider(
            MOCK,
            IProviderRegistry.ProviderConfig({
                sourceChain: src,
                executionProfile: GpuTypes.ExecutionProfile.LOCAL_MOCK,
                testOnly: true,
                policyVersionId: keccak256("policy-v1"),
                admissionEnabled: true
            })
        );
        providers.registerEmitter(
            MOCK, ESCROW, TOPIC, GpuTypes.EvidenceMeaning.OBLIGATION_RECOGNIZED, bytes32(0), address(0)
        );
        vm.stopPrank();
        verifier = new AttestcoinRevenueVerifier(
            address(prover),
            providers,
            MOCK,
            src,
            GpuTypes.ExecutionProfile.LOCAL_MOCK,
            AttestcoinRevenueVerifier.Limits({ maxTxBytes: 8192, maxLogs: 16, maxSiblings: 32, maxContinuityRoots: 64 })
        );
        evidence = new EvidenceBook(roles, providers, ENV_ID_HASH, 30 days);
        consumer = new Consumer(evidence);
        vm.startPrank(admin);
        evidence.bindVerifier(MOCK, verifier);
        evidence.setConsumer(address(consumer), true);
        vm.stopPrank();
    }

    function _envelope() internal view returns (GpuTypes.NativeProofEnvelope memory e) {
        e.chainKey = 1;
        e.height = 9_100_000;
        e.encodedTransaction = vm.parseJsonBytes(wireJson, ".cases.obligation2Logs.txBytes");
        e.merkleRoot = keccak256("root");
        e.siblings = new INativeQueryVerifier.MerkleProofEntry[](1);
        e.siblings[0] = INativeQueryVerifier.MerkleProofEntry({ hash: keccak256("s"), isLeft: true });
        e.lowerEndpointDigest = keccak256("lower");
        e.continuityRoots = new bytes32[](1);
        e.continuityRoots[0] = keccak256("c0");
    }

    function _consumeProof() internal {
        bytes32[] memory t = new bytes32[](1);
        t[0] = TOPIC;
        IEvidenceBook.ConsumeInstruction[] memory ins = new IEvidenceBook.ConsumeInstruction[](1);
        ins[0] = IEvidenceBook.ConsumeInstruction({
            logOrdinal: 0,
            economicEventId: GpuTypes.EconomicEventId.wrap(keccak256("econ-A")),
            accountKey: GpuTypes.AccountKey.wrap(keccak256("mockdepin-testonly:acct-A")),
            validUntil: uint64(block.timestamp + 7 days)
        });
        consumer.consume(MOCK, _envelope(), ESCROW, t, ins);
    }

    // ------------------------------------------------------------------ direct repayment

    function test_partialInterest_preservesUnpaidInterestAndPrincipal() public {
        vm.warp(T0 + 365 days);
        assertEq(_debt(FA), 5500e6);
        vm.prank(borrowerA);
        GpuTypes.RepayResult memory r = router.repayFor(FA, 250e6, bytes32("ref-1"));
        _assertSplit(r);
        assertEq(r.interestPaid, 250e6);
        assertEq(r.principalPaid, 0);
        assertEq(r.excess, 0);
        assertEq(r.newDebt, 5250e6, "AR-01: $5,000 / 10% / 365d / $250 => $5,250");
        assertEq(ledger.view_(FA).principal, PRINCIPAL);
        assertEq(ledger.unpaidInterestAt(FA, uint64(block.timestamp)), 250e6);
    }

    function test_feesFirst_thenInterest_thenPrincipal() public {
        ledger.recordFee(FA, 100e6, "origination");
        vm.warp(T0 + 365 days);
        vm.prank(borrowerA);
        GpuTypes.RepayResult memory r = router.repayFor(FA, 1000e6, bytes32(0));
        _assertSplit(r);
        assertEq(r.feePaid, 100e6);
        assertEq(r.interestPaid, 500e6);
        assertEq(r.principalPaid, 400e6);
        assertEq(r.newDebt, 4600e6);
    }

    function test_fullPlusExcess_excessIsBorrowerOwnedNotNav() public {
        vm.warp(T0 + 365 days);
        uint256 navBefore = vault.nav();
        vm.prank(borrowerA);
        GpuTypes.RepayResult memory r = router.repayFor(FA, 6000e6, bytes32("ref-full"));
        _assertSplit(r);
        assertEq(r.applied, 5500e6);
        assertEq(r.excess, 500e6);
        assertEq(r.newDebt, 0);
        assertEq(router.refundable(FA), 500e6);
        assertEq(vault.totalBorrowerOwned(), 500e6);
        // NAV: receivables fell by 5,500 and LP cash rose by exactly 5,500; the 500 excess never entered NAV
        assertEq(vault.nav(), navBefore);
        assertEq(_debt(FA), 0);
    }

    function test_debtZero_rejected() public {
        vm.prank(borrowerA);
        router.repayExact(FA, type(uint128).max);
        assertEq(_debt(FA), 0);
        vm.prank(borrowerA);
        vm.expectRevert(abi.encodeWithSelector(IRepaymentRouter.NothingToRepay.selector, FA));
        router.repayFor(FA, 1e6, bytes32(0));
        vm.prank(borrowerA);
        vm.expectRevert(abi.encodeWithSelector(IRepaymentRouter.NothingToRepay.selector, FA));
        router.repayExact(FA, 1e6);
    }

    function test_thirdPartyPayer_reducesDebtorFacility_notPayer() public {
        vm.warp(T0 + 100 days);
        uint256 debtBefore = _debt(FA);
        uint256 balBefore = usd.balanceOf(thirdParty);
        vm.prank(thirdParty);
        GpuTypes.RepayResult memory r = router.repayFor(FA, 1000e6, bytes32("3p"));
        _assertSplit(r);
        assertEq(usd.balanceOf(thirdParty), balBefore - 1000e6);
        assertEq(_debt(FA), debtBefore - 1000e6);
        assertEq(router.refundable(FA), 0);
    }

    function test_repayExact_capsPullAtCurrentDebt_noExcess() public {
        vm.warp(T0 + 365 days);
        uint256 balBefore = usd.balanceOf(borrowerA);
        vm.prank(borrowerA);
        GpuTypes.RepayResult memory r = router.repayExact(FA, 50_000e6);
        _assertSplit(r);
        assertEq(r.requested, 5500e6, "cap-before-transfer: only the legal debt is pulled");
        assertEq(r.received, 5500e6);
        assertEq(r.excess, 0);
        assertEq(usd.balanceOf(borrowerA), balBefore - 5500e6);
        assertEq(_debt(FA), 0);
    }

    function test_otherFacilityPrincipalUnchanged() public {
        vm.warp(T0 + 30 days);
        uint256 debtB = _debt(FB);
        vm.prank(borrowerA);
        router.repayFor(FA, 3000e6, bytes32(0));
        assertEq(_debt(FB), debtB);
        assertEq(ledger.view_(FB).principal, 2000e6);
    }

    function test_wrongFacility_rejected() public {
        vm.prank(borrowerA);
        vm.expectRevert(abi.encodeWithSelector(IDebtLedger.FacilityUnknown.selector, FX));
        router.repayFor(FX, 1e6, bytes32(0));
    }

    function test_wrongToken_isNeverCounted() public {
        MockERC20 other = new MockERC20("OTHER", "OTH", 6);
        other.mint(borrowerA, 1000e6);
        vm.prank(borrowerA);
        other.transfer(address(router), 1000e6); // foreign token sent to the router: no receipt, no debt change
        uint256 debt = _debt(FA);
        assertEq(router.ASSET(), address(usd));
        assertEq(router.unallocated(keccak256("nothing")), 0);
        assertEq(_debt(FA), debt);
        // and the vault's asset is the only asset the router will ever pull
        vm.prank(borrowerA);
        usd.approve(address(router), 0);
        vm.prank(borrowerA);
        vm.expectRevert(IRepaymentRouter.TransferFailed.selector);
        router.repayFor(FA, 1e6, bytes32(0));
    }

    function test_repaymentWorksWhileDrawsFrozenOrPaused() public {
        ledger.setState(FA, GpuTypes.FacilityState.DRAW_FROZEN);
        vm.warp(T0 + 10 days);
        vm.prank(borrowerA);
        GpuTypes.RepayResult memory r = router.repayFor(FA, 100e6, bytes32(0));
        _assertSplit(r);
        assertEq(r.received, 100e6);
    }

    // ------------------------------------------------------------------ token edge cases

    function test_nonReturningERC20_accepted() public {
        MockNoReturnERC20 nrt = new MockNoReturnERC20();
        LendingVaultV2 v2 = new LendingVaultV2(roles, ledger, address(nrt));
        RepaymentRouter r2 = new RepaymentRouter(roles, ledger, v2, IFacilityWallets(address(wallets)));
        GpuTypes.FacilityId FN = GpuTypes.FacilityId.wrap(keccak256("facility-N"));
        vm.startPrank(admin);
        v2.setManager(address(this), true);
        v2.setManager(address(r2), true);
        ledger.setWriter(address(r2), true);
        vm.stopPrank();
        nrt.mint(lp, 10_000e6);
        vm.startPrank(lp);
        nrt.approve(address(v2), 10_000e6);
        v2.deposit(10_000e6, 0);
        vm.stopPrank();
        ledger.open(FN, _terms());
        ledger.recordDraw(FN, 1000e6);
        v2.lend(FN, borrowerA, 1000e6);
        vm.startPrank(borrowerA);
        nrt.approve(address(r2), 1000e6);
        GpuTypes.RepayResult memory r = r2.repayFor(FN, 1000e6, bytes32(0));
        vm.stopPrank();
        _assertSplit(r);
        assertEq(r.principalPaid, 1000e6);
        assertEq(ledger.legalDebtAt(FN, uint64(block.timestamp)), 0);
    }

    function test_reentrancy_rejected_stateUnchanged() public {
        ReenterToken rt = new ReenterToken();
        LendingVaultV2 v2 = new LendingVaultV2(roles, ledger, address(rt));
        RepaymentRouter r2 = new RepaymentRouter(roles, ledger, v2, IFacilityWallets(address(wallets)));
        GpuTypes.FacilityId FR = GpuTypes.FacilityId.wrap(keccak256("facility-R"));
        vm.startPrank(admin);
        v2.setManager(address(this), true);
        v2.setManager(address(r2), true);
        ledger.setWriter(address(r2), true);
        vm.stopPrank();
        rt.mint(lp, 10_000e6);
        vm.startPrank(lp);
        rt.approve(address(v2), 10_000e6);
        v2.deposit(10_000e6, 0);
        vm.stopPrank();
        ledger.open(FR, _terms());
        ledger.recordDraw(FR, 1000e6);
        v2.lend(FR, borrowerA, 1000e6);
        rt.arm(r2, FR);
        vm.startPrank(borrowerA);
        rt.approve(address(r2), type(uint256).max);
        GpuTypes.RepayResult memory r = r2.repayFor(FR, 500e6, bytes32(0));
        vm.stopPrank();
        assertEq(rt.lastError(), IRepaymentRouter.Reentrancy.selector, "re-entrant repayment rejected");
        _assertSplit(r);
        assertEq(r.received, 500e6, "outer repayment applied exactly once");
        assertEq(ledger.legalDebtAt(FR, uint64(block.timestamp)), 500e6);
        assertEq(rt.balanceOf(address(v2)), 9500e6);
    }

    // ------------------------------------------------------------------ settlement leg

    function test_settlement_recordThenAllocate_andReuseRejected() public {
        vm.warp(T0 + 365 days);
        bytes32 sid = keccak256("settlement-1");
        uint256 navBefore = vault.nav();
        vm.prank(treasury);
        router.recordDestinationReceipt(sid, 3000e6, bytes32("sweep-ref"));
        (uint256 total, uint256 allocated) = router.received(sid);
        assertEq(total, 3000e6);
        assertEq(allocated, 0);
        assertEq(router.unallocated(sid), 3000e6);
        assertEq(usd.balanceOf(address(router)), 3000e6, "held by the router until allocated");
        assertEq(vault.nav(), navBefore, "unallocated settlement cash is not NAV");
        assertEq(_debt(FA), 5500e6, "recording a receipt is not repayment");

        vm.prank(treasury);
        GpuTypes.RepayResult memory r = router.allocate(sid, FA, 2000e6);
        _assertSplit(r);
        assertEq(r.interestPaid, 500e6);
        assertEq(r.principalPaid, 1500e6);
        assertEq(_debt(FA), 3500e6);
        assertEq(router.unallocated(sid), 1000e6);

        vm.prank(treasury);
        vm.expectRevert(abi.encodeWithSelector(IRepaymentRouter.AllocationExceedsReceipt.selector, sid, 4500e6, 3000e6));
        router.allocate(sid, FA, 2500e6);

        vm.prank(treasury);
        vm.expectRevert(abi.encodeWithSelector(IRepaymentRouter.DuplicateSettlement.selector, sid));
        router.recordDestinationReceipt(sid, 1e6, bytes32(0));
        vm.prank(treasury);
        vm.expectRevert(abi.encodeWithSelector(IRepaymentRouter.DuplicateSettlement.selector, sid));
        router.receiveSettlement(FA, sid, 1e6);
    }

    function test_receiveSettlement_oneStep_excessRefundable() public {
        vm.warp(T0 + 365 days);
        bytes32 sid = keccak256("settlement-2");
        vm.prank(treasury);
        GpuTypes.RepayResult memory r = router.receiveSettlement(FA, sid, 6000e6);
        _assertSplit(r);
        assertEq(r.applied, 5500e6);
        assertEq(r.excess, 500e6);
        assertEq(router.unallocated(sid), 0);
        assertEq(router.refundable(FA), 500e6);
        vm.prank(treasury);
        vm.expectRevert(abi.encodeWithSelector(IRepaymentRouter.UnknownSettlement.selector, keccak256("no")));
        router.allocate(keccak256("no"), FA, 1e6);
    }

    function test_settlementLeg_requiresRole() public {
        vm.prank(mallory);
        vm.expectRevert(abi.encodeWithSelector(IRepaymentRouter.NotSettlementLeg.selector, mallory));
        router.recordDestinationReceipt(keccak256("x"), 1e6, bytes32(0));
        vm.prank(borrowerA);
        vm.expectRevert(abi.encodeWithSelector(IRepaymentRouter.NotSettlementLeg.selector, borrowerA));
        router.receiveSettlement(FA, keccak256("x"), 1e6);
    }

    // ------------------------------------------------------------------ refunds

    function test_refundExcess_onlyWalletOrServicer_onlyToWallet() public {
        vm.prank(borrowerA);
        router.repayFor(FA, 6000e6, bytes32(0)); // debt 5,000 at T0 → 1,000 excess
        assertEq(router.refundable(FA), 1000e6);
        vm.prank(mallory);
        vm.expectRevert(abi.encodeWithSelector(IRepaymentRouter.NotRefundAuthority.selector, FA, mallory));
        router.refundExcess(FA, mallory);
        vm.prank(servicer);
        vm.expectRevert(abi.encodeWithSelector(IRepaymentRouter.NotRefundAuthority.selector, FA, mallory));
        router.refundExcess(FA, mallory);
        vm.prank(mallory);
        vm.expectRevert(abi.encodeWithSelector(IRepaymentRouter.NotRefundAuthority.selector, FA, mallory));
        router.refundExcess(FA, borrowerA);
        uint256 before = usd.balanceOf(borrowerA);
        vm.prank(servicer);
        uint256 amt = router.refundExcess(FA, borrowerA);
        assertEq(amt, 1000e6);
        assertEq(usd.balanceOf(borrowerA), before + 1000e6);
        assertEq(vault.totalBorrowerOwned(), 0);
        vm.prank(borrowerA);
        vm.expectRevert(abi.encodeWithSelector(IRepaymentRouter.NothingToRefund.selector, FA));
        router.refundExcess(FA, borrowerA);
    }

    // ------------------------------------------------------------------ invariants / fuzz

    function testFuzz_receivedEqualsSplit(uint96 amount, uint32 elapsedDays) public {
        amount = uint96(bound(amount, 1, 20_000e6));
        elapsedDays = uint32(bound(elapsedDays, 0, 730));
        vm.warp(T0 + uint256(elapsedDays) * 1 days);
        uint256 debtBefore = _debt(FA);
        vm.prank(thirdParty);
        GpuTypes.RepayResult memory r = router.repayFor(FA, amount, bytes32(0));
        _assertSplit(r);
        assertEq(r.received, amount);
        assertEq(r.newDebt, debtBefore - r.applied);
        assertEq(router.refundable(FA), r.excess);
    }

    // ------------------------------------------------------------------ R2: proofs never move debt; outage never
    // blocks cash

    function test_proofOnly_noCash_debtAndNavUnchanged() public {
        vm.warp(T0 + 30 days);
        uint256 debt = _debt(FA);
        uint256 nav = vault.nav();
        uint256 cash = vault.availableCash();
        _consumeProof();
        assertTrue(evidence.isConsumed(verifier.sourceEventId(9_100_000, 1, 0)), "native (mock) evidence consumed");
        assertEq(_debt(FA), debt, "a source proof is not repayment");
        assertEq(vault.nav(), nav);
        assertEq(vault.availableCash(), cash);
    }

    function test_directRepay_succeedsDuringProofOutage() public {
        prover.setResult(false); // official verification unavailable / failing
        vm.expectRevert();
        _consumeProof();
        vm.warp(T0 + 30 days);
        vm.prank(borrowerA);
        GpuTypes.RepayResult memory r = router.repayFor(FA, 1000e6, bytes32("outage"));
        _assertSplit(r);
        assertEq(r.received, 1000e6);
    }

    function test_routerHasNoEvidenceOrSignatureSurface() public view {
        // the router binds ledger + vault + wallet lookup only; no verifier/evidence/authorization dependency exists
        assertEq(address(router.LEDGER()), address(ledger));
        assertEq(address(router.VAULT()), address(vault));
        assertEq(address(router.FACILITIES()), address(wallets));
    }
}
