// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import { GpuTypes } from "../types/GpuTypes.sol";

/**
 * @title IRepaymentRouter
 * @notice Destination-side settlement recording and allocation (PIVOT §10.3, docs/gpu/evidence-and-reconciliation.md).
 *         Links settlementId -> destination receipt -> `repayFor` allocation. Only actual loan-currency receipts at the
 *         destination reduce debt; source receipts, legs and proofs never do (R2-D07).
 */
interface IRepaymentRouter {
    event DestinationReceiptRecorded(
        bytes32 indexed settlementId, address indexed token, uint256 amount, bytes32 sourceRef
    );
    event AllocationApplied(
        bytes32 indexed settlementId,
        GpuTypes.FacilityId indexed facilityId,
        uint256 amount,
        uint256 applied,
        uint256 excess
    );
    event ExcessRefunded(GpuTypes.FacilityId indexed facilityId, address indexed to, uint256 amount);

    error AllocationExceedsReceipt(bytes32 settlementId, uint256 allocated, uint256 received);
    error WrongAsset(address expected, address actual);
    error DuplicateSettlement(bytes32 settlementId);
    error NothingToRefund(GpuTypes.FacilityId facilityId);

    function received(bytes32 settlementId) external view returns (uint256 total, uint256 allocated);
    function refundable(GpuTypes.FacilityId facilityId) external view returns (uint256);
    function recordDestinationReceipt(bytes32 settlementId, uint256 amount, bytes32 sourceRef) external;
    function allocate(bytes32 settlementId, GpuTypes.FacilityId facilityId, uint256 amount)
        external
        returns (GpuTypes.RepayResult memory);
    function refundExcess(GpuTypes.FacilityId facilityId, address to) external returns (uint256);
}
