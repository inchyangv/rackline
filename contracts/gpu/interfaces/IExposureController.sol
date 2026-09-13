// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import { GpuTypes } from "../types/GpuTypes.sol";

/// @notice Minimal view the exposure controller needs from the vault (GPU-034 implements it).
interface IVaultCashView {
    function availableCash() external view returns (uint256);
}

/**
 * @title IExposureController
 * @notice On-chain borrowing base, concentration headroom and execution reservations (GPU-035.b, PIVOT §6.3).
 * @dev  - Exposure of a category = Σ authoritative ledger debt (principal + fees + accrued interest, via IDebtLedger)
 *         of every facility in the category + every ACTIVE reservation in it. Headroom = cap − exposure.
 *       - A reservation is released only by an explicit on-chain cancel/expire/consume call; an off-chain timeout
 *         alone releases nothing. Consumption records the draw on the ledger in the same transaction, so reserved
 *         decreases exactly when debt increases (no double count, no gap).
 *       - Authority changes (policy version, facility authorization, control agreement version) invalidate
 *         reservations taken under the old authority. A limit decrease never erases existing debt.
 */
interface IExposureController {
    enum ReservationState {
        NONE,
        ACTIVE,
        CONSUMED,
        CANCELLED,
        EXPIRED
    }

    struct Authorization {
        uint256 limit; // approved facility cap in loan-asset base units
        bytes32 policyVersionId;
        bytes32 controlAgreementId;
        uint32 controlVersion;
        uint64 validUntil; // credit decision validity
        uint64 epoch; // bumps on every setAuthorization
        bool exists;
    }

    struct Reservation {
        GpuTypes.FacilityId facilityId;
        uint256 amount;
        uint64 approvalNonce;
        uint64 expiresAt;
        bytes32 policyVersionId;
        uint64 authorizationEpoch;
        ReservationState state;
    }

    event FacilityEnrolled(GpuTypes.FacilityId indexed facilityId, bytes32 indexed borrowerId, bytes32 indexed groupId);
    event AuthorizationSet(
        GpuTypes.FacilityId indexed facilityId, uint256 limit, bytes32 policyVersionId, uint64 validUntil, uint64 epoch
    );
    event Reserved(
        bytes32 indexed reservationId, GpuTypes.FacilityId indexed facilityId, uint256 amount, uint64 expiresAt
    );
    event ReservationConsumed(bytes32 indexed reservationId, GpuTypes.FacilityId indexed facilityId, uint256 amount);
    event ReservationReleased(bytes32 indexed reservationId, ReservationState state);

    error NotManager(address caller);
    error FacilityNotEnrolled(GpuTypes.FacilityId facilityId);
    error FacilityAlreadyEnrolled(GpuTypes.FacilityId facilityId);
    error NoAuthorization(GpuTypes.FacilityId facilityId);
    error AuthorizationExpired(GpuTypes.FacilityId facilityId, uint64 validUntil);
    error PolicyStale(bytes32 policyVersionId);
    error ControlNotUsable(bytes32 agreementId, uint32 version);
    error FacilityLimitZero(GpuTypes.FacilityId facilityId);
    error InsufficientHeadroom(uint256 requested, uint256 available);
    error NonceUsed(GpuTypes.FacilityId facilityId, uint64 approvalNonce);
    error ReservationNotActive(bytes32 reservationId, ReservationState state);
    error ReservationExpired(bytes32 reservationId, uint64 expiresAt);
    error ReservationInvalidated(bytes32 reservationId, string reason);
    error PilotValuationUnsupported(string reason);

    function authorization(GpuTypes.FacilityId facilityId) external view returns (Authorization memory);
    function reservation(bytes32 reservationId) external view returns (Reservation memory);
    function reservedOf(GpuTypes.FacilityId facilityId) external view returns (uint256);
    function exposureOfBorrower(bytes32 borrowerId, uint64 at) external view returns (uint256);
    function exposureOfGroup(bytes32 groupId, uint64 at) external view returns (uint256);
    function exposureOfProvider(GpuTypes.ProviderId providerId, uint64 at) external view returns (uint256);
    function exposureGlobal(uint64 at) external view returns (uint256);
    function evaluateDraw(GpuTypes.FacilityId facilityId) external view returns (GpuTypes.DrawEvaluation memory);

    function reserve(GpuTypes.FacilityId facilityId, uint256 amount, uint64 approvalNonce, uint64 expiresAt)
        external
        returns (bytes32 reservationId);
    function consumeReservation(bytes32 reservationId) external;
    function cancelReservation(bytes32 reservationId) external;
    function expireReservation(bytes32 reservationId) external;
}
