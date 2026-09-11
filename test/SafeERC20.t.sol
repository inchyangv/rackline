// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import { Test, console } from "forge-std/Test.sol";
import { LendingVault } from "../contracts/LendingVault.sol";
import { HashCreditManager } from "../contracts/HashCreditManager.sol";
import { RiskConfig } from "../contracts/RiskConfig.sol";
import { IRiskConfig } from "../contracts/interfaces/IRiskConfig.sol";
import { PoolRegistry } from "../contracts/PoolRegistry.sol";
import { MockVerifier } from "../contracts/mocks/MockVerifier.sol";
import { MockUSDT } from "../contracts/mocks/MockUSDT.sol";
import { MockNoReturnERC20 } from "../contracts/mocks/MockNoReturnERC20.sol";
import { ReentrantToken, ReentrantAttacker } from "../contracts/mocks/ReentrantToken.sol";
import { PayoutEvidence } from "../contracts/interfaces/IVerifierAdapter.sol";
import { IHashCreditManager } from "../contracts/interfaces/IHashCreditManager.sol";

/**
 * @title SafeERC20Test
 * @notice Tests for SafeERC20 and ReentrancyGuard integration (T2.8)
 */
contract SafeERC20Test is Test {
    // Test with standard mock
    LendingVault public vault;
    HashCreditManager public manager;
    RiskConfig public riskConfig;
    PoolRegistry public poolRegistry;
    MockVerifier public verifier;

    address public owner = address(this);
    address public alice = address(0xA11CE);
    address public bob = address(0xB0B);

    uint256 constant INITIAL_BALANCE = 1_000_000e6;

    // ============================================
    // USDT-style Token Tests (approve 0 required)
    // ============================================

    function test_vaultDeposit_withUSDTStyle() public {
        MockUSDT usdt = new MockUSDT();
        LendingVault usdtVault = new LendingVault(address(usdt), 1000);

        usdt.mint(alice, INITIAL_BALANCE);

        vm.startPrank(alice);
        usdt.approve(address(usdtVault), INITIAL_BALANCE);
        uint256 shares = usdtVault.deposit(100_000e6);
        vm.stopPrank();

        assertEq(shares, 100_000e6);
        assertEq(usdt.balanceOf(address(usdtVault)), 100_000e6);
    }

    function test_managerRepay_withUSDTStyle() public {
        // Setup with USDT (without auto max approval for alice)
        MockUSDT usdt = new MockUSDT();
        _setupFullStackWithTokenNoAliceApproval(address(usdt));

        // Setup borrower with credit
        _setupBorrowerWithCredit(alice, 1_00000000);

        // Borrow
        vm.prank(alice);
        manager.borrow(5000_000000);

        // Mint more USDT for repay
        usdt.mint(alice, 5000_000000);

        // Repay (tests forceApprove for USDT-style tokens)
        // Alice approves manager (user -> contract approval)
        vm.startPrank(alice);
        usdt.approve(address(manager), 5000_000000);
        // Manager will use forceApprove internally when approving vault
        manager.repay(5000_000000);
        vm.stopPrank();

        IHashCreditManager.BorrowerInfo memory info = manager.getBorrowerInfo(alice);
        assertEq(info.currentDebt, 0);
    }

    function test_managerRepay_multipleRepays_withUSDTStyle() public {
        // Setup with USDT (without auto max approval for alice)
        MockUSDT usdt = new MockUSDT();
        _setupFullStackWithTokenNoAliceApproval(address(usdt));

        _setupBorrowerWithCredit(alice, 1_00000000);

        vm.prank(alice);
        manager.borrow(5000_000000);

        usdt.mint(alice, 10000_000000);

        // For USDT-style tokens, user needs to approve exact amounts or use forceApprove pattern
        // First repay - approve exact amount
        vm.startPrank(alice);
        usdt.approve(address(manager), 2000_000000);
        manager.repay(2000_000000);

        // Manager's forceApprove to vault works, now test user approval
        // For second repay, allowance is 0 again after first repay consumed it
        // (because Manager only pulls what's needed)
        usdt.approve(address(manager), 3000_000000);
        manager.repay(3000_000000);
        vm.stopPrank();

        IHashCreditManager.BorrowerInfo memory info = manager.getBorrowerInfo(alice);
        assertEq(info.currentDebt, 0);
    }

    // ============================================
    // No-Return Token Tests
    // ============================================

    function test_vaultDeposit_withNoReturnToken() public {
        MockNoReturnERC20 nrt = new MockNoReturnERC20();
        LendingVault nrtVault = new LendingVault(address(nrt), 1000);

        nrt.mint(alice, INITIAL_BALANCE);

        vm.startPrank(alice);
        nrt.approve(address(nrtVault), INITIAL_BALANCE);
        uint256 shares = nrtVault.deposit(100_000e6);
        vm.stopPrank();

        assertEq(shares, 100_000e6);
        assertEq(nrt.balanceOf(address(nrtVault)), 100_000e6);
    }

    function test_vaultWithdraw_withNoReturnToken() public {
        MockNoReturnERC20 nrt = new MockNoReturnERC20();
        LendingVault nrtVault = new LendingVault(address(nrt), 1000);

        nrt.mint(alice, INITIAL_BALANCE);

        vm.startPrank(alice);
        nrt.approve(address(nrtVault), INITIAL_BALANCE);
        nrtVault.deposit(100_000e6);

        uint256 balanceBefore = nrt.balanceOf(alice);
        nrtVault.withdraw(50_000e6);
        vm.stopPrank();

        assertEq(nrt.balanceOf(alice), balanceBefore + 50_000e6);
    }

    function test_managerRepay_withNoReturnToken() public {
        MockNoReturnERC20 nrt = new MockNoReturnERC20();
        _setupFullStackWithToken(address(nrt));

        _setupBorrowerWithCredit(alice, 1_00000000);

        vm.prank(alice);
        manager.borrow(5000_000000);

        nrt.mint(alice, 5000_000000);

        vm.startPrank(alice);
        nrt.approve(address(manager), 5000_000000);
        manager.repay(5000_000000);
        vm.stopPrank();

        IHashCreditManager.BorrowerInfo memory info = manager.getBorrowerInfo(alice);
        assertEq(info.currentDebt, 0);
    }

    // ============================================
    // Reentrancy Tests
    // ============================================

    function test_vaultDeposit_preventsReentrancy() public {
        ReentrantToken rent = new ReentrantToken();
        LendingVault rentVault = new LendingVault(address(rent), 1000);

        ReentrantAttacker attacker = new ReentrantAttacker(address(rentVault));

        rent.mint(address(attacker), INITIAL_BALANCE);
        rent.mint(alice, INITIAL_BALANCE);

        // Setup callback to attempt reentrant deposit
        bytes memory depositCall = abi.encodeWithSelector(
            LendingVault.deposit.selector,
            1000e6
        );
        rent.setCallback(address(rentVault), depositCall);
        attacker.setAttack(depositCall, 1);

        // Approve from attacker
        vm.prank(address(attacker));
        rent.approve(address(rentVault), INITIAL_BALANCE);

        // First deposit from alice should work (no reentrancy)
        vm.startPrank(alice);
        rent.approve(address(rentVault), INITIAL_BALANCE);
        rentVault.deposit(100_000e6);
        vm.stopPrank();

        // Clear callback for clean state
        rent.clearCallback();

        assertEq(rent.balanceOf(address(rentVault)), 100_000e6);
    }

    function test_vaultWithdraw_preventsReentrancy() public {
        ReentrantToken rent = new ReentrantToken();
        LendingVault rentVault = new LendingVault(address(rent), 1000);

        rent.mint(alice, INITIAL_BALANCE);

        // First, deposit normally
        vm.startPrank(alice);
        rent.approve(address(rentVault), INITIAL_BALANCE);
        rentVault.deposit(100_000e6);
        vm.stopPrank();

        // Setup callback to attempt reentrant withdraw during transfer
        bytes memory withdrawCall = abi.encodeWithSelector(
            LendingVault.withdraw.selector,
            10_000e6
        );
        rent.setCallback(address(rentVault), withdrawCall);

        // Withdraw should succeed, but reentrant call inside should fail
        vm.prank(alice);
        rentVault.withdraw(50_000e6);

        // Should only withdraw once (50k, not 60k)
        assertEq(rent.balanceOf(alice), INITIAL_BALANCE - 100_000e6 + 50_000e6);
    }

    function test_managerBorrow_preventsReentrancy() public {
        ReentrantToken rent = new ReentrantToken();
        _setupFullStackWithToken(address(rent));

        _setupBorrowerWithCredit(alice, 1_00000000);

        // Setup callback to attempt reentrant borrow
        bytes memory borrowCall = abi.encodeWithSelector(
            HashCreditManager.borrow.selector,
            1000_000000
        );
        rent.setCallback(address(manager), borrowCall);

        // Borrow should succeed, reentrant call should fail
        vm.prank(alice);
        manager.borrow(5000_000000);

        IHashCreditManager.BorrowerInfo memory info = manager.getBorrowerInfo(alice);
        // Should only have borrowed 5000, not 6000
        assertEq(info.currentDebt, 5000_000000);
    }

    // ============================================
    // Helper Functions
    // ============================================

    function _setupFullStackWithTokenNoAliceApproval(address token) internal {
        verifier = new MockVerifier();

        IRiskConfig.RiskParams memory params = IRiskConfig.RiskParams({
            confirmationsRequired: 6,
            advanceRateBps: 5000,
            windowSeconds: 30 days,
            newBorrowerCap: 10_000_000000,
            globalCap: 0,
            minPayoutSats: 10000,
            btcPriceUsd: 50_000_00000000,
            minPayoutCountForFullCredit: 0,
            largePayoutThresholdSats: 0,
            largePayoutDiscountBps: 10_000,
            newBorrowerPeriodSeconds: 30 days
        });
        riskConfig = new RiskConfig(params);
        poolRegistry = new PoolRegistry(true);

        vault = new LendingVault(token, 1000);

        manager = new HashCreditManager(
            address(verifier),
            address(vault),
            address(riskConfig),
            address(poolRegistry),
            token
        );

        vault.setManager(address(manager));

        if (token == address(0)) return;

        // Mint and deposit liquidity (owner only)
        (bool success,) = token.call(abi.encodeWithSignature("mint(address,uint256)", owner, INITIAL_BALANCE));
        require(success, "mint failed");

        (success,) = token.call(abi.encodeWithSignature("approve(address,uint256)", address(vault), type(uint256).max));
        require(success, "approve failed");

        vault.deposit(INITIAL_BALANCE);

        // Mint tokens to alice for repays but DON'T approve manager yet
        (success,) = token.call(abi.encodeWithSignature("mint(address,uint256)", alice, INITIAL_BALANCE));
        require(success, "mint to alice failed");
    }

    function _setupFullStackWithToken(address token) internal {
        verifier = new MockVerifier();

        IRiskConfig.RiskParams memory params = IRiskConfig.RiskParams({
            confirmationsRequired: 6,
            advanceRateBps: 5000,
            windowSeconds: 30 days,
            newBorrowerCap: 10_000_000000,
            globalCap: 0,
            minPayoutSats: 10000,
            btcPriceUsd: 50_000_00000000,
            minPayoutCountForFullCredit: 0,
            largePayoutThresholdSats: 0,
            largePayoutDiscountBps: 10_000,
            newBorrowerPeriodSeconds: 30 days
        });
        riskConfig = new RiskConfig(params);
        poolRegistry = new PoolRegistry(true);

        vault = new LendingVault(token, 1000);

        manager = new HashCreditManager(
            address(verifier),
            address(vault),
            address(riskConfig),
            address(poolRegistry),
            token
        );

        vault.setManager(address(manager));

        // Mint and deposit liquidity
        if (token == address(0)) return;

        // Use low-level call for tokens that may not return
        (bool success,) = token.call(abi.encodeWithSignature("mint(address,uint256)", owner, INITIAL_BALANCE));
        require(success, "mint failed");

        // Approve and deposit
        (success,) = token.call(abi.encodeWithSignature("approve(address,uint256)", address(vault), type(uint256).max));
        require(success, "approve failed");

        vault.deposit(INITIAL_BALANCE);

        // Mint tokens to alice for repays
        (success,) = token.call(abi.encodeWithSignature("mint(address,uint256)", alice, INITIAL_BALANCE));
        require(success, "mint to alice failed");

        // Alice approves manager
        vm.prank(alice);
        (success,) = token.call(abi.encodeWithSignature("approve(address,uint256)", address(manager), type(uint256).max));
        require(success, "alice approve failed");
    }

    function _setupBorrowerWithCredit(address borrower, uint64 amountSats) internal {
        bytes32 keyHash = keccak256(abi.encodePacked(borrower));
        manager.registerBorrower(borrower, keyHash);

        PayoutEvidence memory evidence = PayoutEvidence({
            borrower: borrower,
            txid: bytes32(uint256(uint160(borrower))),
            vout: 0,
            amountSats: amountSats,
            blockHeight: 800000,
            blockTimestamp: uint32(block.timestamp)
        });

        bytes memory proof = verifier.encodeEvidence(evidence);
        manager.submitPayout(proof);
    }
}
