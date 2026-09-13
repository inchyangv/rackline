// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import { GpuTypes } from "../types/GpuTypes.sol";

/**
 * @title IControlRegistry
 * @notice Payment-control agreements: grade, version, receiver, expiry, observation freshness (GPU-032).
 * @dev A registry flag never replaces a partner-side lock; grade E2 is recorded only with a PoC reference and
 *      partner recognition (docs/gpu/permissions-and-states.md §3). Release requires debt == 0 and the reconciliation
 *      window to have closed.
 */
interface IControlRegistry {
    struct Agreement {
        bytes32 agreementId;
        bytes32 borrowerId;
        GpuTypes.AccountKey accountKey;
        GpuTypes.ControlGrade grade;
        uint32 version;
        address receiver;
        uint64 receiverChainId;
        bytes32 agreementHash;
        uint64 effectiveFrom;
        uint64 effectiveTo;
        uint64 lastObservedAt;
        bytes32 pocRef;
    }

    event AgreementVersioned(
        bytes32 indexed agreementId, uint32 version, GpuTypes.ControlGrade grade, bytes32 agreementHash
    );
    event ControlObserved(
        bytes32 indexed agreementId, GpuTypes.ControlGrade observedGrade, address receiver, uint64 at
    );
    event ControlRevoked(bytes32 indexed agreementId, string reason, uint64 at);
    event ControlReleased(bytes32 indexed agreementId, uint64 at);

    error GradeInsufficient(GpuTypes.ControlGrade required, GpuTypes.ControlGrade actual);
    error ObservationStale(uint64 lastObservedAt, uint64 maxAge);
    error AgreementNotEffective(bytes32 agreementId, uint32 version);
    error ReleaseBlocked(string reason);
    error E2RequiresPoc(bytes32 agreementId);

    function agreement(bytes32 agreementId) external view returns (Agreement memory);
    function isEffective(bytes32 agreementId, uint32 version, uint64 at) external view returns (bool);
    function isFresh(bytes32 agreementId, uint64 maxAge) external view returns (bool);
    function controlObservationMaxAge() external view returns (uint64);
}
