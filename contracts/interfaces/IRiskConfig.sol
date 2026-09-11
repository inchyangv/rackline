// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * @title IRiskConfig
 * @notice Interface for risk configuration management
 * @dev Stores and manages all risk-related parameters for the protocol
 */
interface IRiskConfig {
    // ============================================
    // Structs
    // ============================================

    /// @notice Risk parameters structure
    struct RiskParams {
        /// @notice Required confirmations for payout (informational, enforced by relayer)
        uint32 confirmationsRequired;
        /// @notice Advance rate in basis points (e.g., 5000 = 50%)
        uint32 advanceRateBps;
        /// @notice Trailing revenue window in seconds (e.g., 30 days)
        uint32 windowSeconds;
        /// @notice Maximum credit limit for new borrowers (in stablecoin, 6 decimals)
        uint128 newBorrowerCap;
        /// @notice Global protocol cap on total borrows (0 = no cap)
        uint128 globalCap;
        /// @notice Minimum payout amount to count (in satoshis)
        uint64 minPayoutSats;
        /// @notice BTC/USD price for credit calculation (8 decimals, e.g., 50000_00000000 = $50,000)
        uint64 btcPriceUsd;
    }

    // ============================================
    // Events
    // ============================================

    /// @notice Emitted when risk parameters are updated
    event RiskParamsUpdated(
        uint32 confirmationsRequired,
        uint32 advanceRateBps,
        uint32 windowSeconds,
        uint128 newBorrowerCap,
        uint128 globalCap,
        uint64 minPayoutSats,
        uint64 btcPriceUsd
    );

    /// @notice Emitted when BTC price is updated
    event BtcPriceUpdated(uint64 oldPrice, uint64 newPrice);

    // ============================================
    // Errors
    // ============================================

    /// @notice Invalid parameter value
    error InvalidParameter();

    /// @notice Advance rate too high (max 100%)
    error AdvanceRateTooHigh();

    // ============================================
    // Functions
    // ============================================

    /**
     * @notice Get all risk parameters
     * @return params Current risk parameters
     */
    function getRiskParams() external view returns (RiskParams memory params);

    /**
     * @notice Update risk parameters
     * @param params New risk parameters
     */
    function setRiskParams(RiskParams calldata params) external;

    /**
     * @notice Update only the BTC price
     * @param btcPriceUsd New BTC price in USD (8 decimals)
     */
    function setBtcPrice(uint64 btcPriceUsd) external;

    /**
     * @notice Calculate credit limit from satoshi revenue
     * @param revenueSats Revenue in satoshis
     * @return creditLimit Credit limit in stablecoin (6 decimals)
     * @dev creditLimit = revenueSats * btcPriceUsd * advanceRateBps / 10000 / 1e8 (sat to btc) * 1e6 (stablecoin decimals)
     */
    function calculateCreditLimit(uint128 revenueSats) external view returns (uint128 creditLimit);

    // ============================================
    // Individual Getters (convenience)
    // ============================================

    function confirmationsRequired() external view returns (uint32);
    function advanceRateBps() external view returns (uint32);
    function windowSeconds() external view returns (uint32);
    function newBorrowerCap() external view returns (uint128);
    function globalCap() external view returns (uint128);
    function minPayoutSats() external view returns (uint64);
    function btcPriceUsd() external view returns (uint64);
}
