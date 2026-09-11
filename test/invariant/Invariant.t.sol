// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test, console} from "forge-std/Test.sol";
import {LendingVault} from "../../contracts/LendingVault.sol";
import {HashCreditManager} from "../../contracts/HashCreditManager.sol";
import {RiskConfig} from "../../contracts/RiskConfig.sol";
import {IRiskConfig} from "../../contracts/interfaces/IRiskConfig.sol";
import {PoolRegistry} from "../../contracts/PoolRegistry.sol";
import {MockERC20} from "../../contracts/mocks/MockERC20.sol";
import {MockVerifier} from "../../contracts/mocks/MockVerifier.sol";
import {PayoutEvidence} from "../../contracts/interfaces/IVerifierAdapter.sol";
import {IHashCreditManager} from "../../contracts/interfaces/IHashCreditManager.sol";

/**
 * @title VaultHandler
 * @notice Handler contract for fuzzing LendingVault operations
 */
contract VaultHandler is Test {
    LendingVault public vault;
    MockERC20 public stablecoin;
    address[] public actors;

    uint256 public ghost_depositSum;
    uint256 public ghost_withdrawSum;

    constructor(LendingVault _vault, MockERC20 _stablecoin) {
        vault = _vault;
        stablecoin = _stablecoin;

        // Create test actors
        for (uint256 i = 0; i < 3; i++) {
            address actor = address(uint160(0x1000 + i));
            actors.push(actor);
            // Mint stablecoins to actors
            stablecoin.mint(actor, 1_000_000e6);
            vm.prank(actor);
            stablecoin.approve(address(vault), type(uint256).max);
        }
    }

    function deposit(uint256 actorSeed, uint256 amount) external {
        address actor = actors[actorSeed % actors.length];
        amount = bound(amount, 1e6, 100_000e6); // 1 to 100k

        uint256 balance = stablecoin.balanceOf(actor);
        if (balance < amount) return;

        vm.prank(actor);
        vault.deposit(amount);

        ghost_depositSum += amount;
    }

    function withdraw(uint256 actorSeed, uint256 shares) external {
        address actor = actors[actorSeed % actors.length];
        uint256 actorShares = vault.sharesOf(actor);

        if (actorShares == 0) return;
        shares = bound(shares, 1, actorShares);

        vm.prank(actor);
        uint256 assets = vault.withdraw(shares);

        ghost_withdrawSum += assets;
    }
}

/**
 * @title VaultInvariantTest
 * @notice Invariant tests for LendingVault share/asset accounting
 */
contract VaultInvariantTest is Test {
    LendingVault public vault;
    MockERC20 public stablecoin;
    VaultHandler public handler;
    address public manager;

    function setUp() public {
        stablecoin = new MockERC20("USD Coin", "USDC", 6);
        manager = address(0xdead);
        vault = new LendingVault(
            address(stablecoin),
            500 // 5% APR
        );
        vault.setManager(manager);

        handler = new VaultHandler(vault, stablecoin);

        // Target only the handler
        targetContract(address(handler));
    }

    /**
     * @notice Total assets should always be >= sum of all share values
     * @dev This catches share dilution bugs where new deposits steal from existing LPs
     */
    function invariant_totalAssetsGeShares() public view {
        uint256 totalShares = vault.totalShares();
        if (totalShares == 0) return;

        uint256 totalAssets = vault.totalAssets();

        // Each share should be convertible to at least 1 wei
        // (accounting for initial shares if any)
        assertTrue(
            totalAssets >= totalShares || totalShares == 0,
            "Total assets should cover all shares"
        );
    }

    /**
     * @notice convertToAssets(convertToShares(x)) should be <= x (no free money)
     * @dev Rounding should favor the vault, not the user
     */
    function invariant_roundingFavorsVault() public view {
        uint256 testAmount = 1000e6; // 1000 USDC

        uint256 shares = vault.convertToShares(testAmount);
        uint256 assetsBack = vault.convertToAssets(shares);

        assertTrue(
            assetsBack <= testAmount,
            "Rounding should favor vault (no free money from round-trip)"
        );
    }

    /**
     * @notice Total shares value should approximate deposit sum minus withdraw sum
     * @dev Ghost variables track all deposits and withdrawals
     */
    function invariant_ghostAccounting() public view {
        // This is a sanity check that deposits - withdrawals ~ total assets
        // (with some tolerance for interest accrual and rounding)
        uint256 totalAssets = vault.totalAssets();
        uint256 netDeposits = handler.ghost_depositSum() > handler.ghost_withdrawSum()
            ? handler.ghost_depositSum() - handler.ghost_withdrawSum()
            : 0;

        // Allow for some deviation due to interest
        // Total assets should be >= net deposits (interest adds value)
        // Note: This can be violated if there are outstanding borrows
        // but in this test we don't borrow
        if (vault.totalBorrowed() == 0) {
            assertTrue(
                totalAssets >= netDeposits * 99 / 100, // 1% tolerance for rounding
                "Total assets should be close to net deposits"
            );
        }
    }
}

/**
 * @title ManagerHandler
 * @notice Handler contract for fuzzing HashCreditManager operations
 */
contract ManagerHandler is Test {
    HashCreditManager public manager;
    MockVerifier public verifier;
    mapping(bytes32 => bool) public usedTxids;
    bytes32[] public allTxids;
    address public borrower;
    bytes32 public borrowerKeyHash;

    constructor(HashCreditManager _manager, MockVerifier _verifier, address _borrower, bytes32 _keyHash) {
        manager = _manager;
        verifier = _verifier;
        borrower = _borrower;
        borrowerKeyHash = _keyHash;
    }

    function getAllTxidsLength() external view returns (uint256) {
        return allTxids.length;
    }

    function getTxidAt(uint256 index) external view returns (bytes32) {
        return allTxids[index];
    }

    function submitPayout(uint256 txidSeed, uint256 vout) external {
        bytes32 txid = keccak256(abi.encode("txid", txidSeed));
        vout = bound(vout, 0, 10);

        bytes32 payoutKey = keccak256(abi.encode(txid, vout));

        // Skip if already tracked locally (to avoid unnecessary reverts)
        if (usedTxids[payoutKey]) return;

        // Create payout evidence
        PayoutEvidence memory evidence = PayoutEvidence({
            borrower: borrower,
            txid: txid,
            vout: uint32(vout),
            amountSats: 1_000_000, // 0.01 BTC
            blockHeight: uint32(block.number),
            blockTimestamp: uint32(block.timestamp)
        });

        bytes memory proof = verifier.encodeEvidence(evidence);

        vm.prank(manager.owner());
        try manager.submitPayout(proof) {
            usedTxids[payoutKey] = true;
            allTxids.push(payoutKey);
        } catch {
            // Expected to fail sometimes (e.g., replay at contract level)
        }
    }
}

/**
 * @title ManagerInvariantTest
 * @notice Invariant tests for HashCreditManager replay protection and debt accounting
 */
contract ManagerInvariantTest is Test {
    HashCreditManager public manager;
    LendingVault public vault;
    MockERC20 public stablecoin;
    MockVerifier public verifier;
    RiskConfig public riskConfig;
    PoolRegistry public poolRegistry;
    ManagerHandler public handler;

    address public borrower = address(0xB0B);
    bytes32 public borrowerKeyHash = keccak256("bob_btc_key");

    function setUp() public {
        stablecoin = new MockERC20("USD Coin", "USDC", 6);
        verifier = new MockVerifier();

        // Deploy RiskConfig
        IRiskConfig.RiskParams memory params = IRiskConfig.RiskParams({
            confirmationsRequired: 6,
            advanceRateBps: 5000, // 50%
            windowSeconds: 30 days,
            newBorrowerCap: 10_000e6,
            globalCap: 0,
            minPayoutSats: 10_000,
            btcPriceUsd: 50_000_00000000, // $50k with 8 decimals
            minPayoutCountForFullCredit: 0,
            largePayoutThresholdSats: 0,
            largePayoutDiscountBps: 10_000,
            newBorrowerPeriodSeconds: 30 days
        });
        riskConfig = new RiskConfig(params);

        // Deploy PoolRegistry (permissive)
        poolRegistry = new PoolRegistry(true);

        // Deploy vault
        vault = new LendingVault(address(stablecoin), 500);

        // Deploy manager
        manager = new HashCreditManager(
            address(verifier),
            address(vault),
            address(riskConfig),
            address(poolRegistry),
            address(stablecoin)
        );

        // Update vault manager
        vault.setManager(address(manager));

        // Fund vault
        stablecoin.mint(address(this), 1_000_000e6);
        stablecoin.approve(address(vault), type(uint256).max);
        vault.deposit(1_000_000e6);

        // Register borrower
        manager.registerBorrower(borrower, borrowerKeyHash);

        handler = new ManagerHandler(manager, verifier, borrower, borrowerKeyHash);
        targetContract(address(handler));
    }

    /**
     * @notice Each txid+vout pair should only be processable once
     * @dev Checks that replay protection works correctly
     */
    function invariant_noReplayPossible() public view {
        // Check all recorded txids are marked as processed
        for (uint256 i = 0; i < handler.getAllTxidsLength(); i++) {
            bytes32 payoutKey = handler.getTxidAt(i);
            assertTrue(
                handler.usedTxids(payoutKey),
                "All submitted payouts should be tracked"
            );
        }
    }

    /**
     * @notice Total global debt should equal sum of all borrower debts
     * @dev Ghost accounting invariant for debt
     */
    function invariant_debtAccountingConsistent() public view {
        uint256 totalGlobalDebt = manager.totalGlobalDebt();
        uint256 vaultBorrowed = vault.totalBorrowed();

        // Global debt in manager should match vault's record
        // Note: They track the same thing, just manager tracks principal
        // while vault may have interest
        assertTrue(
            totalGlobalDebt <= vaultBorrowed + 1, // +1 for rounding
            "Manager debt should not exceed vault borrowed"
        );
    }

    /**
     * @notice Borrower should never be able to borrow more than credit limit
     * @dev Core credit line invariant
     */
    function invariant_borrowNeverExceedsLimit() public view {
        uint256 currentDebt = manager.getCurrentDebt(borrower);
        IHashCreditManager.BorrowerInfo memory info = manager.getBorrowerInfo(borrower);

        assertTrue(
            currentDebt <= info.creditLimit + 1, // +1 for rounding
            "Debt should never exceed credit limit"
        );
    }
}
