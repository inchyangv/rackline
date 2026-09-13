// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import { GpuTypes } from "../types/GpuTypes.sol";

/**
 * @title IDebtLedger
 * @notice The single facility ledger (docs/gpu/accounting.md): principal, unpaid interest (exact accumulator), fees,
 *         forward-only rate segments, waterfall allocation. Both manager and vault read this ledger; neither keeps a
 *         second copy (AR-02/03 corrected).
 * @dev Interest: ACT/365 simple on principal, per rate segment, floor on units, no capitalization unless terms say so.
 *      Allocation order: fees -> unpaid interest -> principal -> excess.
 */
interface IDebtLedger {
    event Accrued(
        GpuTypes.FacilityId indexed facilityId, uint256 interestUnits, uint64 from, uint64 to, uint32 rateBps
    );
    event RateSegmentAdded(GpuTypes.FacilityId indexed facilityId, uint64 start, uint32 rateBps);
    event Drawn(GpuTypes.FacilityId indexed facilityId, uint256 amount, uint256 newPrincipal);
    event Allocated(
        GpuTypes.FacilityId indexed facilityId,
        uint256 feePaid,
        uint256 interestPaid,
        uint256 principalPaid,
        uint256 excess,
        uint256 newDebt
    );
    event FeeCharged(GpuTypes.FacilityId indexed facilityId, uint256 amount, bytes32 reason);
    event AccrualFrozen(GpuTypes.FacilityId indexed facilityId, uint64 at);

    error AccrualBackwards(uint64 last, uint64 requested);
    error ZeroAmount();
    error CapitalizationDisabled();
    error NotLedgerWriter(address caller);

    function view_(GpuTypes.FacilityId facilityId) external view returns (GpuTypes.FacilityLedgerView memory);
    function unpaidInterestAt(GpuTypes.FacilityId facilityId, uint64 at) external view returns (uint256);
    function legalDebtAt(GpuTypes.FacilityId facilityId, uint64 at) external view returns (uint256);
    function accrue(GpuTypes.FacilityId facilityId) external;
    function setRate(GpuTypes.FacilityId facilityId, uint32 rateBps) external;
    function recordDraw(GpuTypes.FacilityId facilityId, uint256 amount) external;
    function recordFee(GpuTypes.FacilityId facilityId, uint256 amount, bytes32 reason) external;
    /// @notice Apply received loan-currency cash to the facility; returns the split.
    function allocate(GpuTypes.FacilityId facilityId, uint256 received) external returns (GpuTypes.RepayResult memory);
    function freezeAccrual(GpuTypes.FacilityId facilityId) external;
}
