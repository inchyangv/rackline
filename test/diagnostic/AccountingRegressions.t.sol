// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import { Test } from "forge-std/Test.sol";
import { Vm } from "forge-std/Vm.sol";
import { HashCreditManager } from "../../contracts/HashCreditManager.sol";
import { IHashCreditManager } from "../../contracts/interfaces/IHashCreditManager.sol";
import { LendingVault } from "../../contracts/LendingVault.sol";
import { RiskConfig } from "../../contracts/RiskConfig.sol";
import { IRiskConfig } from "../../contracts/interfaces/IRiskConfig.sol";
import { PoolRegistry } from "../../contracts/PoolRegistry.sol";
import { BtcSpvVerifier } from "../../contracts/BtcSpvVerifier.sol";
import { CheckpointManager } from "../../contracts/CheckpointManager.sol";
import { MockVerifier } from "../../contracts/mocks/MockVerifier.sol";
import { MockERC20 } from "../../contracts/mocks/MockERC20.sol";
import { PayoutEvidence } from "../../contracts/interfaces/IVerifierAdapter.sol";

/**
 * @title AccountingRegressionsTest (GPU-002)
 * @notice Minimal reproduction vectors for known v1 accounting / attribution defects. Each vector records BOTH the
 * value
 *         v1 produces today (`observed`) and the value a correct ledger must produce (`correct`).
 *
 *         Default run (CI): asserts `observed == V1_OBSERVED` and `observed != CORRECT`, i.e. it pins
 *         the defect so any silent change of v1 behaviour is noticed. It never claims the defect is fixed.
 *
 *         RUN_RED_DIAGNOSTICS=true forge test --match-contract AccountingRegressionsTest:
 *         asserts `observed == CORRECT` and is expected to be RED against v1. The same constants are
 *         the acceptance expectations for the v2 ledger (GPU-034~036, 039, 029/031, 013).
 *
 *         Legacy contracts are not modified by this file.
 */
contract AccountingRegressionsTest is Test {
    HashCreditManager manager;
    LendingVault vault;
    RiskConfig riskConfig;
    PoolRegistry poolRegistry;
    MockVerifier verifier;
    MockERC20 usd;

    address alice = address(0xA11CE);
    address mallory = address(0xBAD);

    uint64 constant BTC_PRICE_USD = 5_000_000_000_000; // $50,000 (8 dp)
    uint32 constant ADVANCE_RATE_BPS = 5000;
    uint32 constant WINDOW = 30 days;
    uint128 constant NEW_BORROWER_CAP = 100_000_000_000; // $100,000 so caps do not mask the vectors
    uint256 constant LIQUIDITY = 1_000_000_000_000; // $1,000,000

    bool red;

    function setUp() public {
        red = vm.envOr("RUN_RED_DIAGNOSTICS", false);
        vm.warp(1_800_000_000); // fixed, far from zero so window arithmetic is meaningful

        usd = new MockERC20("USD", "USD", 6);
        verifier = new MockVerifier();
        riskConfig = new RiskConfig(
            IRiskConfig.RiskParams({
                confirmationsRequired: 6,
                advanceRateBps: ADVANCE_RATE_BPS,
                windowSeconds: WINDOW,
                newBorrowerCap: NEW_BORROWER_CAP,
                globalCap: 0,
                minPayoutSats: 10_000,
                btcPriceUsd: BTC_PRICE_USD,
                minPayoutCountForFullCredit: 0,
                largePayoutThresholdSats: 0,
                largePayoutDiscountBps: 10_000,
                newBorrowerPeriodSeconds: WINDOW
            })
        );
        poolRegistry = new PoolRegistry(true);
        vault = new LendingVault(address(usd), 1000); // 10% APR
        manager = new HashCreditManager(
            address(verifier), address(vault), address(riskConfig), address(poolRegistry), address(usd)
        );
        vault.setManager(address(manager));
        usd.mint(address(this), LIQUIDITY);
        usd.approve(address(vault), LIQUIDITY);
        vault.deposit(LIQUIDITY);
    }

    // ------------------------------------------------------------------ helpers

    /// @dev Pin the defect by default; assert the correct value in RED mode.
    function _vector(string memory id, uint256 observed, uint256 v1Observed, uint256 correct) internal {
        if (red) {
            assertEq(observed, correct, string.concat(id, ": correct expectation"));
        } else {
            assertEq(observed, v1Observed, string.concat(id, ": v1 observed value changed"));
            assertTrue(observed != correct, string.concat(id, ": defect no longer reproduces; move to fixed"));
        }
    }

    function _vectorBool(string memory id, bool observed, bool v1Observed, bool correct) internal {
        if (red) {
            assertEq(observed, correct, string.concat(id, ": correct expectation"));
        } else {
            assertEq(observed, v1Observed, string.concat(id, ": v1 observed value changed"));
            assertTrue(observed != correct, string.concat(id, ": defect no longer reproduces; move to fixed"));
        }
    }

    function _payout(address borrower, uint64 sats, uint32 blockTimestamp, uint256 salt) internal {
        PayoutEvidence memory e = PayoutEvidence({
            borrower: borrower,
            txid: keccak256(abi.encodePacked(borrower, salt)),
            vout: 0,
            amountSats: sats,
            blockHeight: 800_000,
            blockTimestamp: blockTimestamp
        });
        manager.submitPayout(verifier.encodeEvidence(e));
    }

    /// @dev Register alice and give her a $10,000 limit through one payout (0.4 BTC at $50k, 50% advance).
    function _aliceWithLimit() internal {
        manager.registerBorrower(alice, keccak256("alice"));
        _payout(alice, 40_000_000, uint32(block.timestamp), 1);
        assertEq(manager.getBorrowerInfo(alice).creditLimit, 10_000_000_000);
    }

    function _borrow(address who, uint256 amount) internal {
        vm.prank(who);
        manager.borrow(amount);
    }

    function _repay(address who, uint256 amount) internal {
        usd.mint(who, amount);
        vm.startPrank(who);
        usd.approve(address(manager), amount);
        manager.repay(amount);
        vm.stopPrank();
    }

    // ------------------------------------------------------------------ AR-01 partial interest loss

    /// $5,000 at 10% for 365 days, repay $250: remaining debt must be $5,250 (v1 shows $5,000).
    function test_AR01_partialInterestPayment_preservesUnpaidInterest() public {
        _aliceWithLimit();
        _borrow(alice, 5_000_000_000);
        vm.warp(block.timestamp + 365 days);
        assertEq(manager.getAccruedInterest(alice), 500_000_000, "precondition: $500 interest accrued");

        _repay(alice, 250_000_000);

        uint256 debtAfter = manager.getCurrentDebt(alice);
        _vector("AR-01 total debt after $250 partial interest payment", debtAfter, 5_000_000_000, 5_250_000_000);
        _vector("AR-01 unpaid interest carried", manager.getAccruedInterest(alice), 0, 250_000_000);
    }

    // ------------------------------------------------------------------ AR-02 manager/vault allocation

    /// Same $250 payment: manager books it as interest, vault books it as principal.
    function test_AR02_managerAndVault_disagreeOnPrincipal() public {
        _aliceWithLimit();
        _borrow(alice, 5_000_000_000);
        vm.warp(block.timestamp + 365 days);
        _repay(alice, 250_000_000);

        uint256 managerPrincipal = manager.getBorrowerInfo(alice).currentDebt;
        uint256 vaultPrincipal = vault.totalBorrowed();
        // Manager: principal untouched (5,000). Vault: principal reduced to 4,750. Correct: both 5,000.
        assertEq(managerPrincipal, 5_000_000_000, "manager principal");
        _vector("AR-02 vault principal after interest-only payment", vaultPrincipal, 4_750_000_000, 5_000_000_000);
        _vectorBool("AR-02 manager principal == vault principal", managerPrincipal == vaultPrincipal, false, true);
    }

    // ------------------------------------------------------------------ AR-03 re-borrow capitalization

    /// Borrow $5,000, wait 1y ($500 interest), borrow $1,000 more: manager capitalizes, vault does not.
    function test_AR03_reborrow_capitalizesOnlyInManager() public {
        _aliceWithLimit();
        _borrow(alice, 5_000_000_000);
        vm.warp(block.timestamp + 365 days);
        _borrow(alice, 1_000_000_000);

        uint256 managerPrincipal = manager.getBorrowerInfo(alice).currentDebt; // 6,500 (interest capitalized)
        uint256 vaultPrincipal = vault.totalBorrowed(); // 6,000
        assertEq(managerPrincipal, 6_500_000_000, "manager capitalized principal");
        assertEq(vaultPrincipal, 6_000_000_000, "vault principal");
        // Correct: one product rule. The v2 ledger keeps principal 6,000 and unpaid interest 500 in BOTH
        // (no capitalization unless the facility terms say so), so the two views must agree.
        _vectorBool(
            "AR-03 manager principal == vault principal after re-borrow",
            managerPrincipal == vaultPrincipal,
            false,
            true
        );
        _vector(
            "AR-03 principal (no capitalization) as seen by manager", managerPrincipal, 6_500_000_000, 6_000_000_000
        );
    }

    // ------------------------------------------------------------------ AR-04 APR applied retroactively

    /// $5,000 for 1y at 10%, then owner raises APR to 20%: manager re-prices the past year at 20%.
    function test_AR04_aprChange_appliesRetroactivelyInManager() public {
        _aliceWithLimit();
        _borrow(alice, 5_000_000_000);
        vm.warp(block.timestamp + 365 days);
        assertEq(manager.getAccruedInterest(alice), 500_000_000, "precondition at 10%");

        vault.setFixedAPR(2000); // vault accrues the past year at 10% before switching

        uint256 managerInterest = manager.getAccruedInterest(alice); // 5,000 * 20% * 1y = 1,000
        uint256 vaultInterest = vault.accumulatedInterest(); // 500 (frozen at old rate)
        assertEq(vaultInterest, 500_000_000, "vault freezes past interest at the old rate");
        _vector(
            "AR-04 borrower interest for the year before the APR change", managerInterest, 1_000_000_000, 500_000_000
        );
    }

    // ------------------------------------------------------------------ AR-05 stale limit at borrow

    /// Limit is only recomputed on submitPayout; after the window expires borrow still uses the stale limit.
    function test_AR05_staleLimit_allowsBorrowAfterWindowExpiry() public {
        _aliceWithLimit();
        vm.warp(block.timestamp + WINDOW + 1 days); // the only payout is now outside the trailing window

        uint256 storedLimit = manager.getBorrowerInfo(alice).creditLimit; // still $10,000
        assertEq(storedLimit, 10_000_000_000, "stored limit not refreshed");

        // Correct: effective limit is 0 (no in-window revenue) and the draw must revert.
        bool borrowed;
        vm.prank(alice);
        try manager.borrow(1_000_000_000) {
            borrowed = true;
        } catch {
            borrowed = false;
        }
        _vectorBool("AR-05 borrow succeeds with expired evidence", borrowed, true, false);
    }

    // ------------------------------------------------------------------ AR-06 old evidence counted as fresh

    /// A payout mined 60 days ago is recorded at submission time and counts fully in the 30-day window.
    function test_AR06_oldEvidence_recordedAtSubmissionTime() public {
        manager.registerBorrower(alice, keccak256("alice"));
        uint32 minedAt = uint32(block.timestamp - 60 days);
        _payout(alice, 40_000_000, minedAt, 7);

        IHashCreditManager.BorrowerInfo memory info = manager.getBorrowerInfo(alice);
        assertEq(info.lastPayoutTimestamp, minedAt, "evidence timestamp is kept for display only");
        // Correct: evidence older than the window contributes 0 trailing revenue / 0 limit.
        _vector(
            "AR-06 trailing revenue from 60-day-old payout (30-day window)", info.trailingRevenueSats, 40_000_000, 0
        );
        _vector("AR-06 credit limit from 60-day-old payout", info.creditLimit, 10_000_000_000, 0);
    }

    // ------------------------------------------------------------------ AR-07 claim signature has no domain

    /// claimBtcAddress binds pubkeyHash to msg.sender but the signed hash carries no caller/chain/nonce.
    /// Anyone who sees Alice's (hash, sig) can bind her BTC key to their own address.
    function test_AR07_claimBtcAddress_replayableByAnotherCaller() public {
        CheckpointManager cm = new CheckpointManager(address(this));
        BtcSpvVerifier spv = new BtcSpvVerifier(address(this), address(cm));

        Vm.Wallet memory aliceBtc = vm.createWallet(uint256(keccak256("alice-btc-key")));
        bytes32 msgHash = keccak256("HashCredit: Link BTC to 0xA11CE"); // no contract / chain / nonce binding
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(aliceBtc.privateKey, msgHash);

        vm.prank(alice);
        spv.claimBtcAddress(bytes32(aliceBtc.publicKeyX), bytes32(aliceBtc.publicKeyY), msgHash, v, r, s);
        bytes20 aliceHash = spv.borrowerPubkeyHash(alice);
        assertTrue(aliceHash != bytes20(0), "alice linked");

        // Replay by a different caller with the same public parameters.
        bool malloryLinked;
        vm.prank(mallory);
        try spv.claimBtcAddress(bytes32(aliceBtc.publicKeyX), bytes32(aliceBtc.publicKeyY), msgHash, v, r, s) {
            malloryLinked = spv.borrowerPubkeyHash(mallory) == aliceHash;
        } catch {
            malloryLinked = false;
        }
        _vectorBool("AR-07 third party can bind Alice's BTC key to itself by replay", malloryLinked, true, false);
    }

    // ------------------------------------------------------------------ AR-08 share donation / rounding

    /// First depositor with 1 base unit + direct donation makes the next depositor's shares round down.
    function test_AR08_shareDonation_roundsSecondDepositorDown() public {
        LendingVault v2 = new LendingVault(address(usd), 1000); // fresh vault, no manager needed
        address first = address(0xF1);
        address second = address(0xF2);

        usd.mint(first, 1 + 1_000_000_000); // 1 unit to deposit + $1,000 to donate
        vm.startPrank(first);
        usd.approve(address(v2), 1);
        v2.deposit(1); // 1 share
        usd.transfer(address(v2), 1_000_000_000); // donation: totalAssets = 1e9 + 1, totalShares = 1
        vm.stopPrank();

        usd.mint(second, 2_000_000_000);
        vm.startPrank(second);
        usd.approve(address(v2), 2_000_000_000);
        uint256 secondShares = v2.deposit(2_000_000_000); // 2e9 * 1 / (1e9 + 1) = 1 share (floor)
        vm.stopPrank();

        uint256 secondRedeemable = v2.convertToAssets(secondShares);
        // Second deposited $2,000 but can redeem only ~$1,500; the first depositor gained ~$500.
        assertEq(secondShares, 1, "rounded down to a single share");
        assertEq(secondRedeemable, 1_500_000_000, "half of the pool");
        _vector(
            "AR-08 second depositor redeemable after $2,000 deposit", secondRedeemable, 1_500_000_000, 2_000_000_000
        );
        // A $1,000 deposit is refused outright (0 shares), locking small LPs out after a donation.
        usd.mint(second, 1_000_000_000);
        vm.startPrank(second);
        usd.approve(address(v2), 1_000_000_000);
        bool accepted;
        try v2.deposit(1_000_000_000) {
            accepted = true;
        } catch {
            accepted = false;
        }
        vm.stopPrank();
        _vectorBool("AR-08 $1,000 deposit accepted after donation", accepted, false, true);
    }
}
