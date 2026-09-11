// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import { PayoutEvidence } from "./IVerifierAdapter.sol";

/**
 * @title IHashCreditManager
 * @notice Interface for the HashCredit Manager contract
 * @dev Core contract that manages borrowers, payouts, credit limits, and routing
 */
interface IHashCreditManager {
    // ============================================
    // Enums
    // ============================================

    /// @notice Borrower status states
    enum BorrowerStatus {
        None,       // Not registered
        Active,     // Can borrow and submit payouts
        Frozen,     // Cannot borrow, can still repay
        Closed      // Fully closed, no operations allowed
    }

    // ============================================
    // Structs
    // ============================================

    /// @notice Borrower account information
    struct BorrowerInfo {
        BorrowerStatus status;
        /// @notice Hash of the borrower's BTC payout scriptPubKey
        bytes32 btcPayoutKeyHash;
        /// @notice Total lifetime revenue in satoshis
        uint128 totalRevenueSats;
        /// @notice Current trailing window revenue in satoshis (dynamically recalculated)
        uint128 trailingRevenueSats;
        /// @notice Current credit limit in stablecoin (6 decimals)
        uint128 creditLimit;
        /// @notice Current outstanding debt principal in stablecoin (6 decimals)
        uint128 currentDebt;
        /// @notice Last payout timestamp (for window calculations)
        uint64 lastPayoutTimestamp;
        /// @notice Registration timestamp
        uint64 registeredAt;
        /// @notice Total number of payouts received (for provenance heuristics)
        uint32 payoutCount;
        /// @notice Last timestamp when debt was updated (for interest calculation)
        uint64 lastDebtUpdateTimestamp;
    }

    /// @notice Record of a payout for trailing window calculation
    struct PayoutRecord {
        /// @notice Timestamp when the payout was recorded
        uint64 timestamp;
        /// @notice Effective amount in satoshis (after heuristics applied)
        uint64 effectiveAmountSats;
    }

    // ============================================
    // Events
    // ============================================

    /// @notice Emitted when a new borrower is registered
    event BorrowerRegistered(
        address indexed borrower,
        bytes32 indexed btcPayoutKeyHash,
        uint64 timestamp
    );

    /// @notice Emitted when borrower status changes
    event BorrowerStatusChanged(
        address indexed borrower,
        BorrowerStatus oldStatus,
        BorrowerStatus newStatus
    );

    /// @notice Emitted when a payout is recorded
    event PayoutRecorded(
        address indexed borrower,
        bytes32 indexed txid,
        uint32 vout,
        uint64 amountSats,
        uint32 blockHeight,
        uint128 newCreditLimit
    );

    /// @notice Emitted when a borrow occurs
    event Borrowed(
        address indexed borrower,
        uint256 amount,
        uint128 newDebt
    );

    /// @notice Emitted when a repayment occurs
    event Repaid(
        address indexed borrower,
        uint256 amount,
        uint128 newDebt
    );

    /// @notice Emitted when the verifier adapter is changed
    event VerifierUpdated(address indexed oldVerifier, address indexed newVerifier);

    /// @notice Emitted when the vault is changed
    event VaultUpdated(address indexed oldVault, address indexed newVault);

    /// @notice Emitted when payouts are pruned from trailing window
    event PayoutWindowPruned(
        address indexed borrower,
        uint256 prunedCount,
        uint128 newTrailingRevenue
    );

    /// @notice Emitted when a payout is skipped due to being below minimum
    event PayoutBelowMinimum(
        address indexed borrower,
        bytes32 indexed txid,
        uint32 vout,
        uint64 amountSats,
        uint64 minRequired
    );

    // ============================================
    // Errors
    // ============================================

    /// @notice Borrower is already registered
    error BorrowerAlreadyRegistered();

    /// @notice Borrower is not registered
    error BorrowerNotRegistered();

    /// @notice Borrower is frozen or closed
    error BorrowerNotActive();

    /// @notice Payout already processed (replay attack)
    error PayoutAlreadyProcessed();

    /// @notice Payout verification failed
    error PayoutVerificationFailed();

    /// @notice Borrower mismatch in payout evidence
    error BorrowerMismatch();

    /// @notice Amount exceeds credit limit
    error ExceedsCreditLimit();

    /// @notice Amount is zero
    error ZeroAmount();

    /// @notice Invalid address (zero address)
    error InvalidAddress();

    /// @notice Caller is not authorized
    error Unauthorized();

    /// @notice Payout source not eligible (pool registry check)
    error IneligiblePayoutSource();

    // ============================================
    // Functions
    // ============================================

    /**
     * @notice Register a new borrower
     * @param borrower EVM address of the borrower
     * @param btcPayoutKeyHash Hash of BTC scriptPubKey for payout verification
     */
    function registerBorrower(address borrower, bytes32 btcPayoutKeyHash) external;

    /**
     * @notice Submit a payout proof for credit
     * @param proof Encoded proof data (format depends on verifier)
     */
    function submitPayout(bytes calldata proof) external;

    /**
     * @notice Borrow stablecoin against credit limit
     * @param amount Amount to borrow (in stablecoin decimals)
     */
    function borrow(uint256 amount) external;

    /**
     * @notice Repay outstanding debt
     * @param amount Amount to repay (in stablecoin decimals)
     */
    function repay(uint256 amount) external;

    /**
     * @notice Get borrower information
     * @param borrower Address to query
     * @return info Borrower information struct
     */
    function getBorrowerInfo(address borrower) external view returns (BorrowerInfo memory info);

    /**
     * @notice Get current debt including accrued interest
     * @param borrower Address to query
     * @return Total debt (principal + accrued interest) in stablecoin decimals
     */
    function getCurrentDebt(address borrower) external view returns (uint256);

    /**
     * @notice Get accrued interest for a borrower
     * @param borrower Address to query
     * @return Accrued interest in stablecoin decimals
     */
    function getAccruedInterest(address borrower) external view returns (uint256);

    /**
     * @notice Get current verifier adapter address
     */
    function verifier() external view returns (address);

    /**
     * @notice Get vault address
     */
    function vault() external view returns (address);
}
