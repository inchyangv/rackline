// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

/**
 * @title InterestMath
 * @notice Exact-numerator simple interest (docs/gpu/accounting.md §2, GPU-012 reference model).
 * @dev `accum = Σ principal × rateBps × seconds` is kept exactly; `units = accum / DENOM` (floor). Because the
 *      numerator is never rounded, the interest owed does not depend on how often accrual runs (AC-03) and no dust
 *      is lost between accruals. Payments subtract `units × DENOM` from the numerator, so a payment can never
 *      erase the fractional remainder (AR-01 corrected). Income rounds down: the borrower is never charged a
 *      fraction of a unit.
 */
library InterestMath {
    uint256 internal constant BPS = 10_000;
    uint256 internal constant YEAR = 365 days; // ACT/365 in seconds
    uint256 internal constant DENOM = BPS * YEAR; // one unit of interest == DENOM accumulator units

    /// @dev Principal cap so that principal × rateBps × seconds cannot overflow uint256 for any uint32 rate and
    ///      uint64 elapsed time: 2^128 × 2^32 × 2^64 = 2^224 < 2^256.
    uint256 internal constant MAX_PRINCIPAL = type(uint128).max;

    error PrincipalTooLarge(uint256 principal);

    /// @notice Numerator growth for `principal` at `rateBps` over `elapsed` seconds (exact, no rounding).
    function growth(uint256 principal, uint32 rateBps, uint64 elapsed) internal pure returns (uint256) {
        if (principal > MAX_PRINCIPAL) revert PrincipalTooLarge(principal);
        return principal * uint256(rateBps) * uint256(elapsed);
    }

    /// @notice Whole interest units represented by `accum` (floor).
    function units(uint256 accum) internal pure returns (uint256) {
        return accum / DENOM;
    }

    /// @notice Numerator amount to subtract when `unitsPaid` units of interest are paid.
    function toAccum(uint256 unitsPaid) internal pure returns (uint256) {
        return unitsPaid * DENOM;
    }
}
