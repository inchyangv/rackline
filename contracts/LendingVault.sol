// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import { IERC20 } from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import { ILendingVault } from "./interfaces/ILendingVault.sol";
import { SafeERC20 } from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import { ReentrancyGuard } from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

/**
 * @title LendingVault
 * @notice Stablecoin lending vault for HashCredit protocol
 * @dev Manages liquidity deposits from LPs and borrows/repayments from Manager
 *
 * Interest Model (MVP): Simple fixed APR
 * - Interest accrues continuously based on time elapsed
 * - LPs earn interest from borrowers
 *
 * Share Model: Similar to ERC4626
 * - Shares represent proportional ownership of vault assets
 * - Share value increases as interest accrues
 */
contract LendingVault is ILendingVault, ReentrancyGuard {
    using SafeERC20 for IERC20;

    // ============================================
    // Constants
    // ============================================

    /// @notice Seconds per year for APR calculations
    uint256 private constant SECONDS_PER_YEAR = 365 days;

    /// @notice Basis points denominator
    uint256 private constant BPS = 10_000;

    // ============================================
    // State Variables
    // ============================================

    /// @notice The underlying stablecoin asset (internal)
    IERC20 internal immutable _asset;

    /// @notice The HashCreditManager address (only caller for borrow/repay)
    address public override manager;

    /// @notice Owner address for admin functions
    address public owner;

    /// @notice Total shares outstanding
    uint256 public totalShares;

    /// @notice Mapping of user address to their shares
    mapping(address => uint256) public sharesOf;

    /// @notice Total amount currently borrowed
    uint256 public override totalBorrowed;

    /// @notice Last timestamp when interest was accrued
    uint256 public lastAccrualTimestamp;

    /// @notice Accumulated interest (added to totalAssets)
    uint256 public accumulatedInterest;

    /// @notice Fixed borrow APR in basis points (e.g., 1000 = 10%)
    uint256 public fixedBorrowAPRBps;

    // ============================================
    // Constructor
    // ============================================

    /**
     * @notice Initialize the vault
     * @param asset_ The stablecoin token address
     * @param fixedAPRBps_ Initial fixed APR in basis points
     */
    constructor(address asset_, uint256 fixedAPRBps_) {
        if (asset_ == address(0)) revert InvalidAddress();

        _asset = IERC20(asset_);
        fixedBorrowAPRBps = fixedAPRBps_;
        owner = msg.sender;
        lastAccrualTimestamp = block.timestamp;
    }

    /**
     * @inheritdoc ILendingVault
     */
    function asset() external view override returns (address) {
        return address(_asset);
    }

    // ============================================
    // Modifiers
    // ============================================

    modifier onlyManager() {
        if (msg.sender != manager) revert OnlyManager();
        _;
    }

    modifier onlyOwner() {
        if (msg.sender != owner) revert InvalidAddress();
        _;
    }

    // ============================================
    // Admin Functions
    // ============================================

    /**
     * @notice Set the manager address
     * @param newManager New manager address
     */
    function setManager(address newManager) external onlyOwner {
        if (newManager == address(0)) revert InvalidAddress();
        address oldManager = manager;
        manager = newManager;
        emit ManagerUpdated(oldManager, newManager);
    }

    /**
     * @notice Set the fixed borrow APR
     * @param newAPRBps New APR in basis points
     */
    function setFixedAPR(uint256 newAPRBps) external onlyOwner {
        _accrueInterest();
        fixedBorrowAPRBps = newAPRBps;
    }

    /**
     * @notice Transfer ownership
     * @param newOwner New owner address
     */
    function transferOwnership(address newOwner) external onlyOwner {
        if (newOwner == address(0)) revert InvalidAddress();
        owner = newOwner;
    }

    // ============================================
    // LP Functions
    // ============================================

    /**
     * @inheritdoc ILendingVault
     */
    function deposit(uint256 amount) external override nonReentrant returns (uint256 shares) {
        if (amount == 0) revert ZeroAmount();

        _accrueInterest();

        shares = convertToShares(amount);
        if (shares == 0) revert ZeroAmount();

        // Transfer tokens first (checks-effects-interactions pattern with nonReentrant guard)
        _asset.safeTransferFrom(msg.sender, address(this), amount);

        sharesOf[msg.sender] += shares;
        totalShares += shares;

        emit Deposited(msg.sender, amount, shares);
    }

    /**
     * @inheritdoc ILendingVault
     */
    function withdraw(uint256 shares) external override nonReentrant returns (uint256 amount) {
        if (shares == 0) revert ZeroAmount();
        if (shares > sharesOf[msg.sender]) revert InsufficientShares();

        _accrueInterest();

        amount = convertToAssets(shares);
        if (amount > availableLiquidity()) revert InsufficientLiquidity();

        // Update state before external call (CEI pattern)
        sharesOf[msg.sender] -= shares;
        totalShares -= shares;

        _asset.safeTransfer(msg.sender, amount);

        emit Withdrawn(msg.sender, amount, shares);
    }

    // ============================================
    // Manager Functions
    // ============================================

    /**
     * @inheritdoc ILendingVault
     */
    function borrowFunds(address borrower, uint256 amount) external override onlyManager nonReentrant {
        if (amount == 0) revert ZeroAmount();
        if (amount > availableLiquidity()) revert InsufficientLiquidity();

        _accrueInterest();

        // Update state before external call (CEI pattern)
        totalBorrowed += amount;

        _asset.safeTransfer(borrower, amount);

        emit BorrowedFromVault(borrower, amount);
    }

    /**
     * @inheritdoc ILendingVault
     */
    function repayFunds(address borrower, uint256 amount) external override onlyManager nonReentrant {
        if (amount == 0) revert ZeroAmount();

        _accrueInterest();

        // Transfer tokens first (receiving funds is safe before state update)
        // Manager is responsible for collecting from borrower first
        _asset.safeTransferFrom(msg.sender, address(this), amount);

        // Cap principal repayment at total borrowed
        uint256 principalRepay = amount > totalBorrowed ? totalBorrowed : amount;
        uint256 interestPortion = amount - principalRepay;

        totalBorrowed -= principalRepay;

        // When interest is repaid, reduce accumulatedInterest to prevent double-counting
        // (interest tokens come into balanceOf, so we reduce the "expected" interest)
        if (interestPortion > 0 && accumulatedInterest > 0) {
            uint256 interestDeduction = interestPortion > accumulatedInterest ? accumulatedInterest : interestPortion;
            accumulatedInterest -= interestDeduction;
        }

        emit RepaidToVault(borrower, amount);
    }

    // ============================================
    // View Functions
    // ============================================

    /**
     * @inheritdoc ILendingVault
     * @dev Includes: actual balance + outstanding borrowed + accrued interest + pending interest
     *      This ensures share price reflects all earned interest at any point in time
     */
    function totalAssets() public view override returns (uint256) {
        return _asset.balanceOf(address(this)) + totalBorrowed + accumulatedInterest + _pendingInterest();
    }

    /**
     * @inheritdoc ILendingVault
     */
    function availableLiquidity() public view override returns (uint256) {
        return _asset.balanceOf(address(this));
    }

    /**
     * @inheritdoc ILendingVault
     */
    function convertToShares(uint256 assets) public view override returns (uint256) {
        uint256 supply = totalShares;
        uint256 total = totalAssets();

        if (supply == 0 || total == 0) {
            return assets; // 1:1 ratio initially
        }

        return (assets * supply) / total;
    }

    /**
     * @inheritdoc ILendingVault
     */
    function convertToAssets(uint256 shares) public view override returns (uint256) {
        uint256 supply = totalShares;

        if (supply == 0) {
            return shares; // 1:1 ratio initially
        }

        return (shares * totalAssets()) / supply;
    }

    /**
     * @inheritdoc ILendingVault
     */
    function utilizationRate() external view override returns (uint256) {
        uint256 total = totalAssets();
        if (total == 0) return 0;
        return (totalBorrowed * BPS) / total;
    }

    /**
     * @inheritdoc ILendingVault
     */
    function borrowAPR() external view override returns (uint256) {
        return fixedBorrowAPRBps;
    }

    // ============================================
    // Internal Functions
    // ============================================

    /**
     * @notice Accrue interest based on time elapsed
     */
    function _accrueInterest() internal {
        uint256 pending = _pendingInterest();
        if (pending > 0) {
            accumulatedInterest += pending;
            emit InterestAccrued(pending, block.timestamp);
        }
        lastAccrualTimestamp = block.timestamp;
    }

    /**
     * @notice Calculate pending interest since last accrual
     */
    function _pendingInterest() internal view returns (uint256) {
        if (totalBorrowed == 0) return 0;

        uint256 timeElapsed = block.timestamp - lastAccrualTimestamp;
        if (timeElapsed == 0) return 0;

        // interest = principal * rate * time / year
        // rate is in basis points, so divide by BPS
        return (totalBorrowed * fixedBorrowAPRBps * timeElapsed) / (SECONDS_PER_YEAR * BPS);
    }
}
