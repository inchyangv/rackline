// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import { GpuTypes } from "../types/GpuTypes.sol";

/**
 * @title IRiskPolicy
 * @notice Versioned borrowing-base and concentration policy (docs/gpu/underwriting-policy.md). No BTC price, no
 *         sats, no trailing payouts: inputs are eligible unpaid receivables, haircuts, caps, freshness windows.
 * @dev TEST_ONLY policy versions may not be bound to PRODUCTION facilities (mirrors the DB trigger, GPU-015).
 */
interface IRiskPolicy {
    struct Params {
        uint32 advanceRateBps;
        uint32 overdueHaircutBps;
        uint32 concentrationHaircutBps;
        uint32 collectabilityHaircutBps;
        uint64 evidenceValidityWindow; // seconds after provenAt
        uint64 checkpointMaxAge; // seconds
        uint64 controlObservationMaxAge; // seconds
        uint64 decisionValidity; // seconds
        uint64 maxTenor; // seconds
        uint32 reserveBps;
        uint32 dscrMinBps;
        uint256 perBorrowerCap;
        uint256 perGroupCap;
        uint256 perProviderCap;
        uint256 globalCap;
        bool testOnly;
    }

    event PolicyVersionPublished(bytes32 indexed policyVersionId, address approvedBy, bool testOnly);

    error PolicyUnknown(bytes32 policyVersionId);
    error TestOnlyPolicyInProduction(bytes32 policyVersionId);

    function params(bytes32 policyVersionId) external view returns (Params memory);
    function isTestOnly(bytes32 policyVersionId) external view returns (bool);
    /// @notice Pure evaluation of PIVOT §6.3 given already-summed inputs; the manager supplies live figures.
    function evaluate(
        bytes32 policyVersionId,
        uint256 eligibleUnpaid,
        uint256 approvedCap,
        uint256 debt,
        uint256 reserved,
        uint256 headroom,
        uint256 vaultCash
    ) external view returns (GpuTypes.DrawEvaluation memory);
}
