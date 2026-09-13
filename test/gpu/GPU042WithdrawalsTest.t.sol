// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import { Test } from "forge-std/Test.sol";
import { MockERC20 } from "../../contracts/mocks/MockERC20.sol";
import { ProtocolRoles } from "../../contracts/gpu/ProtocolRoles.sol";
import { DebtLedger } from "../../contracts/gpu/DebtLedger.sol";
import { LendingVaultV2 } from "../../contracts/gpu/LendingVaultV2.sol";
import { IDebtLedger } from "../../contracts/gpu/interfaces/IDebtLedger.sol";
import { ILendingVaultV2 } from "../../contracts/gpu/interfaces/ILendingVaultV2.sol";
import { GpuTypes } from "../../contracts/gpu/types/GpuTypes.sol";

/// @dev TEST_ONLY outgoing fee/callback token; incoming transfers are exact.
contract QueueAdversarialToken {
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;
    LendingVaultV2 public vault;
    bool public chargeFee;
    bool public callback;
    bytes public callbackRevert;

    function configure(LendingVaultV2 v, bool fee, bool reenter) external {
        vault = v;
        chargeFee = fee;
        callback = reenter;
    }

    function mint(address to, uint256 amount) external {
        balanceOf[to] += amount;
    }

    function approve(address to, uint256 amount) external returns (bool) {
        allowance[msg.sender][to] = amount;
        return true;
    }

    function transferFrom(address from, address to, uint256 amount) external returns (bool) {
        allowance[from][msg.sender] -= amount;
        balanceOf[from] -= amount;
        balanceOf[to] += amount;
        return true;
    }

    function transfer(address to, uint256 amount) external returns (bool) {
        balanceOf[msg.sender] -= amount;
        balanceOf[to] += chargeFee ? amount - 1 : amount;
        if (callback) {
            callback = false;
            try vault.claimWithdrawal(1) { }
            catch (bytes memory reason) {
                callbackRevert = reason;
            }
        }
        return true;
    }
}

/// @notice LOCAL_MOCK cash/queue/epoch accounting using the real single DebtLedger, no source proof claims.
contract GPU042WithdrawalsTest is Test {
    ProtocolRoles roles;
    DebtLedger ledger;
    MockERC20 usdc;
    LendingVaultV2 vault;
    address admin = address(0xAD);
    address guardian = address(0x6A);
    address manager = address(0x3A);
    address lp1 = address(0x11);
    address lp2 = address(0x12);
    address lp3 = address(0x13);
    address borrower = address(0xB0);
    address attacker = address(0xBAD);
    GpuTypes.FacilityId F1 = GpuTypes.FacilityId.wrap(keccak256("queue-facility-1"));
    GpuTypes.FacilityId F2 = GpuTypes.FacilityId.wrap(keccak256("queue-facility-2"));

    function setUp() public {
        vm.warp(1_800_000_000);
        roles = new ProtocolRoles(admin);
        ledger = new DebtLedger(roles);
        usdc = new MockERC20("TEST ONLY USD Coin", "USDC", 6);
        vault = new LendingVaultV2(roles, ledger, address(usdc));
        vm.startPrank(admin);
        roles.grantRole(roles.GUARDIAN(), guardian);
        ledger.setWriter(manager, true);
        vault.setManager(manager, true);
        vm.stopPrank();
        usdc.mint(lp1, 1_000_000_000e6);
        usdc.mint(lp2, 1_000_000_000e6);
        usdc.mint(lp3, 1_000_000_000e6);
        usdc.mint(borrower, 1_000_000_000e6);
    }

    function _deposit(address lp, uint256 amount) internal returns (uint256 shares) {
        vm.startPrank(lp);
        usdc.approve(address(vault), amount);
        shares = vault.deposit(amount, 0);
        vm.stopPrank();
    }

    function _draw(GpuTypes.FacilityId id, uint256 amount, uint32 rate) internal {
        vm.startPrank(manager);
        ledger.open(
            id,
            IDebtLedger.Terms({
                loanAsset: GpuTypes.AssetRef({ chainId: uint64(block.chainid), token: address(usdc), decimals: 6 }),
                rateBps: rate,
                maturityAt: 0,
                termsVersionId: keccak256("TEST_ONLY_TERMS"),
                policyVersionId: keccak256("TEST_ONLY_POLICY"),
                executionProfile: GpuTypes.ExecutionProfile.LOCAL_MOCK,
                capitalizeUnpaidInterest: false
            })
        );
        ledger.recordDraw(id, amount);
        vault.lend(id, borrower, amount);
        vm.stopPrank();
    }

    function _repay(GpuTypes.FacilityId id, uint256 amount) internal returns (GpuTypes.RepayResult memory result) {
        vm.prank(borrower);
        usdc.transfer(address(vault), amount);
        vm.startPrank(manager);
        result = ledger.allocate(id, amount);
        vault.onRepayment(id, result);
        vm.stopPrank();
    }

    function _request(address lp, uint256 shares, uint256 minimum) internal returns (uint256 id) {
        vm.prank(lp);
        return vault.requestWithdrawal(shares, minimum);
    }

    function _writeOff(GpuTypes.FacilityId id) internal {
        vm.prank(guardian);
        vault.writeOff(id);
    }

    function _roll() internal {
        vm.prank(guardian);
        vault.rollLossEpoch();
    }

    function test_queueLocksSharesAndCannotDoubleReserveOrTransferThem() public {
        uint256 shares = _deposit(lp1, 10_000e6);
        uint256 id = _request(lp1, shares / 2, 0);
        assertEq(vault.balanceOf(lp1), shares, "requests are NAV-exposed shares, not burned cash claims");
        assertEq(vault.lockedShares(1, lp1), shares / 2);
        assertEq(vault.totalShares(), shares);
        vm.startPrank(lp1);
        vm.expectRevert(abi.encodeWithSelector(LendingVaultV2.LockedShares.selector, shares, shares / 2));
        vault.requestWithdrawal(shares, 0);
        vm.expectRevert(abi.encodeWithSelector(LendingVaultV2.LockedShares.selector, shares, shares / 2));
        vault.transfer(lp2, shares);
        vault.approve(attacker, shares);
        vm.stopPrank();
        vm.prank(attacker);
        vm.expectRevert(abi.encodeWithSelector(LendingVaultV2.LockedShares.selector, shares, shares / 2));
        vault.transferFrom(lp1, attacker, shares);
        assertEq(vault.allowance(lp1, attacker), shares, "failed transfer cannot spend allowance");
        vm.prank(lp1);
        vault.cancelWithdrawal(id);
        assertEq(vault.lockedShares(1, lp1), 0);
        vm.prank(lp1);
        vault.transfer(lp2, shares);
        assertEq(vault.balanceOf(lp2), shares);
    }

    function test_pendingQueueBlocksEveryImmediateExitAndNewLoan() public {
        uint256 shares1 = _deposit(lp1, 10_000e6);
        uint256 shares2 = _deposit(lp2, 10_000e6);
        _draw(F1, 5000e6, 0);
        _request(lp1, shares1, 0);
        assertEq(vault.availableCash(), 0);
        assertEq(vault.liquidLpCash(), 15_000e6);
        assertEq(vault.nav(), 20_000e6, "queue priority cannot incorrectly shrink NAV");
        assertEq(vault.maxWithdraw(lp2), 0);
        vm.prank(lp2);
        vm.expectRevert(LendingVaultV2.WithdrawalQueueActive.selector);
        vault.withdraw(shares2, 0);
        vm.prank(manager);
        vm.expectRevert(LendingVaultV2.WithdrawalQueueActive.selector);
        vault.lend(F1, borrower, 1);
    }

    function test_partialFillCancelAndClaimAccountOnlyActualCash() public {
        uint256 shares = _deposit(lp1, 10_000e6);
        _draw(F1, 8000e6, 0);
        uint256 id = _request(lp1, shares, 0);
        (uint256 count, uint256 reserved) = vault.processWithdrawals(10);
        assertEq(count, 1);
        assertEq(reserved, 2000e6);
        ILendingVaultV2.WithdrawalRequest memory r = vault.withdrawalRequest(id);
        assertEq(r.sharesRemaining, shares * 8 / 10);
        assertEq(vault.balanceOf(lp1), r.sharesRemaining);
        assertEq(vault.lockedShares(1, lp1), r.sharesRemaining);
        assertEq(vault.totalWithdrawalReserved(), 2000e6);
        assertEq(vault.nav(), 8000e6);
        assertEq(vault.availableCash(), 0);
        vm.prank(lp1);
        vault.cancelWithdrawal(id);
        assertEq(vault.pendingWithdrawalShares(), 0);
        assertEq(vault.lockedShares(1, lp1), 0);
        assertEq(vault.totalWithdrawalReserved(), 2000e6, "cancel cannot mint a second cash refund");
        uint256 before = usdc.balanceOf(lp1);
        vm.prank(lp1);
        assertEq(vault.claimWithdrawal(id), 2000e6);
        assertEq(usdc.balanceOf(lp1) - before, 2000e6);
        assertEq(vault.nav(), 8000e6, "claim was already removed from NAV at fill");
        assertEq(vault.totalWithdrawalReserved(), 0);
        vm.prank(lp1);
        vm.expectRevert(LendingVaultV2.NoClaimableAssets.selector);
        vault.claimWithdrawal(id);
        vm.prank(lp1);
        vm.expectRevert(abi.encodeWithSelector(LendingVaultV2.NoPendingWithdrawal.selector, id));
        vault.cancelWithdrawal(id);
    }

    function test_twoOwnersFifoAndRefillAfterRealRepayment() public {
        uint256 shares1 = _deposit(lp1, 6000e6);
        uint256 shares2 = _deposit(lp2, 4000e6);
        _draw(F1, 8000e6, 0);
        uint256 id1 = _request(lp1, shares1, 0);
        uint256 id2 = _request(lp2, shares2, 0);
        vault.processWithdrawals(50);
        assertEq(vault.withdrawalRequest(id1).assetsReserved, 2000e6);
        assertEq(vault.withdrawalRequest(id2).assetsReserved, 0);
        _repay(F1, 5000e6);
        vault.processWithdrawals(50);
        assertEq(vault.withdrawalRequest(id1).sharesRemaining, 0);
        assertEq(vault.withdrawalRequest(id1).assetsReserved, 6000e6);
        assertEq(vault.withdrawalRequest(id2).assetsReserved, 1000e6);
        vm.prank(lp2);
        assertEq(vault.claimWithdrawal(id2), 1000e6);
        _repay(F1, 3000e6);
        vault.processWithdrawals(50);
        vm.prank(lp2);
        assertEq(vault.claimWithdrawal(id2), 3000e6, "incremental claims pay only new fills");
        vm.prank(lp1);
        assertEq(vault.claimWithdrawal(id1), 6000e6);
        assertEq(vault.nav(), 0);
        assertEq(vault.totalShares(), 0);
        assertEq(vault.totalWithdrawalReserved(), 0);
        assertEq(usdc.balanceOf(address(vault)), 0);
        assertEq(ledger.legalDebtAt(F1, uint64(block.timestamp)), 0);
    }

    function test_reservedClaimsCannotBeLentOrDirectlyWithdrawnAfterQueueEmpties() public {
        uint256 s1 = _deposit(lp1, 6000e6);
        uint256 s2 = _deposit(lp2, 4000e6);
        _draw(F1, 3000e6, 0);
        _request(lp1, s1, 0);
        vault.processWithdrawals(1);
        assertEq(vault.pendingWithdrawalShares(), 0);
        assertEq(vault.totalWithdrawalReserved(), 6000e6);
        assertEq(vault.availableCash(), 1000e6);
        vm.prank(lp2);
        vm.expectRevert(abi.encodeWithSelector(ILendingVaultV2.InsufficientCash.selector, 4000e6, 1000e6));
        vault.withdraw(s2, 0);
        vm.prank(manager);
        vm.expectRevert(abi.encodeWithSelector(ILendingVaultV2.InsufficientCash.selector, 1001e6, 1000e6));
        vault.lend(F1, borrower, 1001e6);
        assertEq(vault.nav(), 4000e6);
    }

    function test_unfilledQueueBearsSameImpairmentAsRemainingLp() public {
        uint256 s1 = _deposit(lp1, 5000e6);
        uint256 s2 = _deposit(lp2, 5000e6);
        _draw(F1, 8000e6, 0);
        uint256 id = _request(lp1, s1, 0);
        vm.prank(guardian);
        vault.recognizeImpairment(F1, 4000e6);
        uint256 expected = vault.previewWithdraw(s1);
        assertApproxEqAbs(expected, 3000e6, 1);
        assertEq(vault.previewWithdraw(s2), expected);
        vault.processWithdrawals(1);
        assertLe(vault.withdrawalRequest(id).assetsReserved, 2000e6);
        assertGt(vault.withdrawalRequest(id).sharesRemaining, 0);
        assertApproxEqAbs(vault.previewWithdraw(vault.balanceOf(lp2)), expected, 1);
        assertEq(ledger.legalDebtAt(F1, uint64(block.timestamp)), 8000e6);
    }

    function test_minAssetsBlocksLossFillUntilOwnerCancelsOrDeadlineExpires() public {
        uint256 s1 = _deposit(lp1, 5000e6);
        uint256 s2 = _deposit(lp2, 5000e6);
        _draw(F1, 8000e6, 0);
        uint256 id1 = _request(lp1, s1, 5000e6);
        uint256 id2 = _request(lp2, s2, 0);
        vm.prank(guardian);
        vault.recognizeImpairment(F1, 2000e6);
        (uint256 count, uint256 cash) = vault.processWithdrawals(50);
        assertEq(count, 0);
        assertEq(cash, 0);
        assertEq(vault.withdrawalRequest(id2).assetsReserved, 0, "minAssets head cannot be leapfrogged");
        vm.prank(lp1);
        vault.cancelWithdrawal(id1);
        vault.processWithdrawals(50);
        assertGt(vault.withdrawalRequest(id2).assetsReserved, 0);
    }

    function test_deadlineAutomaticallyUnlocksBlockedHeadAndBoundsProcessing() public {
        uint256 s1 = _deposit(lp1, 5000e6);
        uint256 s2 = _deposit(lp2, 5000e6);
        _draw(F1, 8000e6, 0);
        uint256 id1 = _request(lp1, s1, 5000e6);
        vm.warp(block.timestamp + 1 days);
        uint256 id2 = _request(lp2, s2, 0);
        vm.prank(guardian);
        vault.recognizeImpairment(F1, 2000e6);
        vm.warp(vault.withdrawalRequest(id1).expiresAt);
        vault.processWithdrawals(1);
        assertTrue(vault.withdrawalRequest(id1).cancelled);
        assertEq(vault.lockedShares(1, lp1), 0);
        assertEq(vault.withdrawalRequest(id2).assetsReserved, 0, "expired entries consume processing budget");
        vault.processWithdrawals(1);
        assertGt(vault.withdrawalRequest(id2).assetsReserved, 0);
        vm.expectRevert(LendingVaultV2.InvalidProcessLimit.selector);
        vault.processWithdrawals(0);
        vm.expectRevert(LendingVaultV2.InvalidProcessLimit.selector);
        vault.processWithdrawals(51);
    }

    function test_unknownUnauthorizedAndInvalidRequestsFailClosed() public {
        uint256 s1 = _deposit(lp1, 100e6);
        vm.prank(lp1);
        vm.expectRevert(ILendingVaultV2.ZeroShares.selector);
        vault.requestWithdrawal(0, 0);
        vm.prank(lp1);
        vm.expectRevert(abi.encodeWithSelector(ILendingVaultV2.SlippageExceeded.selector, 100e6, 101e6));
        vault.requestWithdrawal(s1, 101e6);
        uint256 id = _request(lp1, s1, 0);
        vm.prank(attacker);
        vm.expectRevert(abi.encodeWithSelector(LendingVaultV2.NotWithdrawalOwner.selector, attacker));
        vault.cancelWithdrawal(id);
        vm.prank(attacker);
        vm.expectRevert(abi.encodeWithSelector(LendingVaultV2.NotWithdrawalOwner.selector, attacker));
        vault.claimWithdrawal(id);
        vm.expectRevert(abi.encodeWithSelector(LendingVaultV2.UnknownWithdrawal.selector, 77));
        vault.withdrawalRequest(77);
        vm.prank(lp1);
        vm.expectRevert(LendingVaultV2.NoClaimableAssets.selector);
        vault.claimWithdrawal(id);
    }

    function test_fundedClaimSurvivesLaterLossAndEpochRollover() public {
        uint256 s1 = _deposit(lp1, 10_000e6);
        _draw(F1, 8000e6, 0);
        uint256 id = _request(lp1, s1, 0);
        vault.processWithdrawals(1);
        uint256 remaining = vault.balanceOf(lp1);
        _writeOff(F1);
        assertEq(vault.nav(), 0);
        _roll();
        assertEq(vault.currentEpoch(), 2);
        assertEq(vault.sharesOfEpoch(1, lp1), remaining);
        assertEq(vault.closedEpochShares(1), remaining);
        assertEq(vault.totalWithdrawalReserved(), 2000e6);
        _deposit(lp2, 5000e6);
        vm.prank(lp1);
        assertEq(vault.claimWithdrawal(id), 2000e6);
        vm.prank(lp1);
        vault.cancelWithdrawal(id);
        assertEq(vault.sharesOfEpoch(1, lp1), remaining, "old cancellation cannot erase recovery rights");
        assertEq(vault.pendingWithdrawalShares(), 0);
        assertEq(vault.nav(), 5000e6);
        _repay(F1, 400e6);
        assertEq(vault.recoveryClaimable(1, lp1), 400e6);
        assertEq(vault.recoveryClaimable(1, lp2), 0);
        vm.prank(lp1);
        assertEq(vault.claimEpochRecovery(1), 400e6);
        assertEq(vault.nav(), 5000e6);
    }

    function test_oldPendingRequestsCannotBlockNewEpochQueue() public {
        uint256 s1 = _deposit(lp1, 10_000e6);
        _draw(F1, 10_000e6, 0);
        uint256 oldId = _request(lp1, s1, 0);
        _writeOff(F1);
        _roll();
        uint256 s2 = _deposit(lp2, 5000e6);
        uint256 newId = _request(lp2, s2, 0);
        vault.processWithdrawals(1);
        assertEq(vault.withdrawalRequest(newId).assetsReserved, 5000e6);
        assertEq(vault.withdrawalRequest(oldId).assetsReserved, 0);
        assertEq(vault.sharesOfEpoch(1, lp1), s1);
        vm.prank(lp1);
        vault.cancelWithdrawal(oldId);
        assertEq(vault.pendingWithdrawalShares(), 0);
    }

    function test_frozenBalancesAndAllowancesDoNotMigrateIntoNewEpoch() public {
        uint256 s1 = _deposit(lp1, 10_000e6);
        vm.prank(lp1);
        vault.approve(attacker, type(uint256).max);
        _draw(F1, 10_000e6, 0);
        _writeOff(F1);
        _roll();
        uint256 s2 = _deposit(lp1, 1000e6);
        assertEq(vault.sharesOfEpoch(1, lp1), s1);
        assertEq(vault.balanceOf(lp1), s2);
        assertEq(vault.allowance(lp1, attacker), 0);
        vm.prank(attacker);
        vm.expectRevert(ILendingVaultV2.ZeroShares.selector);
        vault.transferFrom(lp1, attacker, 1);
        vm.prank(lp1);
        vault.transfer(lp2, s2);
        assertEq(vault.sharesOfEpoch(1, lp1), s1, "new share transfer cannot mutate old snapshot");
        assertEq(vault.sharesOfEpoch(1, lp2), 0);
    }

    function test_partialLossOrImpairmentCannotBeUsedForForcedEpochReset() public {
        _deposit(lp1, 10_000e6);
        _draw(F1, 10_000e6, 0);
        vm.prank(guardian);
        vault.recognizeImpairment(F1, 10_000e6);
        assertEq(vault.nav(), 0);
        vm.prank(guardian);
        vm.expectRevert(LendingVaultV2.EpochNotFullyWrittenOff.selector);
        vault.rollLossEpoch();
        vm.prank(attacker);
        vm.expectRevert(abi.encodeWithSelector(LendingVaultV2.NotGuardian.selector, attacker));
        vault.rollLossEpoch();
        _writeOff(F1);
        _roll();
        vm.prank(guardian);
        vm.expectRevert(LendingVaultV2.EpochNotFullyWrittenOff.selector);
        vault.rollLossEpoch();
    }

    function test_zeroNavEpochCannotBeRecapitalizedBeforeExplicitRollover() public {
        uint256 shares = _deposit(lp1, 10_000e6);
        _draw(F1, 10_000e6, 0);
        _writeOff(F1);
        vm.startPrank(lp2);
        usdc.approve(address(vault), 5000e6);
        vm.expectRevert(LendingVaultV2.EpochRecapitalizationRequired.selector);
        vault.deposit(5000e6, 0);
        vm.stopPrank();
        vm.prank(lp1);
        vm.expectRevert(LendingVaultV2.EpochRecapitalizationRequired.selector);
        vault.withdraw(shares, 0);
        assertEq(vault.sharesOfEpoch(1, lp1), shares, "zero NAV cannot burn away recovery rights");
        _roll();
        _deposit(lp2, 5000e6);
        assertEq(vault.nav(), 5000e6);
    }

    function test_donationAfterZeroNavCannotBypassOrGriefRollover() public {
        _deposit(lp1, 10_000e6);
        _draw(F1, 10_000e6, 0);
        _writeOff(F1);
        vm.prank(borrower);
        usdc.transfer(address(vault), 1);
        assertTrue(vault.epochRolloverRequired());
        assertEq(vault.availableCash(), 0);
        vm.startPrank(lp2);
        usdc.approve(address(vault), 5000e6);
        vm.expectRevert(LendingVaultV2.EpochRecapitalizationRequired.selector);
        vault.deposit(5000e6, 0);
        vm.stopPrank();
        _roll();
        assertEq(vault.recoveryClaimable(1, lp1), 1);
        assertEq(ledger.legalDebtAt(F1, uint64(block.timestamp)), 10_000e6, "donation is not repayment");
        _deposit(lp2, 5000e6);
        assertEq(vault.nav(), 5000e6);
        assertEq(vault.recoveryClaimable(1, lp2), 0);
    }

    function test_recoveryBeforeRolloverRemainsOldHolderCash() public {
        _deposit(lp1, 10_000e6);
        _draw(F1, 10_000e6, 0);
        _writeOff(F1);
        _repay(F1, 1000e6);
        assertEq(vault.nav(), 1000e6);
        assertTrue(vault.epochRolloverRequired(), "incoming recovery cannot reopen entry into the old cohort");
        _roll();
        assertEq(vault.nav(), 0);
        assertEq(vault.recoveryClaimable(1, lp1), 1000e6);
        _deposit(lp2, 5000e6);
        assertEq(vault.availableCash(), 5000e6);
        vm.prank(lp1);
        assertEq(vault.claimEpochRecovery(1), 1000e6);
        assertEq(vault.nav(), 5000e6);
    }

    function test_interestFirstLateRecoveryAndBorrowerExcessStayOutsideNewNav() public {
        _deposit(lp1, 1000e6);
        _draw(F1, 1000e6, 1000);
        vm.warp(block.timestamp + 365 days);
        vm.prank(manager);
        ledger.freezeAccrual(F1); // GPU-041 must perform this through the authorized default workflow.
        _writeOff(F1);
        _roll();
        _deposit(lp2, 5000e6);
        GpuTypes.RepayResult memory first = _repay(F1, 50e6);
        assertEq(first.interestPaid, 50e6);
        assertEq(first.principalPaid, 0);
        assertEq(ledger.view_(F1).principal, 1000e6);
        assertEq(vault.recoveryClaimable(1, lp1), 50e6);
        assertEq(vault.nav(), 5000e6);
        GpuTypes.RepayResult memory second = _repay(F1, 1100e6);
        assertEq(second.applied, 1050e6);
        assertEq(second.excess, 50e6);
        assertEq(vault.totalRecoveryReserved(), 1100e6);
        assertEq(vault.totalBorrowerOwned(), 50e6);
        assertEq(vault.availableCash(), 5000e6);
        assertEq(vault.nav(), 5000e6);
        vm.prank(manager);
        vault.refundExcess(F1, borrower, 50e6);
        vm.prank(lp1);
        assertEq(vault.claimEpochRecovery(1), 1100e6);
        assertEq(usdc.balanceOf(address(vault)), 5000e6);
        assertEq(vault.nav(), 5000e6);
        vm.prank(lp1);
        vm.expectRevert(LendingVaultV2.NoClaimableAssets.selector);
        vault.claimEpochRecovery(1);
        vm.prank(lp2);
        vm.expectRevert(LendingVaultV2.NoClaimableAssets.selector);
        vault.claimEpochRecovery(1);
    }

    function test_repeatedLossEpochsKeepFacilityRecoveryCohortsSeparate() public {
        _deposit(lp1, 10_000e6);
        _draw(F1, 10_000e6, 0);
        _writeOff(F1);
        _roll();
        _deposit(lp2, 5000e6);
        _draw(F2, 5000e6, 0);
        _writeOff(F2);
        _roll();
        _deposit(lp3, 2000e6);
        _repay(F1, 700e6);
        _repay(F2, 300e6);
        assertEq(vault.writeOffEpoch(F1), 1);
        assertEq(vault.writeOffEpoch(F2), 2);
        assertEq(vault.recoveryClaimable(1, lp1), 700e6);
        assertEq(vault.recoveryClaimable(2, lp2), 300e6);
        assertEq(vault.recoveryClaimable(1, lp2), 0);
        assertEq(vault.recoveryClaimable(2, lp1), 0);
        assertEq(vault.recoveryClaimable(2, lp3), 0);
        assertEq(vault.nav(), 2000e6);
        vm.prank(lp1);
        vault.claimEpochRecovery(1);
        vm.prank(lp2);
        vault.claimEpochRecovery(2);
        assertEq(vault.availableCash(), 2000e6);
    }

    function test_currentEpochRecoveryAfterPartialLossStillIncreasesNav() public {
        _deposit(lp1, 10_000e6);
        _draw(F1, 8000e6, 0);
        _writeOff(F1);
        assertFalse(vault.epochRolloverRequired());
        assertEq(vault.nav(), 2000e6);
        _repay(F1, 400e6);
        assertEq(vault.nav(), 2400e6);
        assertEq(vault.totalRecoveryReserved(), 0);
    }

    function test_depositPauseDoesNotPauseCancelFillClaimOrLateRecovery() public {
        uint256 shares = _deposit(lp1, 100e6);
        uint256 id = _request(lp1, shares, 0);
        vm.prank(guardian);
        vault.setDepositsPaused(true);
        vault.processWithdrawals(1);
        vm.prank(lp1);
        assertEq(vault.claimWithdrawal(id), 100e6);
    }

    function test_outgoingTransferFeeCannotConsumeFundedWithdrawalClaim() public {
        QueueAdversarialToken token = new QueueAdversarialToken();
        LendingVaultV2 other = new LendingVaultV2(roles, ledger, address(token));
        token.mint(lp1, 100e6);
        vm.startPrank(lp1);
        token.approve(address(other), 100e6);
        uint256 shares = other.deposit(100e6, 0);
        uint256 id = other.requestWithdrawal(shares, 0);
        vm.stopPrank();
        other.processWithdrawals(1);
        token.configure(other, true, false);
        vm.prank(lp1);
        vm.expectRevert(abi.encodeWithSelector(LendingVaultV2.CashNotReceived.selector, 100e6, 100e6 - 1));
        other.claimWithdrawal(id);
        assertEq(other.withdrawalRequest(id).assetsClaimed, 0);
        assertEq(other.totalWithdrawalReserved(), 100e6);
        assertEq(token.balanceOf(address(other)), 100e6);
        token.configure(other, false, false);
        vm.prank(lp1);
        assertEq(other.claimWithdrawal(id), 100e6);
    }

    function test_claimTransferCallbackCannotReenterQueue() public {
        QueueAdversarialToken token = new QueueAdversarialToken();
        LendingVaultV2 other = new LendingVaultV2(roles, ledger, address(token));
        token.mint(lp1, 100e6);
        vm.startPrank(lp1);
        token.approve(address(other), 100e6);
        uint256 shares = other.deposit(100e6, 0);
        uint256 id = other.requestWithdrawal(shares, 0);
        vm.stopPrank();
        other.processWithdrawals(1);
        token.configure(other, false, true);
        vm.prank(lp1);
        other.claimWithdrawal(id);
        assertEq(token.callbackRevert(), abi.encodeWithSelector(LendingVaultV2.Reentrancy.selector));
        assertEq(token.balanceOf(lp1), 100e6);
        assertEq(other.totalWithdrawalReserved(), 0);
    }

    function testFuzz_cashConservationAcrossTwoQueuedOwners(uint256 a, uint256 b, uint256 lent) public {
        a = bound(a, 1e6, 100_000e6);
        b = bound(b, 1e6, 100_000e6);
        lent = bound(lent, 1, a + b - 1);
        uint256 s1 = _deposit(lp1, a);
        uint256 s2 = _deposit(lp2, b);
        _draw(F1, lent, 0);
        uint256 id1 = _request(lp1, s1, 0);
        uint256 id2 = _request(lp2, s2, 0);
        vault.processWithdrawals(50);
        assertEq(vault.nav() + vault.totalWithdrawalReserved(), a + b);
        assertLe(vault.totalWithdrawalReserved(), usdc.balanceOf(address(vault)));
        assertEq(vault.totalShares(), vault.balanceOf(lp1) + vault.balanceOf(lp2));
        _repay(F1, lent);
        vault.processWithdrawals(50);
        assertEq(vault.withdrawalRequest(id1).assetsReserved, a);
        assertEq(vault.withdrawalRequest(id2).assetsReserved, b);
        vm.prank(lp1);
        assertEq(vault.claimWithdrawal(id1), a);
        vm.prank(lp2);
        assertEq(vault.claimWithdrawal(id2), b);
        assertEq(vault.totalShares(), 0);
        assertEq(vault.nav(), 0);
        assertEq(vault.totalWithdrawalReserved(), 0);
        assertEq(usdc.balanceOf(address(vault)), 0);
    }

    function testFuzz_closedEpochProRataRoundingNeverLeaksToNewLp(uint256 a, uint256 b, uint256 recovery) public {
        a = bound(a, 1e6, 100_000e6);
        b = bound(b, 1e6, 100_000e6);
        recovery = bound(recovery, 2, a + b);
        _deposit(lp1, a);
        _deposit(lp2, b);
        _draw(F1, a + b, 0);
        _writeOff(F1);
        _roll();
        _deposit(lp3, 5000e6);
        _repay(F1, recovery);
        uint256 claim1 = vault.recoveryClaimable(1, lp1);
        uint256 claim2 = vault.recoveryClaimable(1, lp2);
        assertEq(claim1, recovery * a / (a + b));
        assertEq(claim2, recovery * b / (a + b));
        assertLe(claim1 + claim2, recovery);
        if (claim1 != 0) {
            vm.prank(lp1);
            vault.claimEpochRecovery(1);
        }
        if (claim2 != 0) {
            vm.prank(lp2);
            vault.claimEpochRecovery(1);
        }
        assertLe(vault.totalRecoveryReserved(), 1, "integer dust remains owned by old epoch");
        assertEq(vault.nav(), 5000e6);
        assertEq(vault.availableCash(), 5000e6);
        assertEq(vault.recoveryClaimable(1, lp3), 0);
        assertEq(vault.recoveryClaimable(1, lp1), 0);
        assertEq(vault.recoveryClaimable(1, lp2), 0);
    }
}
