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

    /// @notice One repayment leg fully accounted: `received == feePaid + interestPaid + principalPaid + excess`.
    event Repaid(
        GpuTypes.FacilityId indexed facilityId,
        address indexed payer,
        bytes32 indexed settlementRef,
        uint256 requested,
        uint256 received,
        uint256 applied,
        uint256 feePaid,
        uint256 interestPaid,
        uint256 principalPaid,
        uint256 excess,
        uint256 newDebt
    );

    error AllocationExceedsReceipt(bytes32 settlementId, uint256 allocated, uint256 received);
    error WrongAsset(address expected, address actual);
    error DuplicateSettlement(bytes32 settlementId);
    error NothingToRefund(GpuTypes.FacilityId facilityId);
    error NothingToRepay(GpuTypes.FacilityId facilityId);
    error UnknownSettlement(bytes32 settlementId);
    error NotSettlementLeg(address caller);
    error NotRefundAuthority(GpuTypes.FacilityId facilityId, address caller);
    error TransferFailed();
    error Reentrancy();
    error ZeroAmount();

    /**
     * @notice Direct repayment by anyone (third parties allowed): pulls `amount` of the loan asset from the caller
     *         into the vault, allocates exactly what arrived (fees -> interest -> principal -> excess) and credits
     *         excess to the borrower's refundable balance. No proof, signature or evidence is involved.
     */
    function repayFor(GpuTypes.FacilityId facilityId, uint256 amount, bytes32 settlementRef)
        external
        returns (GpuTypes.RepayResult memory);
    /// @notice Cap-before-transfer: pulls only `min(maxAmount, current legal debt)` so a direct payer never overpays.
    function repayExact(GpuTypes.FacilityId facilityId, uint256 maxAmount)
        external
        returns (GpuTypes.RepayResult memory);
    /// @notice Settlement-leg arrival recorded and allocated to one facility in one step (TREASURY/RELAYER only).
    function receiveSettlement(GpuTypes.FacilityId facilityId, bytes32 settlementId, uint256 amount)
        external
        returns (GpuTypes.RepayResult memory);
    /// @notice Amount of a recorded settlement receipt that is still held by the router (not yet allocated).
    function unallocated(bytes32 settlementId) external view returns (uint256);

    function received(bytes32 settlementId) external view returns (uint256 total, uint256 allocated);
    function refundable(GpuTypes.FacilityId facilityId) external view returns (uint256);
    function recordDestinationReceipt(bytes32 settlementId, uint256 amount, bytes32 sourceRef) external;
    function allocate(bytes32 settlementId, GpuTypes.FacilityId facilityId, uint256 amount)
        external
        returns (GpuTypes.RepayResult memory);
    function refundExcess(GpuTypes.FacilityId facilityId, address to) external returns (uint256);
}
