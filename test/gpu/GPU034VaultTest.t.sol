// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import { Test } from "forge-std/Test.sol";
import { MockERC20 } from "../../contracts/mocks/MockERC20.sol";
import { GpuTypes } from "../../contracts/gpu/types/GpuTypes.sol";
import { ProtocolRoles } from "../../contracts/gpu/ProtocolRoles.sol";
import { DebtLedger } from "../../contracts/gpu/DebtLedger.sol";
import { LendingVaultV2 } from "../../contracts/gpu/LendingVaultV2.sol";
import { IDebtLedger } from "../../contracts/gpu/interfaces/IDebtLedger.sol";
import { ILendingVaultV2 } from "../../contracts/gpu/interfaces/ILendingVaultV2.sol";

/// @dev TEST_ONLY USDT-style token: transfer/transferFrom return nothing.
contract NonReturningToken {
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    function mint(address to, uint256 amount) external {
        balanceOf[to] += amount;
    }

    function approve(address spender, uint256 amount) external {
        allowance[msg.sender][spender] = amount;
    }

    function transfer(address to, uint256 amount) external {
        balanceOf[msg.sender] -= amount;
        balanceOf[to] += amount;
    }

    function transferFrom(address from, address to, uint256 amount) external {
        allowance[from][msg.sender] -= amount;
        balanceOf[from] -= amount;
        balanceOf[to] += amount;
    }
}

/// @dev TEST_ONLY token whose transferFrom returns false without reverting.
contract FalseReturningToken {
    mapping(address => uint256) public balanceOf;

    function mint(address to, uint256 amount) external {
        balanceOf[to] += amount;
    }

    function approve(address, uint256) external pure returns (bool) {
        return true;
    }

    function transferFrom(address, address, uint256) external pure returns (bool) {
        return false;
    }
}

/// @dev TEST_ONLY token whose transferFrom re-enters the vault (deposit) during a deposit.
contract ReenteringToken {
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;
    LendingVaultV2 public vault;
    bool public armed;
    bytes public lastRevert;

    function setVault(LendingVaultV2 v) external {
        vault = v;
    }

    function arm() external {
        armed = true;
    }

    function mint(address to, uint256 amount) external {
        balanceOf[to] += amount;
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
        allowance[from][msg.sender] -= amount;
        balanceOf[from] -= amount;
        balanceOf[to] += amount;
        if (armed) {
            armed = false;
            try vault.deposit(1, 0) { }
            catch (bytes memory r) {
                lastRevert = r;
            }
        }
        return true;
    }
}

/**
 * @title GPU034VaultTest
 * @notice LP book: virtual-offset shares, NAV from the ledger only, borrower money off-NAV, cash-limited
 *         withdrawals, impairment/write-off/recovery on the vault book, manager/guardian gating.
 */
contract GPU034VaultTest is Test {
    ProtocolRoles roles;
    DebtLedger ledger;
    MockERC20 usdc;
    LendingVaultV2 vault;

    address admin = address(0xAD);
    address guardian = address(0x6A);
    address underwriter = address(0x0DE);
    address manager = address(0x3A);
    address lp1 = address(0x11);
    address lp2 = address(0x12);
    address attacker = address(0xA7);
    address borrower = address(0xB0);
    address mallory = address(0xBAD);

    GpuTypes.FacilityId F1 = GpuTypes.FacilityId.wrap(keccak256("facility-1"));
    GpuTypes.FacilityId F2 = GpuTypes.FacilityId.wrap(keccak256("facility-2"));

    function setUp() public {
        vm.warp(1_800_000_000);
        roles = new ProtocolRoles(admin);
        ledger = new DebtLedger(roles);
        usdc = new MockERC20("USD Coin", "USDC", 6);
        vault = new LendingVaultV2(roles, ledger, address(usdc));
        vm.startPrank(admin);
        roles.grantRole(roles.GUARDIAN(), guardian);
        roles.grantRole(roles.UNDERWRITER(), underwriter);
        ledger.setWriter(manager, true);
        vault.setManager(manager, true);
        vm.stopPrank();
        usdc.mint(lp1, 1_000_000e6);
        usdc.mint(lp2, 1_000_000e6);
        usdc.mint(attacker, 1_000_000e6);
        usdc.mint(borrower, 1_000_000e6);
    }

    // ------------------------------------------------------------------ helpers

    function _terms(uint32 rateBps) internal pure returns (IDebtLedger.Terms memory) {
        return IDebtLedger.Terms({
            loanAsset: GpuTypes.AssetRef({ chainId: 102_031, token: address(0x05DC), decimals: 6 }),
            rateBps: rateBps,
            maturityAt: 0,
            termsVersionId: keccak256("terms-v1"),
            policyVersionId: keccak256("policy-v1"),
            executionProfile: GpuTypes.ExecutionProfile.LOCAL_MOCK,
            capitalizeUnpaidInterest: false
        });
    }

    function _deposit(address lp, uint256 assets) internal returns (uint256 shares) {
        vm.startPrank(lp);
        usdc.approve(address(vault), assets);
        shares = vault.deposit(assets, 0);
        vm.stopPrank();
    }

    /// @dev Manager flow: ledger open (if needed), recordDraw, vault.lend in one tx.
    function _draw(GpuTypes.FacilityId f, uint32 rateBps, uint256 amount, bool open) internal {
        vm.startPrank(manager);
        if (open) ledger.open(f, _terms(rateBps));
        ledger.recordDraw(f, amount);
        vault.lend(f, borrower, amount);
        vm.stopPrank();
    }

    /// @dev Manager flow: tokens arrive, ledger.allocate, vault.onRepayment.
    function _repay(GpuTypes.FacilityId f, uint256 amount) internal returns (GpuTypes.RepayResult memory r) {
        vm.prank(borrower);
        usdc.transfer(address(vault), amount);
        vm.startPrank(manager);
        r = ledger.allocate(f, amount);
        vault.onRepayment(f, r);
        vm.stopPrank();
    }

    // ------------------------------------------------------------------ shares / donation (AC-10, AR-08)

    function test_ticketVector_oneUnit_then100UsdcDonation_then200UsdcDeposit() public {
        uint256 attShares = _deposit(attacker, 1);
        assertEq(attShares, 1000, "1 unit -> 1000 shares via virtual offset");
        // donation: direct transfer, LP cash, not a repayment (no facility, no ledger change)
        vm.prank(attacker);
        usdc.transfer(address(vault), 100e6);
        assertEq(vault.nav(), 100e6 + 1);
        assertEq(ledger.facilityCount(), 0, "donation touched no facility");
        uint256 victimShares = _deposit(lp1, 200e6);
        uint256 victimRedeemable = vault.previewWithdraw(victimShares);
        uint256 attackerRedeemable = vault.previewWithdraw(attShares);
        assertGe(victimRedeemable, 199_900_000, "victim keeps >= 199.9 USDC");
        assertLe(attackerRedeemable, 100e6 + 1, "attacker cannot profit from the donation");
        uint256 victimLoss = 200e6 - victimRedeemable;
        uint256 attackerLoss = (100e6 + 1) - attackerRedeemable;
        assertGt(attackerLoss, victimLoss, "attack is unprofitable");
        // sum of redeemables never exceeds NAV + 1
        assertLe(victimRedeemable + attackerRedeemable, vault.nav() + 1);
    }

    function test_ac10_referenceVector_1000UsdcDonation() public {
        _deposit(attacker, 1);
        vm.prank(attacker);
        usdc.transfer(address(vault), 1000e6);
        uint256 victimShares = _deposit(lp1, 2000e6);
        assertGe(vault.previewWithdraw(victimShares), 1_999_000_000);
        assertLe(vault.previewWithdraw(1000), 1_001_000_000);
    }

    function test_donationIsNeverBorrowerRepayment() public {
        _deposit(lp1, 10_000e6);
        _draw(F1, 1000, 5000e6, true);
        uint256 debtBefore = ledger.legalDebtAt(F1, uint64(block.timestamp));
        vm.prank(borrower);
        usdc.transfer(address(vault), 500e6); // stray transfer, not routed through the manager
        _deposit(lp2, 1); // triggers absorption
        assertEq(ledger.legalDebtAt(F1, uint64(block.timestamp)), debtBefore, "legal debt unchanged");
        assertEq(vault.availableCash(), 5000e6 + 500e6 + 1, "stray cash is LP cash");
    }

    // ------------------------------------------------------------------ NAV composition

    function test_navIncludesLedgerInterestOnly_vaultHasNoRate() public {
        _deposit(lp1, 10_000e6);
        _draw(F1, 1000, 5000e6, true);
        assertEq(vault.nav(), 10_000e6, "cash 5000 + receivable 5000");
        vm.warp(block.timestamp + 365 days);
        assertEq(ledger.unpaidInterestAt(F1, uint64(block.timestamp)), 500e6);
        assertEq(vault.nav(), 10_500e6, "accrued-but-unrecorded interest read from the ledger");
        assertEq(vault.performingReceivables(), 5500e6);
        // the vault exposes no rate parameter: the only rate source is the ledger's terms
        (bool ok,) = address(vault).call(abi.encodeWithSignature("rateBps()"));
        assertFalse(ok);
        (ok,) = address(vault).call(abi.encodeWithSignature("setRate(uint32)", uint32(1)));
        assertFalse(ok);
    }

    function test_sharesSumEqualsTotalSupply_andRedeemablesReconcile() public {
        uint256 s1 = _deposit(lp1, 10_000e6);
        uint256 s2 = _deposit(lp2, 2500e6);
        _draw(F1, 1000, 6000e6, true);
        vm.warp(block.timestamp + 100 days);
        assertEq(vault.totalShares(), s1 + s2);
        assertEq(vault.balanceOf(lp1) + vault.balanceOf(lp2), vault.totalShares());
        uint256 sum = vault.previewWithdraw(s1) + vault.previewWithdraw(s2);
        assertLe(sum, vault.nav() + 1);
        assertGe(sum + 2, vault.nav(), "rounding residual <= 1 unit per conversion");
    }

    function test_borrowerRefundableExcess_isOffNav_andNotWithdrawable() public {
        uint256 s1 = _deposit(lp1, 10_000e6);
        _draw(F1, 1000, 5000e6, true);
        vm.warp(block.timestamp + 365 days); // interest 500
        GpuTypes.RepayResult memory r = _repay(F1, 6000e6); // debt 5,500 -> 500 excess
        assertEq(r.excess, 500e6);
        assertEq(vault.refundableOf(F1), 500e6);
        assertEq(vault.totalBorrowerOwned(), 500e6);
        assertEq(usdc.balanceOf(address(vault)), 11_000e6);
        assertEq(vault.availableCash(), 10_500e6, "excess excluded from LP cash");
        assertEq(vault.nav(), 10_500e6, "excess excluded from NAV; debt is zero");
        assertEq(ledger.legalDebtAt(F1, uint64(block.timestamp)), 0);
        // LP cannot withdraw the borrower's money even by redeeming everything
        vm.prank(lp1);
        uint256 got = vault.withdraw(s1, 0);
        assertLe(got, 10_500e6);
        assertEq(usdc.balanceOf(address(vault)), 11_000e6 - got);
        assertGe(usdc.balanceOf(address(vault)), 500e6, "refundable stays in the vault");
        // manager refunds it to the borrower; mallory cannot
        vm.prank(mallory);
        vm.expectRevert(abi.encodeWithSelector(ILendingVaultV2.OnlyManager.selector, mallory));
        vault.refundExcess(F1, mallory, 500e6);
        vm.prank(manager);
        vm.expectRevert(abi.encodeWithSelector(LendingVaultV2.RefundExceedsBalance.selector, 600e6, 500e6));
        vault.refundExcess(F1, borrower, 600e6);
        uint256 before = usdc.balanceOf(borrower);
        vm.prank(manager);
        vault.refundExcess(F1, borrower, 500e6);
        assertEq(usdc.balanceOf(borrower) - before, 500e6);
        assertEq(vault.totalBorrowerOwned(), 0);
    }

    function test_repayment_partialInterestFirst_navReflectsCashReplacingReceivable() public {
        _deposit(lp1, 10_000e6);
        _draw(F1, 1000, 5000e6, true);
        vm.warp(block.timestamp + 365 days);
        uint256 navBefore = vault.nav(); // 5000 cash + 5500 receivable
        assertEq(navBefore, 10_500e6);
        GpuTypes.RepayResult memory r = _repay(F1, 250e6);
        assertEq(r.interestPaid, 250e6);
        assertEq(r.principalPaid, 0);
        assertEq(r.newDebt, 5250e6);
        assertEq(vault.nav(), 10_500e6, "cash replaced receivable one-for-one");
        assertEq(vault.availableCash(), 5250e6);
    }

    // ------------------------------------------------------------------ withdrawals / slippage / cash

    function test_withdrawLimitedToCash_ac13() public {
        uint256 s1 = _deposit(lp1, 10_000e6);
        _draw(F1, 1000, 8000e6, true);
        vm.prank(underwriter);
        vault.recognizeImpairment(F1, 1000e6);
        assertEq(vault.nav(), 9000e6);
        assertEq(ledger.legalDebtAt(F1, uint64(block.timestamp)), 8000e6, "legal debt untouched");
        assertEq(vault.availableCash(), 2000e6);
        uint256 sharesFor5000 = (s1 * 5000e6) / 9000e6 + 1;
        vm.prank(lp1);
        vm.expectRevert();
        vault.withdraw(sharesFor5000, 0);
        assertEq(vault.maxWithdraw(lp1), 2000e6);
    }

    function test_previewMatchesActual_andSlippageGuards() public {
        _deposit(lp1, 10_000e6);
        _draw(F1, 1000, 4000e6, true);
        vm.warp(block.timestamp + 30 days);
        uint256 pv = vault.previewDeposit(1000e6);
        vm.startPrank(lp2);
        usdc.approve(address(vault), 1000e6);
        vm.expectRevert(abi.encodeWithSelector(ILendingVaultV2.SlippageExceeded.selector, pv, pv + 1));
        vault.deposit(1000e6, pv + 1);
        uint256 got = vault.deposit(1000e6, pv);
        assertEq(got, pv);
        uint256 pw = vault.previewWithdraw(got);
        vm.expectRevert(abi.encodeWithSelector(ILendingVaultV2.SlippageExceeded.selector, pw, pw + 1));
        vault.withdraw(got, pw + 1);
        uint256 assets = vault.withdraw(got, pw);
        assertEq(assets, pw);
        assertLe(assets, 1000e6, "round trip never mints value");
        vm.stopPrank();
    }

    function test_zeroDepositAndZeroShares() public {
        vm.startPrank(lp1);
        usdc.approve(address(vault), 1);
        vm.expectRevert(LendingVaultV2.ZeroAmount.selector);
        vault.deposit(0, 0);
        vm.expectRevert(ILendingVaultV2.ZeroShares.selector);
        vault.withdraw(0, 0);
        vm.stopPrank();
    }

    // ------------------------------------------------------------------ tokens

    function test_nonReturningToken_works() public {
        NonReturningToken usdt = new NonReturningToken();
        LendingVaultV2 v = new LendingVaultV2(roles, ledger, address(usdt));
        usdt.mint(lp1, 100e6);
        vm.startPrank(lp1);
        usdt.approve(address(v), 100e6);
        uint256 s = v.deposit(100e6, 0);
        assertGt(s, 0);
        uint256 a = v.withdraw(s, 0);
        assertLe(a, 100e6);
        assertGe(a, 100e6 - 1);
        vm.stopPrank();
    }

    function test_falseReturningToken_failsClosed() public {
        FalseReturningToken bad = new FalseReturningToken();
        LendingVaultV2 v = new LendingVaultV2(roles, ledger, address(bad));
        bad.mint(lp1, 100e6);
        vm.startPrank(lp1);
        bad.approve(address(v), 100e6);
        vm.expectRevert(LendingVaultV2.TransferFailed.selector);
        v.deposit(100e6, 0);
        vm.stopPrank();
    }

    function test_unsupportedToken_rejected() public {
        MockERC20 other = new MockERC20("Other", "OTH", 6);
        other.mint(lp1, 100e6);
        vm.startPrank(lp1);
        other.approve(address(vault), 100e6);
        // the vault only pulls its immutable asset; an unrelated approval yields no deposit
        vm.expectRevert(); // MockERC20 usdc transferFrom fails: no allowance
        vault.deposit(100e6, 0);
        vm.stopPrank();
        assertEq(vault.asset(), address(usdc));
        assertEq(vault.totalShares(), 0);
    }

    function test_reentrancyDuringDeposit_blocked() public {
        ReenteringToken tok = new ReenteringToken();
        LendingVaultV2 v = new LendingVaultV2(roles, ledger, address(tok));
        tok.setVault(v);
        tok.mint(lp1, 100e6);
        vm.startPrank(lp1);
        tok.approve(address(v), 100e6);
        tok.arm();
        v.deposit(100e6, 0);
        vm.stopPrank();
        assertEq(bytes4(tok.lastRevert()), LendingVaultV2.Reentrancy.selector);
        assertEq(v.totalShares(), 100e6 * 1000 / 1, "only the outer deposit minted");
    }

    // ------------------------------------------------------------------ manager gating / cash movement

    function test_lendRequiresManagerAndCash() public {
        _deposit(lp1, 1000e6);
        vm.prank(manager);
        ledger.open(F1, _terms(1000));
        vm.prank(mallory);
        vm.expectRevert(abi.encodeWithSelector(ILendingVaultV2.OnlyManager.selector, mallory));
        vault.lend(F1, mallory, 1);
        vm.prank(manager);
        vm.expectRevert(abi.encodeWithSelector(ILendingVaultV2.InsufficientCash.selector, 2000e6, 1000e6));
        vault.lend(F1, borrower, 2000e6);
    }

    function test_onRepaymentRequiresMeasuredCash() public {
        _deposit(lp1, 10_000e6);
        _draw(F1, 1000, 5000e6, true);
        GpuTypes.RepayResult memory fake = GpuTypes.RepayResult({
            requested: 1000e6,
            received: 1000e6,
            applied: 1000e6,
            feePaid: 0,
            interestPaid: 0,
            principalPaid: 1000e6,
            excess: 0,
            newDebt: 4000e6
        });
        vm.prank(mallory);
        vm.expectRevert(abi.encodeWithSelector(ILendingVaultV2.OnlyManager.selector, mallory));
        vault.onRepayment(F1, fake);
        vm.prank(manager);
        vm.expectRevert(abi.encodeWithSelector(LendingVaultV2.CashNotReceived.selector, 1000e6, 0));
        vault.onRepayment(F1, fake);
    }

    function test_depositPauseDoesNotPauseRepaymentsOrWithdrawals() public {
        uint256 s1 = _deposit(lp1, 10_000e6);
        _draw(F1, 1000, 5000e6, true);
        vm.prank(mallory);
        vm.expectRevert(abi.encodeWithSelector(LendingVaultV2.NotGuardian.selector, mallory));
        vault.setDepositsPaused(true);
        vm.prank(guardian);
        vault.setDepositsPaused(true);
        vm.startPrank(lp2);
        usdc.approve(address(vault), 1e6);
        vm.expectRevert(LendingVaultV2.Paused.selector);
        vault.deposit(1e6, 0);
        vm.stopPrank();
        GpuTypes.RepayResult memory r = _repay(F1, 1000e6);
        assertEq(r.principalPaid, 1000e6);
        vm.prank(lp1);
        uint256 got = vault.withdraw(s1 / 10, 0);
        assertGt(got, 0);
    }

    // ------------------------------------------------------------------ impairment / write-off / recovery

    function test_impairmentRolesAndCap() public {
        _deposit(lp1, 10_000e6);
        _draw(F1, 1000, 5000e6, true);
        vm.prank(mallory);
        vm.expectRevert(abi.encodeWithSelector(LendingVaultV2.NotGuardianOrUnderwriter.selector, mallory));
        vault.recognizeImpairment(F1, 1e6);
        vm.prank(manager);
        vm.expectRevert(abi.encodeWithSelector(LendingVaultV2.NotGuardianOrUnderwriter.selector, manager));
        vault.recognizeImpairment(F1, 1e6);
        vm.prank(guardian);
        vm.expectRevert(abi.encodeWithSelector(ILendingVaultV2.ImpairmentExceedsExposure.selector, 5001e6, 5000e6));
        vault.recognizeImpairment(F1, 5001e6);
        vm.prank(guardian);
        vault.recognizeImpairment(F1, 1000e6);
        assertEq(vault.nav(), 9000e6);
        vm.prank(underwriter);
        vault.reverseImpairment(F1, 400e6);
        assertEq(vault.nav(), 9400e6);
        assertEq(ledger.legalDebtAt(F1, uint64(block.timestamp)), 5000e6, "ledger untouched by the book");
    }

    function test_writeOff_releasesImpairment_debtPersists_recoveryAddsCash_ac09() public {
        uint256 s1 = _deposit(lp1, 10_000e6);
        _draw(F1, 1000, 10_000e6, true);
        vm.warp(block.timestamp + 365 days);
        vm.prank(guardian);
        vault.recognizeImpairment(F1, 2000e6);
        vm.prank(mallory);
        vm.expectRevert(abi.encodeWithSelector(LendingVaultV2.NotGuardian.selector, mallory));
        vault.writeOff(F1);
        vm.prank(guardian);
        vault.writeOff(F1);
        assertEq(vault.totalImpairment(), 0, "impairment released on write-off");
        assertEq(vault.nav(), 0, "AC-09: total loss");
        assertEq(ledger.legalDebtAt(F1, uint64(block.timestamp)), 11_000e6, "write-off is not forgiveness");
        vm.prank(guardian);
        vm.expectRevert(abi.encodeWithSelector(LendingVaultV2.FacilityWrittenOff.selector, F1));
        vault.recognizeImpairment(F1, 1);
        // GPU-042: explicit epoch rollover preserves old recovery rights instead of selling them to new LPs.
        vm.startPrank(lp2);
        usdc.approve(address(vault), 5000e6);
        vm.expectRevert(LendingVaultV2.EpochRecapitalizationRequired.selector);
        vault.deposit(5000e6, 0);
        vm.stopPrank();
        vm.prank(guardian);
        vault.rollLossEpoch();
        uint256 s2 = _deposit(lp2, 5000e6);
        assertEq(vault.nav(), 5000e6);
        assertGe(vault.previewWithdraw(s2), 4999e6);
        assertEq(vault.balanceOf(lp1), 0, "old shares are not current-epoch shares");
        assertEq(vault.sharesOfEpoch(1, lp1), s1, "old ownership remains intact");
        // The recovery reduces legal debt but belongs to old LPs, not the new epoch's NAV.
        vm.prank(borrower);
        usdc.transfer(address(vault), 400e6);
        vm.startPrank(manager);
        ledger.allocate(F1, 400e6);
        vault.recordRecovery(F1, 400e6);
        vm.stopPrank();
        assertEq(vault.nav(), 5000e6);
        assertEq(vault.totalRecoveryReserved(), 400e6);
        assertEq(vault.recoveryClaimable(1, lp1), 400e6);
        assertEq(vault.recoveryClaimable(1, lp2), 0);
        vm.prank(lp1);
        assertEq(vault.claimEpochRecovery(1), 400e6);
        assertEq(vault.nav(), 5000e6, "old recovery claim cannot drain new LP assets");
        assertEq(ledger.legalDebtAt(F1, uint64(block.timestamp)), 10_600e6);
        vm.prank(manager);
        vm.expectRevert(abi.encodeWithSelector(LendingVaultV2.FacilityNotWrittenOff.selector, F2));
        vault.recordRecovery(F2, 1);
        vm.prank(manager);
        vm.expectRevert(abi.encodeWithSelector(LendingVaultV2.FacilityWrittenOff.selector, F1));
        vault.lend(F1, borrower, 1);
    }

    function test_multipleFacilities_performingBookExcludesWrittenOffOnly() public {
        _deposit(lp1, 20_000e6);
        _draw(F1, 1000, 5000e6, true);
        _draw(F2, 2000, 3000e6, true);
        vm.warp(block.timestamp + 365 days);
        assertEq(vault.performingReceivables(), 5500e6 + 3600e6);
        vm.prank(guardian);
        vault.writeOff(F2);
        assertEq(vault.performingReceivables(), 5500e6);
        assertEq(vault.nav(), 12_000e6 + 5500e6);
    }
}
