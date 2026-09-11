// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import { IRiskConfig } from "./interfaces/IRiskConfig.sol";

/**
 * @title RiskConfig
 * @notice Stores and manages risk parameters for the HashCredit protocol
 */
contract RiskConfig is IRiskConfig {
    // ============================================
    // State Variables
    // ============================================

    /// @notice Owner address
    address public owner;

    /// @notice Current risk parameters
    RiskParams private _params;

    // ============================================
    // Constructor
    // ============================================

    constructor(RiskParams memory initialParams) {
        owner = msg.sender;
        _validateParams(initialParams);
        _params = initialParams;
    }

    // ============================================
    // Modifiers
    // ============================================

    modifier onlyOwner() {
        require(msg.sender == owner, "RiskConfig: not owner");
        _;
    }

    // ============================================
    // Admin Functions
    // ============================================

    /**
     * @inheritdoc IRiskConfig
     */
    function setRiskParams(RiskParams calldata params) external override onlyOwner {
        _validateParams(params);
        _params = params;

        emit RiskParamsUpdated(
            params.confirmationsRequired,
            params.advanceRateBps,
            params.windowSeconds,
            params.newBorrowerCap,
            params.globalCap,
            params.minPayoutSats,
            params.btcPriceUsd,
            params.minPayoutCountForFullCredit,
            params.largePayoutThresholdSats,
            params.largePayoutDiscountBps,
            params.newBorrowerPeriodSeconds
        );
    }

    /**
     * @inheritdoc IRiskConfig
     */
    function setBtcPrice(uint64 btcPriceUsd) external override onlyOwner {
        if (btcPriceUsd == 0) revert InvalidParameter();

        uint64 oldPrice = _params.btcPriceUsd;
        _params.btcPriceUsd = btcPriceUsd;

        emit BtcPriceUpdated(oldPrice, btcPriceUsd);
    }

    /**
     * @notice Transfer ownership
     * @param newOwner New owner address
     */
    function transferOwnership(address newOwner) external onlyOwner {
        require(newOwner != address(0), "RiskConfig: zero address");
        owner = newOwner;
    }

    // ============================================
    // View Functions
    // ============================================

    /**
     * @inheritdoc IRiskConfig
     */
    function getRiskParams() external view override returns (RiskParams memory) {
        return _params;
    }

    /**
     * @inheritdoc IRiskConfig
     */
    function calculateCreditLimit(uint128 revenueSats) external view override returns (uint128) {
        // creditLimit = revenueSats * btcPriceUsd * advanceRateBps / BPS / SATS_PER_BTC
        // Convert to stablecoin decimals (6)

        uint256 btcValueUsd = (uint256(revenueSats) * _params.btcPriceUsd) / 1e8;
        uint256 creditLimitUsd = (btcValueUsd * _params.advanceRateBps) / 10_000;
        uint256 creditLimit = creditLimitUsd / 100; // 8 decimals to 6 decimals

        if (creditLimit > type(uint128).max) {
            return type(uint128).max;
        }

        return uint128(creditLimit);
    }

    /**
     * @inheritdoc IRiskConfig
     */
    function confirmationsRequired() external view override returns (uint32) {
        return _params.confirmationsRequired;
    }

    /**
     * @inheritdoc IRiskConfig
     */
    function advanceRateBps() external view override returns (uint32) {
        return _params.advanceRateBps;
    }

    /**
     * @inheritdoc IRiskConfig
     */
    function windowSeconds() external view override returns (uint32) {
        return _params.windowSeconds;
    }

    /**
     * @inheritdoc IRiskConfig
     */
    function newBorrowerCap() external view override returns (uint128) {
        return _params.newBorrowerCap;
    }

    /**
     * @inheritdoc IRiskConfig
     */
    function globalCap() external view override returns (uint128) {
        return _params.globalCap;
    }

    /**
     * @inheritdoc IRiskConfig
     */
    function minPayoutSats() external view override returns (uint64) {
        return _params.minPayoutSats;
    }

    /**
     * @inheritdoc IRiskConfig
     */
    function btcPriceUsd() external view override returns (uint64) {
        return _params.btcPriceUsd;
    }

    /**
     * @inheritdoc IRiskConfig
     */
    function minPayoutCountForFullCredit() external view override returns (uint32) {
        return _params.minPayoutCountForFullCredit;
    }

    /**
     * @inheritdoc IRiskConfig
     */
    function largePayoutThresholdSats() external view override returns (uint64) {
        return _params.largePayoutThresholdSats;
    }

    /**
     * @inheritdoc IRiskConfig
     */
    function largePayoutDiscountBps() external view override returns (uint32) {
        return _params.largePayoutDiscountBps;
    }

    /**
     * @inheritdoc IRiskConfig
     */
    function newBorrowerPeriodSeconds() external view override returns (uint32) {
        return _params.newBorrowerPeriodSeconds;
    }

    /**
     * @inheritdoc IRiskConfig
     */
    function applyPayoutHeuristics(uint64 amountSats, uint32 payoutCount)
        external
        view
        override
        returns (uint64 effectiveAmount)
    {
        effectiveAmount = amountSats;

        // Apply large payout discount if configured
        if (_params.largePayoutThresholdSats > 0 && amountSats > _params.largePayoutThresholdSats) {
            // Apply discount: effectiveAmount = amount * discountBps / 10000
            effectiveAmount = uint64((uint256(amountSats) * _params.largePayoutDiscountBps) / 10_000);
        }

        // If borrower hasn't met minimum payout count, cap the effective amount
        // This prevents single large deposit attacks for new borrowers
        if (_params.minPayoutCountForFullCredit > 0 && payoutCount < _params.minPayoutCountForFullCredit) {
            // Progressive cap: allow (payoutCount / minCount) * 100% of the amount
            // For simplicity, cap at minPayoutSats for first few payouts
            if (effectiveAmount > _params.minPayoutSats) {
                effectiveAmount = _params.minPayoutSats;
            }
        }
    }

    // ============================================
    // Internal Functions
    // ============================================

    function _validateParams(RiskParams memory params) internal pure {
        if (params.advanceRateBps > 10_000) revert AdvanceRateTooHigh();
        if (params.btcPriceUsd == 0) revert InvalidParameter();
        if (params.windowSeconds == 0) revert InvalidParameter();
        if (params.largePayoutDiscountBps > 10_000) revert InvalidParameter();
    }
}
