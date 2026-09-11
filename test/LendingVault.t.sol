// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import { Test, console } from "forge-std/Test.sol";
import { LendingVault } from "../contracts/LendingVault.sol";
import { ILendingVault } from "../contracts/interfaces/ILendingVault.sol";
import { MockERC20 } from "../contracts/mocks/MockERC20.sol";

/**
 * @title LendingVaultTest
 * @notice Tests for LendingVault contract
 */
contract LendingVaultTest is Test {
    LendingVault public vault;
    MockERC20 public stablecoin;

    address public owner = address(this);
    address public manager = address(0x1234);
    address public alice = address(0xA11CE);
    address public bob = address(0xB0B);
    address public borrower = address(0xB0FF);

    uint256 public constant INITIAL_BALANCE = 1_000_000e6; // 1M USDC
    uint256 public constant FIXED_APR_BPS = 1000; // 10% APR

    function setUp() public {
        // Deploy mock stablecoin (6 decimals like USDC)
        stablecoin = new MockERC20("USD Coin", "USDC", 6);

        // Deploy vault with 10% APR
        vault = new LendingVault(address(stablecoin), FIXED_APR_BPS);

        // Set manager
        vault.setManager(manager);

        // Mint tokens to test users
        stablecoin.mint(alice, INITIAL_BALANCE);
        stablecoin.mint(bob, INITIAL_BALANCE);
        stablecoin.mint(borrower, INITIAL_BALANCE);

        // Approve vault
        vm.prank(alice);
        stablecoin.approve(address(vault), type(uint256).max);

        vm.prank(bob);
        stablecoin.approve(address(vault), type(uint256).max);

        vm.prank(borrower);
        stablecoin.approve(address(vault), type(uint256).max);
    }

    // ============================================
    // Deployment Tests
    // ============================================

    function test_deployment() public view {
        assertEq(address(vault.asset()), address(stablecoin));
        assertEq(vault.manager(), manager);
        assertEq(vault.owner(), owner);
        assertEq(vault.fixedBorrowAPRBps(), FIXED_APR_BPS);
        assertEq(vault.totalShares(), 0);
        assertEq(vault.totalBorrowed(), 0);
    }

    function test_revert_zeroAsset() public {
        vm.expectRevert(ILendingVault.InvalidAddress.selector);
        new LendingVault(address(0), FIXED_APR_BPS);
    }

    // ============================================
    // Deposit Tests
    // ============================================

    function test_deposit() public {
        uint256 depositAmount = 100_000e6; // 100k USDC

        vm.prank(alice);
        uint256 shares = vault.deposit(depositAmount);

        assertEq(shares, depositAmount); // 1:1 initially
        assertEq(vault.sharesOf(alice), depositAmount);
        assertEq(vault.totalShares(), depositAmount);
        assertEq(stablecoin.balanceOf(address(vault)), depositAmount);
    }

    function test_deposit_multiple() public {
        // Alice deposits first
        vm.prank(alice);
        vault.deposit(100_000e6);

        // Bob deposits second
        vm.prank(bob);
        uint256 bobShares = vault.deposit(50_000e6);

        assertEq(bobShares, 50_000e6); // Still 1:1 (no interest yet)
        assertEq(vault.totalShares(), 150_000e6);
    }

    function test_deposit_revert_zeroAmount() public {
        vm.prank(alice);
        vm.expectRevert(ILendingVault.ZeroAmount.selector);
        vault.deposit(0);
    }

    // ============================================
    // Withdraw Tests
    // ============================================

    function test_withdraw() public {
        uint256 depositAmount = 100_000e6;

        vm.prank(alice);
        vault.deposit(depositAmount);

        uint256 balanceBefore = stablecoin.balanceOf(alice);

        vm.prank(alice);
        uint256 assets = vault.withdraw(depositAmount);

        assertEq(assets, depositAmount);
        assertEq(stablecoin.balanceOf(alice), balanceBefore + depositAmount);
        assertEq(vault.sharesOf(alice), 0);
    }

    function test_withdraw_revert_insufficientShares() public {
        vm.prank(alice);
        vault.deposit(100_000e6);

        vm.prank(alice);
        vm.expectRevert(ILendingVault.InsufficientShares.selector);
        vault.withdraw(200_000e6);
    }

    function test_withdraw_revert_zeroAmount() public {
        vm.prank(alice);
        vault.deposit(100_000e6);

        vm.prank(alice);
        vm.expectRevert(ILendingVault.ZeroAmount.selector);
        vault.withdraw(0);
    }

    // ============================================
    // Borrow Tests
    // ============================================

    function test_borrowFunds() public {
        // Alice provides liquidity
        vm.prank(alice);
        vault.deposit(100_000e6);

        uint256 borrowAmount = 50_000e6;
        uint256 borrowerBalanceBefore = stablecoin.balanceOf(borrower);

        vm.prank(manager);
        vault.borrowFunds(borrower, borrowAmount);

        assertEq(vault.totalBorrowed(), borrowAmount);
        assertEq(vault.availableLiquidity(), 50_000e6);
        assertEq(stablecoin.balanceOf(borrower), borrowerBalanceBefore + borrowAmount);
    }

    function test_borrowFunds_revert_onlyManager() public {
        vm.prank(alice);
        vault.deposit(100_000e6);

        vm.prank(alice);
        vm.expectRevert(ILendingVault.OnlyManager.selector);
        vault.borrowFunds(borrower, 50_000e6);
    }

    function test_borrowFunds_revert_insufficientLiquidity() public {
        vm.prank(alice);
        vault.deposit(100_000e6);

        vm.prank(manager);
        vm.expectRevert(ILendingVault.InsufficientLiquidity.selector);
        vault.borrowFunds(borrower, 150_000e6);
    }

    // ============================================
    // Repay Tests
    // ============================================

    function test_repayFunds() public {
        // Setup: deposit and borrow
        vm.prank(alice);
        vault.deposit(100_000e6);

        vm.prank(manager);
        vault.borrowFunds(borrower, 50_000e6);

        // Repay - manager needs to have tokens and approve vault
        uint256 repayAmount = 30_000e6;
        stablecoin.mint(manager, repayAmount);

        vm.startPrank(manager);
        stablecoin.approve(address(vault), repayAmount);
        vault.repayFunds(borrower, repayAmount);
        vm.stopPrank();

        assertEq(vault.totalBorrowed(), 20_000e6);
        assertEq(vault.availableLiquidity(), 80_000e6);
    }

    function test_repayFunds_revert_onlyManager() public {
        vm.prank(alice);
        vault.deposit(100_000e6);

        vm.prank(manager);
        vault.borrowFunds(borrower, 50_000e6);

        vm.prank(borrower);
        vm.expectRevert(ILendingVault.OnlyManager.selector);
        vault.repayFunds(borrower, 25_000e6);
    }

    // ============================================
    // Interest Tests
    // ============================================

    function test_interestAccrual() public {
        // Alice deposits
        vm.prank(alice);
        vault.deposit(100_000e6);

        // Borrow
        vm.prank(manager);
        vault.borrowFunds(borrower, 50_000e6);

        // Advance time by 1 year
        vm.warp(block.timestamp + 365 days);

        // Total assets should include interest
        // Interest = 50_000 * 10% * 1 year = 5_000
        uint256 totalAssets = vault.totalAssets();
        assertApproxEqRel(totalAssets, 105_000e6, 0.001e18); // Within 0.1%
    }

    function test_shareValueIncrease() public {
        // Alice deposits
        vm.prank(alice);
        vault.deposit(100_000e6);

        // Borrow
        vm.prank(manager);
        vault.borrowFunds(borrower, 50_000e6);

        // Advance time by 1 year
        vm.warp(block.timestamp + 365 days);

        // Alice's shares should now be worth more
        uint256 aliceAssets = vault.convertToAssets(vault.sharesOf(alice));
        assertApproxEqRel(aliceAssets, 105_000e6, 0.001e18);
    }

    function test_withdrawWithInterest() public {
        // Alice deposits
        vm.prank(alice);
        vault.deposit(100_000e6);

        // Borrow
        vm.prank(manager);
        vault.borrowFunds(borrower, 50_000e6);

        // Borrower repays with interest after 1 year
        vm.warp(block.timestamp + 365 days);

        // Repay full amount (principal + interest) - manager needs tokens
        uint256 repayAmount = 55_000e6; // 50k + 5k interest
        stablecoin.mint(manager, repayAmount);

        vm.startPrank(manager);
        stablecoin.approve(address(vault), repayAmount);
        vault.repayFunds(borrower, repayAmount);
        vm.stopPrank();

        // Alice withdraws
        uint256 balanceBefore = stablecoin.balanceOf(alice);
        uint256 aliceShares = vault.sharesOf(alice);
        vm.prank(alice);
        vault.withdraw(aliceShares);

        // Alice should get back more than deposited
        uint256 received = stablecoin.balanceOf(alice) - balanceBefore;
        assertApproxEqRel(received, 105_000e6, 0.001e18);
    }

    // ============================================
    // View Function Tests
    // ============================================

    function test_utilizationRate() public {
        vm.prank(alice);
        vault.deposit(100_000e6);

        assertEq(vault.utilizationRate(), 0);

        vm.prank(manager);
        vault.borrowFunds(borrower, 50_000e6);

        // 50% utilization = 5000 bps
        assertApproxEqAbs(vault.utilizationRate(), 5000, 1);
    }

    function test_borrowAPR() public view {
        assertEq(vault.borrowAPR(), FIXED_APR_BPS);
    }

    // ============================================
    // Admin Tests
    // ============================================

    function test_setManager() public {
        address newManager = address(0x9999);
        vault.setManager(newManager);
        assertEq(vault.manager(), newManager);
    }

    function test_setFixedAPR() public {
        uint256 newAPR = 2000; // 20%
        vault.setFixedAPR(newAPR);
        assertEq(vault.fixedBorrowAPRBps(), newAPR);
    }

    function test_transferOwnership() public {
        address newOwner = address(0x8888);
        vault.transferOwnership(newOwner);
        assertEq(vault.owner(), newOwner);
    }

    // ============================================
    // Edge Cases
    // ============================================

    function test_withdrawBlocked_whenBorrowed() public {
        vm.prank(alice);
        vault.deposit(100_000e6);

        vm.prank(manager);
        vault.borrowFunds(borrower, 80_000e6);

        // Alice tries to withdraw all - should fail (only 20k available)
        vm.prank(alice);
        vm.expectRevert(ILendingVault.InsufficientLiquidity.selector);
        vault.withdraw(100_000e6);

        // But can withdraw available amount
        vm.prank(alice);
        uint256 assets = vault.withdraw(20_000e6);
        assertEq(assets, 20_000e6);
    }
}
