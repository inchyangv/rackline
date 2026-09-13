// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import { GpuTypes } from "./types/GpuTypes.sol";
import { IRiskPolicy } from "./interfaces/IRiskPolicy.sol";
import { IProtocolRoles } from "./interfaces/IProtocolRoles.sol";

/**
 * @title GpuRiskPolicy
 * @notice Versioned borrowing-base parameters (GPU-035.b; docs/gpu/underwriting-policy.md §3, §5, §6). Published by
 *         the UNDERWRITER; every publish is a new immutable version and becomes the current one. Nothing here is a
 *         limit by itself: the ExposureController combines a version with live ledger, receivable and vault figures.
 * @dev  - A cap of 0 is "no new execution", never "unlimited" (`CapNotSet`).
 *      - `evaluate` is pure arithmetic over already-summed inputs (PIVOT §6.3): eligible → haircuts → advance rate
 *        → min(base room, facility room, category headroom, vault cash). Every division floors.
 *      - `checkpointToleranceBps` is the reconciliation tolerance between the issuer checkpoint and our Σ unpaid;
 *        the pilot value is 0 (no bounded lag, underwriting-policy §6).
 */
contract GpuRiskPolicy is IRiskPolicy {
    IProtocolRoles public immutable ROLES;

    mapping(bytes32 => Params) private _params;
    mapping(bytes32 => bool) private _exists;
    mapping(bytes32 => uint32) private _checkpointToleranceBps;
    bytes32 public currentVersion;
    uint64 public versionCount;

    event PolicyVersionActivated(bytes32 indexed policyVersionId, uint64 ordinal);

    error NotUnderwriter(address caller);
    error PolicyExists(bytes32 policyVersionId);
    error InvalidParams(string reason);
    error CapNotSet(string category);
    error PolicyNotCurrent(bytes32 policyVersionId, bytes32 current);

    constructor(IProtocolRoles roles) {
        ROLES = roles;
    }

    modifier onlyUnderwriter() {
        if (!ROLES.hasRole(ROLES.UNDERWRITER(), msg.sender)) revert NotUnderwriter(msg.sender);
        _;
    }

    // ------------------------------------------------------------------ publishing

    /// @notice Publish a new policy version and make it current. Old versions stay readable but are never current
    ///         again (authorizations pinned to them are rejected by the ExposureController).
    function publish(bytes32 policyVersionId, Params calldata p, uint32 checkpointToleranceBps)
        external
        onlyUnderwriter
    {
        if (policyVersionId == bytes32(0)) revert InvalidParams("id");
        if (_exists[policyVersionId]) revert PolicyExists(policyVersionId);
        if (p.advanceRateBps == 0 || p.advanceRateBps > 10_000) revert InvalidParams("advanceRate");
        if (
            p.overdueHaircutBps > 10_000 || p.concentrationHaircutBps > 10_000 || p.collectabilityHaircutBps > 10_000
                || checkpointToleranceBps > 10_000
        ) revert InvalidParams("bps");
        if (p.concentrationHaircutBps + p.collectabilityHaircutBps > 10_000) revert InvalidParams("haircuts");
        if (p.checkpointMaxAge == 0 || p.evidenceValidityWindow == 0 || p.decisionValidity == 0) {
            revert InvalidParams("windows");
        }
        _params[policyVersionId] = p;
        _exists[policyVersionId] = true;
        _checkpointToleranceBps[policyVersionId] = checkpointToleranceBps;
        currentVersion = policyVersionId;
        versionCount += 1;
        emit PolicyVersionPublished(policyVersionId, msg.sender, p.testOnly);
        emit PolicyVersionActivated(policyVersionId, versionCount);
    }

    // ------------------------------------------------------------------ views

    function params(bytes32 policyVersionId) public view override returns (Params memory) {
        if (!_exists[policyVersionId]) revert PolicyUnknown(policyVersionId);
        return _params[policyVersionId];
    }

    function isTestOnly(bytes32 policyVersionId) external view override returns (bool) {
        if (!_exists[policyVersionId]) revert PolicyUnknown(policyVersionId);
        return _params[policyVersionId].testOnly;
    }

    function checkpointToleranceBps(bytes32 policyVersionId) external view returns (uint32) {
        if (!_exists[policyVersionId]) revert PolicyUnknown(policyVersionId);
        return _checkpointToleranceBps[policyVersionId];
    }

    function isCurrent(bytes32 policyVersionId) public view returns (bool) {
        return _exists[policyVersionId] && policyVersionId == currentVersion;
    }

    function requireCurrent(bytes32 policyVersionId) external view {
        if (!isCurrent(policyVersionId)) revert PolicyNotCurrent(policyVersionId, currentVersion);
    }

    /// @notice Category caps of a version; reverts `CapNotSet` when any is 0 (cap=0 forbids new execution).
    function caps(bytes32 policyVersionId)
        external
        view
        returns (uint256 perBorrower, uint256 perGroup, uint256 perProvider, uint256 global)
    {
        Params storage p = _params[policyVersionId];
        if (!_exists[policyVersionId]) revert PolicyUnknown(policyVersionId);
        if (p.perBorrowerCap == 0) revert CapNotSet("perBorrower");
        if (p.perGroupCap == 0) revert CapNotSet("perGroup");
        if (p.perProviderCap == 0) revert CapNotSet("perProvider");
        if (p.globalCap == 0) revert CapNotSet("global");
        return (p.perBorrowerCap, p.perGroupCap, p.perProviderCap, p.globalCap);
    }

    /// @inheritdoc IRiskPolicy
    function evaluate(
        bytes32 policyVersionId,
        uint256 eligibleUnpaid,
        uint256 approvedCap,
        uint256 debt,
        uint256 reserved,
        uint256 headroom,
        uint256 vaultCash
    ) external view override returns (GpuTypes.DrawEvaluation memory e) {
        Params memory p = params(policyVersionId);
        uint256 haircut = uint256(p.concentrationHaircutBps) + uint256(p.collectabilityHaircutBps);
        uint256 eligible = eligibleUnpaid * (10_000 - haircut) / 10_000;
        uint256 receivableLimit = eligible * p.advanceRateBps / 10_000;
        uint256 committed = debt + reserved;
        uint256 baseRoom = receivableLimit > committed ? receivableLimit - committed : 0;
        uint256 facilityRoom = approvedCap > committed ? approvedCap - committed : 0;
        uint256 available = baseRoom;
        if (facilityRoom < available) available = facilityRoom;
        if (headroom < available) available = headroom;
        if (vaultCash < available) available = vaultCash;
        e = GpuTypes.DrawEvaluation({
            eligibleReceivables: eligible,
            receivableLimit: receivableLimit,
            facilityLimit: approvedCap,
            facilityRoom: facilityRoom,
            headroom: headroom,
            vaultCash: vaultCash,
            availableDraw: available,
            evidenceValidUntil: 0, // filled by the controller from the receivable book
            checkpointAge: 0
        });
    }
}
