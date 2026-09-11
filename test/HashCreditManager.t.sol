// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import { Test, console } from "forge-std/Test.sol";
import { HashCreditManager } from "../contracts/HashCreditManager.sol";
import { IHashCreditManager } from "../contracts/interfaces/IHashCreditManager.sol";
import { LendingVault } from "../contracts/LendingVault.sol";
import { RiskConfig } from "../contracts/RiskConfig.sol";
import { IRiskConfig } from "../contracts/interfaces/IRiskConfig.sol";
import { PoolRegistry } from "../contracts/PoolRegistry.sol";
import { MockVerifier } from "../contracts/mocks/MockVerifier.sol";
import { MockERC20 } from "../contracts/mocks/MockERC20.sol";
import { PayoutEvidence } from "../contracts/interfaces/IVerifierAdapter.sol";

/**
 * @title HashCreditManagerTest
 * @notice Comprehensive tests for HashCreditManager
 */
contract HashCreditManagerTest is Test {
    HashCreditManager public manager;
    LendingVault public vault;
    RiskConfig public riskConfig;
    PoolRegistry public poolRegistry;
    MockVerifier public verifier;
    MockERC20 public stablecoin;

    address public owner = address(this);
    address public alice = address(0xA11CE);
    address public bob = address(0xB0B);

    // BTC payout key hash (mock)
    bytes32 public aliceBtcKeyHash = keccak256("alice_btc_address");
    bytes32 public bobBtcKeyHash = keccak256("bob_btc_address");

    // Test constants
    uint64 constant BTC_PRICE_USD = 50_000_00000000; // $50,000 with 8 decimals
    uint32 constant ADVANCE_RATE_BPS = 5000; // 50%
    uint32 constant WINDOW_SECONDS = 30 days;
    uint128 constant NEW_BORROWER_CAP = 10_000_000000; // $10,000 with 6 decimals
    uint64 constant MIN_PAYOUT_SATS = 10000; // 0.0001 BTC

    function setUp() public {
        // Deploy stablecoin
        stablecoin = new MockERC20("USD Coin", "USDC", 6);

        // Deploy verifier
        verifier = new MockVerifier();

        // Deploy risk config
        IRiskConfig.RiskParams memory params = IRiskConfig.RiskParams({
            confirmationsRequired: 6,
            advanceRateBps: ADVANCE_RATE_BPS,
            windowSeconds: WINDOW_SECONDS,
            newBorrowerCap: NEW_BORROWER_CAP,
            globalCap: 0, // No global cap
            minPayoutSats: MIN_PAYOUT_SATS,
            btcPriceUsd: BTC_PRICE_USD,
            minPayoutCountForFullCredit: 0, // Disabled for tests
            largePayoutThresholdSats: 0, // Disabled for tests
            largePayoutDiscountBps: 10_000, // 100% (no discount)
            newBorrowerPeriodSeconds: WINDOW_SECONDS // Same as window for backwards compat
        });
        riskConfig = new RiskConfig(params);

        // Deploy pool registry (permissive mode for MVP)
        poolRegistry = new PoolRegistry(true);

        // Deploy vault
        vault = new LendingVault(address(stablecoin), 1000); // 10% APR

        // Deploy manager
        manager = new HashCreditManager(
            address(verifier),
            address(vault),
            address(riskConfig),
            address(poolRegistry),
            address(stablecoin)
        );

        // Set manager on vault
        vault.setManager(address(manager));

        // Mint and deposit liquidity to vault
        stablecoin.mint(owner, 1_000_000_000000); // 1M USDC
        stablecoin.approve(address(vault), type(uint256).max);
        vault.deposit(1_000_000_000000);

        // Mint tokens to test users for repayments
        stablecoin.mint(alice, 100_000_000000);
        stablecoin.mint(bob, 100_000_000000);

        // Approve manager for repayments
        vm.prank(alice);
        stablecoin.approve(address(manager), type(uint256).max);

        vm.prank(bob);
        stablecoin.approve(address(manager), type(uint256).max);
    }

    // ============================================
    // Deployment Tests
    // ============================================

    function test_deployment() public view {
        assertEq(manager.owner(), owner);
        assertEq(manager.verifier(), address(verifier));
        assertEq(manager.vault(), address(vault));
        assertEq(manager.riskConfig(), address(riskConfig));
        assertEq(manager.poolRegistry(), address(poolRegistry));
        assertEq(manager.stablecoin(), address(stablecoin));
    }

    // ============================================
    // Borrower Registration Tests
    // ============================================

    function test_registerBorrower() public {
        manager.registerBorrower(alice, aliceBtcKeyHash);

        IHashCreditManager.BorrowerInfo memory info = manager.getBorrowerInfo(alice);
        assertEq(uint8(info.status), uint8(IHashCreditManager.BorrowerStatus.Active));
        assertEq(info.btcPayoutKeyHash, aliceBtcKeyHash);
        assertEq(info.totalRevenueSats, 0);
        assertEq(info.creditLimit, 0);
        assertEq(info.currentDebt, 0);
    }

    function test_registerBorrower_revert_duplicate() public {
        manager.registerBorrower(alice, aliceBtcKeyHash);

        vm.expectRevert(IHashCreditManager.BorrowerAlreadyRegistered.selector);
        manager.registerBorrower(alice, aliceBtcKeyHash);
    }

    function test_registerBorrower_revert_notOwner() public {
        vm.prank(alice);
        vm.expectRevert(IHashCreditManager.Unauthorized.selector);
        manager.registerBorrower(bob, bobBtcKeyHash);
    }

    // ============================================
    // Payout Submission Tests
    // ============================================

    function test_submitPayout() public {
        manager.registerBorrower(alice, aliceBtcKeyHash);

        // Create payout evidence
        PayoutEvidence memory evidence = PayoutEvidence({
            borrower: alice,
            txid: bytes32(uint256(1)),
            vout: 0,
            amountSats: 1_00000000, // 1 BTC
            blockHeight: 800000,
            blockTimestamp: uint32(block.timestamp)
        });

        bytes memory proof = verifier.encodeEvidence(evidence);
        manager.submitPayout(proof);

        IHashCreditManager.BorrowerInfo memory info = manager.getBorrowerInfo(alice);
        assertEq(info.totalRevenueSats, 1_00000000);
        assertEq(info.trailingRevenueSats, 1_00000000);

        // Credit limit = 1 BTC * $50,000 * 50% = $25,000
        // But capped at new borrower cap of $10,000
        assertEq(info.creditLimit, NEW_BORROWER_CAP);
    }

    function test_submitPayout_creditLimitCalculation() public {
        manager.registerBorrower(alice, aliceBtcKeyHash);

        // Advance time past new borrower period
        vm.warp(block.timestamp + WINDOW_SECONDS + 1);

        // Create payout evidence for 0.1 BTC
        PayoutEvidence memory evidence = PayoutEvidence({
            borrower: alice,
            txid: bytes32(uint256(1)),
            vout: 0,
            amountSats: 10000000, // 0.1 BTC
            blockHeight: 800000,
            blockTimestamp: uint32(block.timestamp)
        });

        bytes memory proof = verifier.encodeEvidence(evidence);
        manager.submitPayout(proof);

        IHashCreditManager.BorrowerInfo memory info = manager.getBorrowerInfo(alice);

        // Credit limit = 0.1 BTC * $50,000 * 50% = $2,500 = 2500_000000
        assertEq(info.creditLimit, 2500_000000);
    }

    function test_submitPayout_revert_replay() public {
        manager.registerBorrower(alice, aliceBtcKeyHash);

        PayoutEvidence memory evidence = PayoutEvidence({
            borrower: alice,
            txid: bytes32(uint256(1)),
            vout: 0,
            amountSats: 1_00000000,
            blockHeight: 800000,
            blockTimestamp: uint32(block.timestamp)
        });

        bytes memory proof = verifier.encodeEvidence(evidence);

        manager.submitPayout(proof);

        // Try to submit same payout again
        vm.expectRevert(IHashCreditManager.PayoutAlreadyProcessed.selector);
        manager.submitPayout(proof);
    }

    function test_submitPayout_revert_notRegistered() public {
        PayoutEvidence memory evidence = PayoutEvidence({
            borrower: alice,
            txid: bytes32(uint256(1)),
            vout: 0,
            amountSats: 1_00000000,
            blockHeight: 800000,
            blockTimestamp: uint32(block.timestamp)
        });

        bytes memory proof = verifier.encodeEvidence(evidence);

        vm.expectRevert(IHashCreditManager.BorrowerNotRegistered.selector);
        manager.submitPayout(proof);
    }

    function test_submitPayout_revert_zeroAmount() public {
        manager.registerBorrower(alice, aliceBtcKeyHash);

        PayoutEvidence memory evidence = PayoutEvidence({
            borrower: alice,
            txid: bytes32(uint256(1)),
            vout: 0,
            amountSats: 0,
            blockHeight: 800000,
            blockTimestamp: uint32(block.timestamp)
        });

        bytes memory proof = verifier.encodeEvidence(evidence);

        vm.expectRevert(IHashCreditManager.ZeroAmount.selector);
        manager.submitPayout(proof);
    }

    // ============================================
    // Borrow Tests
    // ============================================

    function test_borrow() public {
        _setupBorrowerWithCredit(alice, 1_00000000); // 1 BTC payout

        uint256 borrowAmount = 5000_000000; // $5,000

        uint256 balanceBefore = stablecoin.balanceOf(alice);

        vm.prank(alice);
        manager.borrow(borrowAmount);

        assertEq(stablecoin.balanceOf(alice), balanceBefore + borrowAmount);

        IHashCreditManager.BorrowerInfo memory info = manager.getBorrowerInfo(alice);
        assertEq(info.currentDebt, borrowAmount);
    }

    function test_borrow_revert_exceedsCreditLimit() public {
        _setupBorrowerWithCredit(alice, 1_00000000);

        // Try to borrow more than credit limit (capped at $10,000)
        vm.prank(alice);
        vm.expectRevert(IHashCreditManager.ExceedsCreditLimit.selector);
        manager.borrow(15000_000000); // $15,000
    }

    function test_borrow_revert_notRegistered() public {
        vm.prank(alice);
        vm.expectRevert(IHashCreditManager.BorrowerNotRegistered.selector);
        manager.borrow(1000_000000);
    }

    function test_borrow_revert_frozen() public {
        _setupBorrowerWithCredit(alice, 1_00000000);

        manager.freezeBorrower(alice);

        vm.prank(alice);
        vm.expectRevert(IHashCreditManager.BorrowerNotActive.selector);
        manager.borrow(1000_000000);
    }

    // ============================================
    // Repay Tests
    // ============================================

    function test_repay() public {
        _setupBorrowerWithCredit(alice, 1_00000000);

        vm.prank(alice);
        manager.borrow(5000_000000);

        uint256 repayAmount = 2000_000000; // $2,000

        vm.prank(alice);
        manager.repay(repayAmount);

        IHashCreditManager.BorrowerInfo memory info = manager.getBorrowerInfo(alice);
        assertEq(info.currentDebt, 3000_000000); // $5,000 - $2,000
    }

    function test_repay_full() public {
        _setupBorrowerWithCredit(alice, 1_00000000);

        vm.prank(alice);
        manager.borrow(5000_000000);

        vm.prank(alice);
        manager.repay(5000_000000);

        IHashCreditManager.BorrowerInfo memory info = manager.getBorrowerInfo(alice);
        assertEq(info.currentDebt, 0);
    }

    function test_repay_capped() public {
        _setupBorrowerWithCredit(alice, 1_00000000);

        vm.prank(alice);
        manager.borrow(5000_000000);

        // Try to repay more than debt
        vm.prank(alice);
        manager.repay(10000_000000); // Repay $10,000

        IHashCreditManager.BorrowerInfo memory info = manager.getBorrowerInfo(alice);
        assertEq(info.currentDebt, 0);
    }

    // ============================================
    // Freeze Tests
    // ============================================

    function test_freezeBorrower() public {
        manager.registerBorrower(alice, aliceBtcKeyHash);

        manager.freezeBorrower(alice);

        IHashCreditManager.BorrowerInfo memory info = manager.getBorrowerInfo(alice);
        assertEq(uint8(info.status), uint8(IHashCreditManager.BorrowerStatus.Frozen));
    }

    function test_unfreezeBorrower() public {
        manager.registerBorrower(alice, aliceBtcKeyHash);
        manager.freezeBorrower(alice);
        manager.unfreezeBorrower(alice);

        IHashCreditManager.BorrowerInfo memory info = manager.getBorrowerInfo(alice);
        assertEq(uint8(info.status), uint8(IHashCreditManager.BorrowerStatus.Active));
    }

    function test_frozenBorrower_canStillRepay() public {
        _setupBorrowerWithCredit(alice, 1_00000000);

        vm.prank(alice);
        manager.borrow(5000_000000);

        manager.freezeBorrower(alice);

        // Should still be able to repay
        vm.prank(alice);
        manager.repay(2000_000000);

        IHashCreditManager.BorrowerInfo memory info = manager.getBorrowerInfo(alice);
        assertEq(info.currentDebt, 3000_000000);
    }

    // ============================================
    // Admin Tests
    // ============================================

    function test_setVerifier() public {
        address newVerifier = address(0x9999);
        manager.setVerifier(newVerifier);
        assertEq(manager.verifier(), newVerifier);
    }

    function test_setVault() public {
        address newVault = address(0x8888);
        manager.setVault(newVault);
        assertEq(manager.vault(), newVault);
    }

    // ============================================
    // View Function Tests
    // ============================================

    function test_getAvailableCredit() public {
        _setupBorrowerWithCredit(alice, 1_00000000);

        // Credit limit capped at $10,000
        assertEq(manager.getAvailableCredit(alice), NEW_BORROWER_CAP);

        vm.prank(alice);
        manager.borrow(3000_000000);

        assertEq(manager.getAvailableCredit(alice), NEW_BORROWER_CAP - 3000_000000);
    }

    function test_isPayoutProcessed() public {
        manager.registerBorrower(alice, aliceBtcKeyHash);

        bytes32 txid = bytes32(uint256(1));
        uint32 vout = 0;

        assertFalse(manager.isPayoutProcessed(txid, vout));

        PayoutEvidence memory evidence = PayoutEvidence({
            borrower: alice,
            txid: txid,
            vout: vout,
            amountSats: 1_00000000,
            blockHeight: 800000,
            blockTimestamp: uint32(block.timestamp)
        });

        bytes memory proof = verifier.encodeEvidence(evidence);
        manager.submitPayout(proof);

        assertTrue(manager.isPayoutProcessed(txid, vout));
    }

    // ============================================
    // Griefing Prevention Tests
    // ============================================

    function test_griefingPrevention_verifierDirectCall() public {
        // Setup: register borrower
        manager.registerBorrower(alice, aliceBtcKeyHash);

        PayoutEvidence memory evidence = PayoutEvidence({
            borrower: alice,
            txid: bytes32(uint256(1)),
            vout: 0,
            amountSats: 1_00000000,
            blockHeight: 800000,
            blockTimestamp: uint32(block.timestamp)
        });

        bytes memory proof = verifier.encodeEvidence(evidence);

        // Attack: attacker calls verifier.verifyPayout() directly
        address attacker = makeAddr("attacker");
        vm.prank(attacker);
        verifier.verifyPayout(proof);

        // Verifier is stateless, so isPayoutProcessed still returns false
        assertFalse(verifier.isPayoutProcessed(evidence.txid, evidence.vout));

        // Legitimate submitPayout still works because manager handles replay protection
        manager.submitPayout(proof);

        // Now manager's processedPayouts is true
        assertTrue(manager.isPayoutProcessed(evidence.txid, evidence.vout));

        // Credit limit was updated correctly
        assertTrue(manager.getAvailableCredit(alice) > 0);
    }

    function test_replayProtectionOnlyInManager() public {
        manager.registerBorrower(alice, aliceBtcKeyHash);

        PayoutEvidence memory evidence = PayoutEvidence({
            borrower: alice,
            txid: bytes32(uint256(1)),
            vout: 0,
            amountSats: 1_00000000,
            blockHeight: 800000,
            blockTimestamp: uint32(block.timestamp)
        });

        bytes memory proof = verifier.encodeEvidence(evidence);

        // First submit succeeds
        manager.submitPayout(proof);

        // Second submit fails with PayoutAlreadyProcessed from manager
        vm.expectRevert(IHashCreditManager.PayoutAlreadyProcessed.selector);
        manager.submitPayout(proof);

        // But verifier itself doesn't track - always returns false
        assertFalse(verifier.isPayoutProcessed(evidence.txid, evidence.vout));
    }

    // ============================================
    // Interest Accrual Tests (T2.7)
    // ============================================

    function test_getCurrentDebt_includesInterest() public {
        _setupBorrowerWithCredit(alice, 1_00000000);

        vm.prank(alice);
        manager.borrow(5000_000000); // $5,000

        // Check initial debt equals principal
        assertEq(manager.getCurrentDebt(alice), 5000_000000);
        assertEq(manager.getAccruedInterest(alice), 0);

        // Advance time by 1 year (10% APR = $500 interest)
        vm.warp(block.timestamp + 365 days);

        // Interest = 5000 * 10% * 1 year = 500
        uint256 expectedInterest = 500_000000;
        assertApproxEqRel(manager.getAccruedInterest(alice), expectedInterest, 0.001e18);
        assertApproxEqRel(manager.getCurrentDebt(alice), 5500_000000, 0.001e18);
    }

    function test_repay_interestFirst() public {
        _setupBorrowerWithCredit(alice, 1_00000000);

        vm.prank(alice);
        manager.borrow(5000_000000);

        // Advance time by 1 year
        vm.warp(block.timestamp + 365 days);

        uint256 interest = manager.getAccruedInterest(alice);
        uint256 halfInterest = interest / 2;

        // Repay less than interest
        vm.prank(alice);
        manager.repay(halfInterest);

        // Principal should remain unchanged
        IHashCreditManager.BorrowerInfo memory info = manager.getBorrowerInfo(alice);
        assertEq(info.currentDebt, 5000_000000, "Principal should not change when only paying interest");

        // Accrued interest should reset (we paid half, timestamp updated)
        assertEq(manager.getAccruedInterest(alice), 0, "Interest should reset after repay");
    }

    function test_repay_interestAndPrincipal() public {
        _setupBorrowerWithCredit(alice, 1_00000000);

        vm.prank(alice);
        manager.borrow(5000_000000);

        // Advance time by 1 year
        vm.warp(block.timestamp + 365 days);

        uint256 totalDebt = manager.getCurrentDebt(alice);
        uint256 interest = manager.getAccruedInterest(alice);

        // Repay full debt (principal + interest)
        vm.prank(alice);
        manager.repay(totalDebt);

        IHashCreditManager.BorrowerInfo memory info = manager.getBorrowerInfo(alice);
        assertEq(info.currentDebt, 0, "Principal should be zero after full repay");
        assertEq(manager.getCurrentDebt(alice), 0, "Total debt should be zero");
    }

    function test_repay_overpayment_capped() public {
        _setupBorrowerWithCredit(alice, 1_00000000);

        vm.prank(alice);
        manager.borrow(5000_000000);

        // Advance time
        vm.warp(block.timestamp + 365 days);

        uint256 totalDebt = manager.getCurrentDebt(alice);
        uint256 balanceBefore = stablecoin.balanceOf(alice);

        // Try to repay more than total debt
        vm.prank(alice);
        manager.repay(totalDebt + 1000_000000);

        // Should only transfer totalDebt amount
        assertEq(stablecoin.balanceOf(alice), balanceBefore - totalDebt, "Should only repay actual debt");

        IHashCreditManager.BorrowerInfo memory info = manager.getBorrowerInfo(alice);
        assertEq(info.currentDebt, 0);
    }

    function test_borrow_compoundsInterestIntoPrincipal() public {
        _setupBorrowerWithCredit(alice, 1_00000000);

        vm.prank(alice);
        manager.borrow(5000_000000);

        // Advance time by 1 year
        vm.warp(block.timestamp + 365 days);

        uint256 accruedInterest = manager.getAccruedInterest(alice);

        // Borrow more - should compound interest into principal
        vm.prank(alice);
        manager.borrow(1000_000000);

        IHashCreditManager.BorrowerInfo memory info = manager.getBorrowerInfo(alice);
        // New principal = old principal + accrued interest + new borrow
        uint256 expectedPrincipal = 5000_000000 + accruedInterest + 1000_000000;
        assertApproxEqRel(info.currentDebt, expectedPrincipal, 0.001e18);

        // After compounding, accrued interest should be 0
        assertEq(manager.getAccruedInterest(alice), 0);
    }

    function test_getAvailableCredit_considersInterest() public {
        _setupBorrowerWithCredit(alice, 1_00000000);

        uint256 initialAvailable = manager.getAvailableCredit(alice);

        vm.prank(alice);
        manager.borrow(5000_000000);

        uint256 afterBorrowAvailable = manager.getAvailableCredit(alice);
        assertEq(afterBorrowAvailable, initialAvailable - 5000_000000);

        // Advance time - interest accrues
        vm.warp(block.timestamp + 365 days);

        uint256 afterInterestAvailable = manager.getAvailableCredit(alice);
        // Available credit should decrease by accrued interest
        assertLt(afterInterestAvailable, afterBorrowAvailable, "Available credit should decrease with interest");

        uint256 interest = manager.getAccruedInterest(alice);
        assertEq(afterInterestAvailable, afterBorrowAvailable - interest);
    }

    function test_vaultReceivesInterestOnRepay() public {
        _setupBorrowerWithCredit(alice, 1_00000000);

        vm.prank(alice);
        manager.borrow(5000_000000);

        // Record vault balance after borrow (reduced by borrowed amount)
        uint256 vaultBalanceAfterBorrow = stablecoin.balanceOf(address(vault));

        // Advance time
        vm.warp(block.timestamp + 365 days);

        uint256 totalDebt = manager.getCurrentDebt(alice);
        uint256 interest = manager.getAccruedInterest(alice);

        // Repay full debt (principal + interest)
        vm.prank(alice);
        manager.repay(totalDebt);

        uint256 vaultBalanceAfterRepay = stablecoin.balanceOf(address(vault));

        // Vault should receive principal + interest (the full repayment amount)
        uint256 received = vaultBalanceAfterRepay - vaultBalanceAfterBorrow;
        assertApproxEqRel(received, 5000_000000 + interest, 0.001e18);
        // Also verify the net gain is exactly the interest
        assertApproxEqRel(interest, 500_000000, 0.001e18);
    }

    // ============================================
    // Helper Functions
    // ============================================

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

    // ============================================
    // Trailing Window Tests (T2.9)
    // ============================================

    function test_trailingWindow_payoutExpires() public {
        manager.registerBorrower(alice, aliceBtcKeyHash);

        // Submit first payout at t=0
        PayoutEvidence memory evidence1 = PayoutEvidence({
            borrower: alice,
            txid: bytes32(uint256(1)),
            vout: 0,
            amountSats: 10_00000000, // 10 BTC
            blockHeight: 800000,
            blockTimestamp: uint32(block.timestamp)
        });
        manager.submitPayout(verifier.encodeEvidence(evidence1));

        IHashCreditManager.BorrowerInfo memory info1 = manager.getBorrowerInfo(alice);
        assertEq(info1.trailingRevenueSats, 10_00000000);
        assertEq(manager.getPayoutHistoryCount(alice), 1);

        // Advance time past the trailing window
        vm.warp(block.timestamp + WINDOW_SECONDS + 1);

        // Submit second payout - should trigger pruning of first payout
        PayoutEvidence memory evidence2 = PayoutEvidence({
            borrower: alice,
            txid: bytes32(uint256(2)),
            vout: 0,
            amountSats: 5_00000000, // 5 BTC
            blockHeight: 800001,
            blockTimestamp: uint32(block.timestamp)
        });
        manager.submitPayout(verifier.encodeEvidence(evidence2));

        IHashCreditManager.BorrowerInfo memory info2 = manager.getBorrowerInfo(alice);
        // Only the second payout should be in trailing window now
        assertEq(info2.trailingRevenueSats, 5_00000000, "First payout should have expired");
        assertEq(manager.getPayoutHistoryCount(alice), 1, "Old payout should be pruned");

        // Total revenue should include both (lifetime)
        assertEq(info2.totalRevenueSats, 15_00000000, "Total revenue should include all payouts");
    }

    function test_trailingWindow_creditLimitDecreasesAfterExpiry() public {
        manager.registerBorrower(alice, aliceBtcKeyHash);

        // Advance time past new borrower period first
        vm.warp(block.timestamp + WINDOW_SECONDS + 1);

        // Submit payout
        PayoutEvidence memory evidence = PayoutEvidence({
            borrower: alice,
            txid: bytes32(uint256(1)),
            vout: 0,
            amountSats: 10_00000000, // 10 BTC
            blockHeight: 800000,
            blockTimestamp: uint32(block.timestamp)
        });
        manager.submitPayout(verifier.encodeEvidence(evidence));

        IHashCreditManager.BorrowerInfo memory info1 = manager.getBorrowerInfo(alice);
        // Credit limit = 10 BTC * $50,000 * 50% = $250,000 = 250000_000000
        assertEq(info1.creditLimit, 250_000_000000);

        // Advance time past window again
        vm.warp(block.timestamp + WINDOW_SECONDS + 1);

        // Submit small payout to trigger recalculation
        PayoutEvidence memory evidence2 = PayoutEvidence({
            borrower: alice,
            txid: bytes32(uint256(2)),
            vout: 0,
            amountSats: MIN_PAYOUT_SATS, // Minimum payout
            blockHeight: 800001,
            blockTimestamp: uint32(block.timestamp)
        });
        manager.submitPayout(verifier.encodeEvidence(evidence2));

        IHashCreditManager.BorrowerInfo memory info2 = manager.getBorrowerInfo(alice);
        // Credit limit should be much lower now (based only on MIN_PAYOUT_SATS)
        assertLt(info2.creditLimit, info1.creditLimit, "Credit limit should decrease after payout expires");
    }

    function test_trailingWindow_multiplePayoutsExpireAtOnce() public {
        manager.registerBorrower(alice, aliceBtcKeyHash);

        // Submit 3 payouts on the same day
        for (uint256 i = 1; i <= 3; i++) {
            PayoutEvidence memory evidence = PayoutEvidence({
                borrower: alice,
                txid: bytes32(i),
                vout: 0,
                amountSats: 1_00000000, // 1 BTC each
                blockHeight: 800000,
                blockTimestamp: uint32(block.timestamp)
            });
            manager.submitPayout(verifier.encodeEvidence(evidence));
        }

        assertEq(manager.getPayoutHistoryCount(alice), 3);

        IHashCreditManager.BorrowerInfo memory info1 = manager.getBorrowerInfo(alice);
        assertEq(info1.trailingRevenueSats, 3_00000000);

        // Advance time past window
        vm.warp(block.timestamp + WINDOW_SECONDS + 1);

        // Submit one more payout
        PayoutEvidence memory newEvidence = PayoutEvidence({
            borrower: alice,
            txid: bytes32(uint256(4)),
            vout: 0,
            amountSats: 1_00000000,
            blockHeight: 800001,
            blockTimestamp: uint32(block.timestamp)
        });
        manager.submitPayout(verifier.encodeEvidence(newEvidence));

        // All old payouts should be pruned
        assertEq(manager.getPayoutHistoryCount(alice), 1, "All old payouts should be pruned");

        IHashCreditManager.BorrowerInfo memory info2 = manager.getBorrowerInfo(alice);
        assertEq(info2.trailingRevenueSats, 1_00000000, "Only new payout in trailing");
        assertEq(info2.totalRevenueSats, 4_00000000, "Total includes all payouts");
    }

    // ============================================
    // Min Payout Filtering Tests (T2.9)
    // ============================================

    function test_minPayoutFilter_belowMinimumIgnored() public {
        manager.registerBorrower(alice, aliceBtcKeyHash);

        // Submit payout below minimum
        uint64 belowMinAmount = MIN_PAYOUT_SATS - 1; // 9999 sats
        PayoutEvidence memory evidence = PayoutEvidence({
            borrower: alice,
            txid: bytes32(uint256(1)),
            vout: 0,
            amountSats: belowMinAmount,
            blockHeight: 800000,
            blockTimestamp: uint32(block.timestamp)
        });
        manager.submitPayout(verifier.encodeEvidence(evidence));

        // Check payout was processed (replay protection)
        assertTrue(manager.isPayoutProcessed(bytes32(uint256(1)), 0), "Payout should be marked processed");

        // But credit should not increase
        IHashCreditManager.BorrowerInfo memory info = manager.getBorrowerInfo(alice);
        assertEq(info.trailingRevenueSats, 0, "Below-min payout should not count");
        assertEq(info.totalRevenueSats, 0, "Total revenue should be 0");
        assertEq(info.creditLimit, 0, "Credit limit should be 0");
        assertEq(manager.getPayoutHistoryCount(alice), 0, "No payout record added");
    }

    function test_minPayoutFilter_atMinimumCountsCorrectly() public {
        manager.registerBorrower(alice, aliceBtcKeyHash);

        // Submit payout at exactly minimum
        PayoutEvidence memory evidence = PayoutEvidence({
            borrower: alice,
            txid: bytes32(uint256(1)),
            vout: 0,
            amountSats: MIN_PAYOUT_SATS, // Exactly 10000 sats
            blockHeight: 800000,
            blockTimestamp: uint32(block.timestamp)
        });
        manager.submitPayout(verifier.encodeEvidence(evidence));

        IHashCreditManager.BorrowerInfo memory info = manager.getBorrowerInfo(alice);
        assertEq(info.trailingRevenueSats, MIN_PAYOUT_SATS, "At-min payout should count");
        assertGt(info.creditLimit, 0, "Should have some credit");
        assertEq(manager.getPayoutHistoryCount(alice), 1, "Payout record should be added");
    }

    function test_minPayoutFilter_replayStillBlocked() public {
        manager.registerBorrower(alice, aliceBtcKeyHash);

        // Submit payout below minimum
        PayoutEvidence memory evidence = PayoutEvidence({
            borrower: alice,
            txid: bytes32(uint256(1)),
            vout: 0,
            amountSats: MIN_PAYOUT_SATS - 1,
            blockHeight: 800000,
            blockTimestamp: uint32(block.timestamp)
        });
        bytes memory proof = verifier.encodeEvidence(evidence);
        manager.submitPayout(proof);

        // Try to submit again with same proof - should fail with replay error
        vm.expectRevert(IHashCreditManager.PayoutAlreadyProcessed.selector);
        manager.submitPayout(proof);
    }

    function test_minPayoutFilter_zeroMinAllowsAll() public {
        // Create new RiskConfig with minPayoutSats = 0
        IRiskConfig.RiskParams memory newParams = IRiskConfig.RiskParams({
            confirmationsRequired: 6,
            advanceRateBps: ADVANCE_RATE_BPS,
            windowSeconds: WINDOW_SECONDS,
            newBorrowerCap: NEW_BORROWER_CAP,
            globalCap: 0,
            minPayoutSats: 0, // No minimum
            btcPriceUsd: BTC_PRICE_USD,
            minPayoutCountForFullCredit: 0,
            largePayoutThresholdSats: 0,
            largePayoutDiscountBps: 10_000,
            newBorrowerPeriodSeconds: WINDOW_SECONDS
        });
        RiskConfig newRiskConfig = new RiskConfig(newParams);
        manager.setRiskConfig(address(newRiskConfig));

        manager.registerBorrower(alice, aliceBtcKeyHash);

        // Submit tiny payout
        PayoutEvidence memory evidence = PayoutEvidence({
            borrower: alice,
            txid: bytes32(uint256(1)),
            vout: 0,
            amountSats: 1, // Just 1 satoshi
            blockHeight: 800000,
            blockTimestamp: uint32(block.timestamp)
        });
        manager.submitPayout(verifier.encodeEvidence(evidence));

        IHashCreditManager.BorrowerInfo memory info = manager.getBorrowerInfo(alice);
        assertEq(info.trailingRevenueSats, 1, "1 sat payout should count when min is 0");
    }

    // ============================================
    // Max Payout Records (DoS Protection) Tests
    // ============================================

    function test_maxPayoutRecords_oldestRemovedWhenFull() public {
        manager.registerBorrower(alice, aliceBtcKeyHash);

        // Submit MAX_PAYOUT_RECORDS payouts (100)
        for (uint256 i = 1; i <= 100; i++) {
            PayoutEvidence memory evidence = PayoutEvidence({
                borrower: alice,
                txid: bytes32(i),
                vout: 0,
                amountSats: MIN_PAYOUT_SATS,
                blockHeight: 800000,
                blockTimestamp: uint32(block.timestamp)
            });
            manager.submitPayout(verifier.encodeEvidence(evidence));
        }

        assertEq(manager.getPayoutHistoryCount(alice), 100);

        // Get the first record's amount
        IHashCreditManager.PayoutRecord memory firstRecord = manager.getPayoutRecord(alice, 0);
        uint64 expectedAmount = firstRecord.effectiveAmountSats;

        // Submit one more - should evict the oldest
        PayoutEvidence memory newEvidence = PayoutEvidence({
            borrower: alice,
            txid: bytes32(uint256(101)),
            vout: 0,
            amountSats: MIN_PAYOUT_SATS * 2, // Different amount to distinguish
            blockHeight: 800001,
            blockTimestamp: uint32(block.timestamp)
        });
        manager.submitPayout(verifier.encodeEvidence(newEvidence));

        // Still at max
        assertEq(manager.getPayoutHistoryCount(alice), 100, "Should still be at max");

        // First record should now be the second original one
        IHashCreditManager.PayoutRecord memory newFirst = manager.getPayoutRecord(alice, 0);
        assertEq(newFirst.effectiveAmountSats, expectedAmount, "First record should be shifted");

        // Last record should be the new one
        IHashCreditManager.PayoutRecord memory lastRecord = manager.getPayoutRecord(alice, 99);
        assertEq(lastRecord.effectiveAmountSats, MIN_PAYOUT_SATS * 2, "Last should be new payout");
    }
}
