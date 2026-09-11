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
            btcPriceUsd: BTC_PRICE_USD
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
}
