// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import { IERC20 } from "lib/forge-std/src/interfaces/IERC20.sol";
import { ILendingVault } from "./interfaces/ILendingVault.sol";

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
contract LendingVault is ILendingVault {
    // ============================================
    // Constants
    // ============================================

    /// @notice Precision for interest calculations
    uint256 private constant PRECISION = 1e18;

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
    function deposit(uint256 amount) external override returns (uint256 shares) {
        if (amount == 0) revert ZeroAmount();

        _accrueInterest();

        shares = convertToShares(amount);
        if (shares == 0) revert ZeroAmount();

        sharesOf[msg.sender] += shares;
        totalShares += shares;

        _asset.transferFrom(msg.sender, address(this), amount);

        emit Deposited(msg.sender, amount, shares);
    }

    /**
     * @inheritdoc ILendingVault
     */
    function withdraw(uint256 shares) external override returns (uint256 amount) {
        if (shares == 0) revert ZeroAmount();
        if (shares > sharesOf[msg.sender]) revert InsufficientShares();

        _accrueInterest();

        amount = convertToAssets(shares);
        if (amount > availableLiquidity()) revert InsufficientLiquidity();

        sharesOf[msg.sender] -= shares;
        totalShares -= shares;

        _asset.transfer(msg.sender, amount);

        emit Withdrawn(msg.sender, amount, shares);
    }

    // ============================================
    // Manager Functions
    // ============================================

    /**
     * @inheritdoc ILendingVault
     */
    function borrowFunds(address borrower, uint256 amount) external override onlyManager {
        if (amount == 0) revert ZeroAmount();
        if (amount > availableLiquidity()) revert InsufficientLiquidity();

        _accrueInterest();

        totalBorrowed += amount;

        _asset.transfer(borrower, amount);

        emit BorrowedFromVault(borrower, amount);
    }

    /**
     * @inheritdoc ILendingVault
     */
    function repayFunds(address borrower, uint256 amount) external override onlyManager {
        if (amount == 0) revert ZeroAmount();

        _accrueInterest();

        // Cap repayment at total borrowed
        uint256 actualRepay = amount > totalBorrowed ? totalBorrowed : amount;
        totalBorrowed -= actualRepay;

        // Transfer from manager (msg.sender), not borrower
        // Manager is responsible for collecting from borrower first
        _asset.transferFrom(msg.sender, address(this), amount);

        emit RepaidToVault(borrower, amount);
    }

    // ============================================
    // View Functions
    // ============================================

    /**
     * @inheritdoc ILendingVault
     */
    function totalAssets() public view override returns (uint256) {
        return _asset.balanceOf(address(this)) + totalBorrowed + _pendingInterest();
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
