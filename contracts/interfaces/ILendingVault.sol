// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * @title ILendingVault
 * @notice Interface for the stablecoin lending vault
 * @dev Manages liquidity deposits, borrows, and repayments
 *      Only HashCreditManager can call borrow/repay functions
 */
interface ILendingVault {
    // ============================================
    // Events
    // ============================================

    /// @notice Emitted when liquidity is deposited
    event Deposited(address indexed depositor, uint256 amount, uint256 shares);

    /// @notice Emitted when liquidity is withdrawn
    event Withdrawn(address indexed depositor, uint256 amount, uint256 shares);

    /// @notice Emitted when funds are borrowed (via Manager)
    event BorrowedFromVault(address indexed borrower, uint256 amount);

    /// @notice Emitted when debt is repaid (via Manager)
    event RepaidToVault(address indexed borrower, uint256 amount);

    /// @notice Emitted when interest is accrued
    event InterestAccrued(uint256 totalInterest, uint256 timestamp);

    /// @notice Emitted when manager is updated
    event ManagerUpdated(address indexed oldManager, address indexed newManager);

    // ============================================
    // Errors
    // ============================================

    /// @notice Caller is not the manager
    error OnlyManager();

    /// @notice Insufficient liquidity for borrow
    error InsufficientLiquidity();

    /// @notice Insufficient shares for withdrawal
    error InsufficientShares();

    /// @notice Amount is zero
    error ZeroAmount();

    /// @notice Invalid address
    error InvalidAddress();

    // ============================================
    // LP Functions (Liquidity Providers)
    // ============================================

    /**
     * @notice Deposit stablecoin to provide liquidity
     * @param amount Amount of stablecoin to deposit
     * @return shares LP shares minted
     */
    function deposit(uint256 amount) external returns (uint256 shares);

    /**
     * @notice Withdraw liquidity by burning shares
     * @param shares Amount of shares to burn
     * @return amount Stablecoin amount returned
     */
    function withdraw(uint256 shares) external returns (uint256 amount);

    // ============================================
    // Manager Functions (Only HashCreditManager)
    // ============================================

    /**
     * @notice Borrow funds for a borrower (only callable by manager)
     * @param borrower Address to send funds to
     * @param amount Amount to borrow
     */
    function borrowFunds(address borrower, uint256 amount) external;

    /**
     * @notice Receive repayment (only callable by manager)
     * @param borrower Address repaying
     * @param amount Amount being repaid
     */
    function repayFunds(address borrower, uint256 amount) external;

    // ============================================
    // View Functions
    // ============================================

    /**
     * @notice Get total assets in the vault (including outstanding loans)
     * @return Total assets denominated in stablecoin
     */
    function totalAssets() external view returns (uint256);

    /**
     * @notice Get available liquidity for new borrows
     * @return Available liquidity
     */
    function availableLiquidity() external view returns (uint256);

    /**
     * @notice Get total outstanding borrows
     * @return Total borrowed amount
     */
    function totalBorrowed() external view returns (uint256);

    /**
     * @notice Convert shares to asset amount
     * @param shares Number of shares
     * @return assets Equivalent asset amount
     */
    function convertToAssets(uint256 shares) external view returns (uint256 assets);

    /**
     * @notice Convert asset amount to shares
     * @param assets Asset amount
     * @return shares Equivalent shares
     */
    function convertToShares(uint256 assets) external view returns (uint256 shares);

    /**
     * @notice Get the stablecoin token address
     */
    function asset() external view returns (address);

    /**
     * @notice Get the manager address
     */
    function manager() external view returns (address);

    /**
     * @notice Get current utilization rate (borrowed / total assets)
     * @return Utilization in basis points (0-10000)
     */
    function utilizationRate() external view returns (uint256);

    /**
     * @notice Get current borrow APR
     * @return APR in basis points
     */
    function borrowAPR() external view returns (uint256);
}
