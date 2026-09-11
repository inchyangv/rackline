// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import { IHashCreditManager, PayoutEvidence } from "./interfaces/IHashCreditManager.sol";
import { IVerifierAdapter } from "./interfaces/IVerifierAdapter.sol";
import { ILendingVault } from "./interfaces/ILendingVault.sol";
import { IRiskConfig } from "./interfaces/IRiskConfig.sol";
import { IPoolRegistry } from "./interfaces/IPoolRegistry.sol";
import { IERC20 } from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import { SafeERC20 } from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import { ReentrancyGuard } from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

/**
 * @title HashCreditManager
 * @notice Core contract managing borrowers, payouts, credit limits, and loan routing
 * @dev Implements Revenue-Based Financing for Bitcoin miners on Creditcoin EVM
 *
 * Key responsibilities:
 * - Borrower registration with BTC payout key binding
 * - Payout verification via pluggable IVerifierAdapter
 * - Credit limit calculation based on trailing revenue
 * - Borrow/repay routing to LendingVault
 * - Replay protection for payouts
 */
contract HashCreditManager is IHashCreditManager, ReentrancyGuard {
    using SafeERC20 for IERC20;

    // ============================================
    // Constants
    // ============================================

    /// @notice Stablecoin decimals (USDC = 6)
    uint256 private constant STABLECOIN_DECIMALS = 6;

    /// @notice BTC price decimals in RiskConfig
    uint256 private constant BTC_PRICE_DECIMALS = 8;

    /// @notice Satoshis per BTC
    uint256 private constant SATS_PER_BTC = 1e8;

    /// @notice Basis points denominator
    uint256 private constant BPS = 10_000;

    // ============================================
    // State Variables
    // ============================================

    /// @notice Owner address
    address public owner;

    /// @notice Verifier adapter for payout proofs
    address public override verifier;

    /// @notice Lending vault for borrows/repays
    address public override vault;

    /// @notice Risk configuration contract
    address public riskConfig;

    /// @notice Pool registry for source eligibility
    address public poolRegistry;

    /// @notice Stablecoin token
    address public stablecoin;

    /// @notice Mapping of borrower address to their info
    mapping(address => BorrowerInfo) private _borrowers;

    /// @notice Mapping of processed payouts (keccak256(txid, vout) => processed)
    mapping(bytes32 => bool) public processedPayouts;

    /// @notice Total global debt
    uint256 public totalGlobalDebt;

    // ============================================
    // Constructor
    // ============================================

    constructor(
        address verifier_,
        address vault_,
        address riskConfig_,
        address poolRegistry_,
        address stablecoin_
    ) {
        if (verifier_ == address(0)) revert InvalidAddress();
        if (vault_ == address(0)) revert InvalidAddress();
        if (riskConfig_ == address(0)) revert InvalidAddress();
        if (stablecoin_ == address(0)) revert InvalidAddress();

        owner = msg.sender;
        verifier = verifier_;
        vault = vault_;
        riskConfig = riskConfig_;
        poolRegistry = poolRegistry_;
        stablecoin = stablecoin_;
    }

    // ============================================
    // Modifiers
    // ============================================

    modifier onlyOwner() {
        if (msg.sender != owner) revert Unauthorized();
        _;
    }

    // ============================================
    // Admin Functions
    // ============================================

    /**
     * @notice Update verifier adapter
     * @param newVerifier New verifier address
     */
    function setVerifier(address newVerifier) external onlyOwner {
        if (newVerifier == address(0)) revert InvalidAddress();
        address oldVerifier = verifier;
        verifier = newVerifier;
        emit VerifierUpdated(oldVerifier, newVerifier);
    }

    /**
     * @notice Update vault
     * @param newVault New vault address
     */
    function setVault(address newVault) external onlyOwner {
        if (newVault == address(0)) revert InvalidAddress();
        address oldVault = vault;
        vault = newVault;
        emit VaultUpdated(oldVault, newVault);
    }

    /**
     * @notice Update risk config
     * @param newRiskConfig New risk config address
     */
    function setRiskConfig(address newRiskConfig) external onlyOwner {
        if (newRiskConfig == address(0)) revert InvalidAddress();
        riskConfig = newRiskConfig;
    }

    /**
     * @notice Update pool registry
     * @param newPoolRegistry New pool registry address
     */
    function setPoolRegistry(address newPoolRegistry) external onlyOwner {
        poolRegistry = newPoolRegistry;
    }

    /**
     * @notice Transfer ownership
     * @param newOwner New owner address
     */
    function transferOwnership(address newOwner) external onlyOwner {
        if (newOwner == address(0)) revert InvalidAddress();
        owner = newOwner;
    }

    /**
     * @notice Freeze a borrower (emergency)
     * @param borrower Address to freeze
     */
    function freezeBorrower(address borrower) external onlyOwner {
        BorrowerInfo storage info = _borrowers[borrower];
        if (info.status == BorrowerStatus.None) revert BorrowerNotRegistered();

        BorrowerStatus oldStatus = info.status;
        info.status = BorrowerStatus.Frozen;
        emit BorrowerStatusChanged(borrower, oldStatus, BorrowerStatus.Frozen);
    }

    /**
     * @notice Unfreeze a borrower
     * @param borrower Address to unfreeze
     */
    function unfreezeBorrower(address borrower) external onlyOwner {
        BorrowerInfo storage info = _borrowers[borrower];
        if (info.status != BorrowerStatus.Frozen) revert BorrowerNotActive();

        info.status = BorrowerStatus.Active;
        emit BorrowerStatusChanged(borrower, BorrowerStatus.Frozen, BorrowerStatus.Active);
    }

    // ============================================
    // Borrower Registration
    // ============================================

    /**
     * @inheritdoc IHashCreditManager
     */
    function registerBorrower(address borrower, bytes32 btcPayoutKeyHash) external override onlyOwner {
        if (borrower == address(0)) revert InvalidAddress();
        if (_borrowers[borrower].status != BorrowerStatus.None) revert BorrowerAlreadyRegistered();

        _borrowers[borrower] = BorrowerInfo({
            status: BorrowerStatus.Active,
            btcPayoutKeyHash: btcPayoutKeyHash,
            totalRevenueSats: 0,
            trailingRevenueSats: 0,
            creditLimit: 0,
            currentDebt: 0,
            lastPayoutTimestamp: 0,
            registeredAt: uint64(block.timestamp),
            payoutCount: 0,
            lastDebtUpdateTimestamp: 0
        });

        emit BorrowerRegistered(borrower, btcPayoutKeyHash, uint64(block.timestamp));
    }

    // ============================================
    // Payout Submission
    // ============================================

    /**
     * @inheritdoc IHashCreditManager
     */
    function submitPayout(bytes calldata proof) external override {
        // 1. Verify the payout via adapter
        PayoutEvidence memory evidence = IVerifierAdapter(verifier).verifyPayout(proof);

        // 2. Check borrower exists and is active
        BorrowerInfo storage info = _borrowers[evidence.borrower];
        if (info.status == BorrowerStatus.None) revert BorrowerNotRegistered();
        if (info.status != BorrowerStatus.Active) revert BorrowerNotActive();

        // 3. Check replay protection
        bytes32 payoutKey = keccak256(abi.encodePacked(evidence.txid, evidence.vout));
        if (processedPayouts[payoutKey]) revert PayoutAlreadyProcessed();

        // 4. Semantic validation
        if (evidence.amountSats == 0) revert ZeroAmount();

        // 5. Check pool registry eligibility (if configured)
        if (poolRegistry != address(0)) {
            // For MVP, we use txid as source identifier
            // Production would use input UTXO analysis
            if (!IPoolRegistry(poolRegistry).isEligiblePayoutSource(evidence.txid)) {
                revert IneligiblePayoutSource();
            }
        }

        // 6. Mark payout as processed
        processedPayouts[payoutKey] = true;

        // 7. Update payout count
        info.payoutCount++;

        // 8. Apply provenance heuristics to get effective amount
        uint64 effectiveAmount = IRiskConfig(riskConfig).applyPayoutHeuristics(
            evidence.amountSats,
            info.payoutCount
        );

        // 9. Update borrower revenue with effective amount
        info.totalRevenueSats += effectiveAmount;
        info.trailingRevenueSats += effectiveAmount;
        info.lastPayoutTimestamp = evidence.blockTimestamp;

        // 10. Recalculate credit limit
        uint128 newCreditLimit = _calculateCreditLimit(info.trailingRevenueSats);

        // Apply new borrower cap if applicable
        IRiskConfig.RiskParams memory params = IRiskConfig(riskConfig).getRiskParams();
        if (info.registeredAt + params.windowSeconds > block.timestamp) {
            // Still in "new borrower" period
            if (newCreditLimit > params.newBorrowerCap) {
                newCreditLimit = params.newBorrowerCap;
            }
        }

        info.creditLimit = newCreditLimit;

        emit PayoutRecorded(
            evidence.borrower,
            evidence.txid,
            evidence.vout,
            effectiveAmount, // Emit effective amount, not original
            evidence.blockHeight,
            newCreditLimit
        );
    }

    // ============================================
    // Borrow/Repay
    // ============================================

    /**
     * @inheritdoc IHashCreditManager
     */
    function borrow(uint256 amount) external override nonReentrant {
        if (amount == 0) revert ZeroAmount();

        BorrowerInfo storage info = _borrowers[msg.sender];
        if (info.status == BorrowerStatus.None) revert BorrowerNotRegistered();
        if (info.status != BorrowerStatus.Active) revert BorrowerNotActive();

        // Compound any accrued interest into principal before adding new borrow
        uint256 accruedInterest = _calculateAccruedInterest(info);
        uint256 currentPrincipal = uint256(info.currentDebt) + accruedInterest;

        // Check credit limit with new amount
        uint256 newDebt = currentPrincipal + amount;
        if (newDebt > info.creditLimit) revert ExceedsCreditLimit();

        // Check global cap
        IRiskConfig.RiskParams memory params = IRiskConfig(riskConfig).getRiskParams();
        if (params.globalCap > 0 && totalGlobalDebt + accruedInterest + amount > params.globalCap) {
            revert ExceedsCreditLimit();
        }

        // Update state before external call (CEI pattern)
        info.currentDebt = uint128(newDebt);
        info.lastDebtUpdateTimestamp = uint64(block.timestamp);
        totalGlobalDebt += accruedInterest + amount;

        // Route to vault
        ILendingVault(vault).borrowFunds(msg.sender, amount);

        emit Borrowed(msg.sender, amount, info.currentDebt);
    }

    /**
     * @inheritdoc IHashCreditManager
     */
    function repay(uint256 amount) external override nonReentrant {
        if (amount == 0) revert ZeroAmount();

        BorrowerInfo storage info = _borrowers[msg.sender];
        if (info.status == BorrowerStatus.None) revert BorrowerNotRegistered();

        // Calculate accrued interest
        uint256 accruedInterest = _calculateAccruedInterest(info);
        uint256 totalDebt = uint256(info.currentDebt) + accruedInterest;

        // Cap repayment at total debt (principal + interest)
        uint256 actualRepay = amount > totalDebt ? totalDebt : amount;

        // Calculate how much goes to interest vs principal
        uint256 interestPaid;
        uint256 principalPaid;

        if (actualRepay <= accruedInterest) {
            // Only paying interest (or partial interest)
            interestPaid = actualRepay;
            principalPaid = 0;
        } else {
            // Paying all interest + some/all principal
            interestPaid = accruedInterest;
            principalPaid = actualRepay - accruedInterest;
        }

        // Transfer stablecoin from borrower (SafeERC20 for non-standard tokens)
        IERC20(stablecoin).safeTransferFrom(msg.sender, address(this), actualRepay);

        // Approve vault to pull funds (forceApprove handles tokens requiring 0 approval first)
        IERC20(stablecoin).forceApprove(vault, actualRepay);

        // Route to vault (full amount including interest)
        ILendingVault(vault).repayFunds(msg.sender, actualRepay);

        // Update state after external calls (vault call is to trusted contract)
        info.currentDebt -= uint128(principalPaid);
        info.lastDebtUpdateTimestamp = uint64(block.timestamp);
        // totalGlobalDebt tracks principal only, so only subtract principal paid
        totalGlobalDebt -= principalPaid;

        emit Repaid(msg.sender, actualRepay, info.currentDebt);
    }

    // ============================================
    // View Functions
    // ============================================

    /**
     * @inheritdoc IHashCreditManager
     */
    function getBorrowerInfo(address borrower) external view override returns (BorrowerInfo memory) {
        return _borrowers[borrower];
    }

    /**
     * @notice Check if a payout has been processed
     * @param txid Bitcoin transaction ID
     * @param vout Output index
     * @return True if processed
     */
    function isPayoutProcessed(bytes32 txid, uint32 vout) external view returns (bool) {
        return processedPayouts[keccak256(abi.encodePacked(txid, vout))];
    }

    /**
     * @notice Get available credit for a borrower
     * @param borrower Address to check
     * @return Available credit (creditLimit - currentDebt including interest)
     */
    function getAvailableCredit(address borrower) external view returns (uint256) {
        BorrowerInfo storage info = _borrowers[borrower];
        uint256 totalDebt = uint256(info.currentDebt) + _calculateAccruedInterest(info);
        if (info.creditLimit <= totalDebt) return 0;
        return info.creditLimit - totalDebt;
    }

    /**
     * @inheritdoc IHashCreditManager
     */
    function getCurrentDebt(address borrower) external view override returns (uint256) {
        BorrowerInfo storage info = _borrowers[borrower];
        return uint256(info.currentDebt) + _calculateAccruedInterest(info);
    }

    /**
     * @inheritdoc IHashCreditManager
     */
    function getAccruedInterest(address borrower) external view override returns (uint256) {
        return _calculateAccruedInterest(_borrowers[borrower]);
    }

    // ============================================
    // Internal Functions
    // ============================================

    /// @notice Seconds per year for APR calculations
    uint256 private constant SECONDS_PER_YEAR = 365 days;

    /**
     * @notice Calculate accrued interest for a borrower
     * @param info Borrower info storage reference
     * @return interest Accrued interest in stablecoin decimals
     */
    function _calculateAccruedInterest(BorrowerInfo storage info) internal view returns (uint256) {
        if (info.currentDebt == 0 || info.lastDebtUpdateTimestamp == 0) {
            return 0;
        }

        uint256 timeElapsed = block.timestamp - info.lastDebtUpdateTimestamp;
        if (timeElapsed == 0) {
            return 0;
        }

        // Get APR from vault
        uint256 aprBps = ILendingVault(vault).borrowAPR();

        // interest = principal * rate * time / year
        // rate is in basis points, so divide by BPS
        return (uint256(info.currentDebt) * aprBps * timeElapsed) / (SECONDS_PER_YEAR * BPS);
    }

    /**
     * @notice Calculate credit limit from trailing revenue
     * @param trailingRevenueSats Revenue in satoshis
     * @return creditLimit Credit limit in stablecoin (6 decimals)
     */
    function _calculateCreditLimit(uint128 trailingRevenueSats) internal view returns (uint128) {
        IRiskConfig.RiskParams memory params = IRiskConfig(riskConfig).getRiskParams();

        // creditLimit = trailingRevenueSats * btcPriceUsd * advanceRateBps / BPS / SATS_PER_BTC
        // Result in stablecoin decimals (6)

        // Step by step to avoid overflow:
        // 1. Convert sats to BTC value in USD (8 decimals)
        // 2. Apply advance rate
        // 3. Convert to stablecoin decimals

        uint256 btcValueUsd = (uint256(trailingRevenueSats) * params.btcPriceUsd) / SATS_PER_BTC;
        uint256 creditLimitUsd = (btcValueUsd * params.advanceRateBps) / BPS;

        // Convert from 8 decimals (btcPrice) to 6 decimals (stablecoin)
        uint256 creditLimit = creditLimitUsd / 100; // 10^8 / 10^6 = 100

        // Cap at uint128 max
        if (creditLimit > type(uint128).max) {
            return type(uint128).max;
        }

        return uint128(creditLimit);
    }
}
