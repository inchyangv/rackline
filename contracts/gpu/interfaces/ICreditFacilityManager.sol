// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import { GpuTypes } from "../types/GpuTypes.sol";

/**
 * @title ICreditFacilityManager
 * @notice Facility lifecycle, draws and repayments (PIVOT §7 CreditFacilityManager; states in
 *         docs/gpu/permissions-and-states.md §4). Every draw re-evaluates the borrowing base, the credit
 * authorization,
 *         the control agreement version/freshness and vault cash. Draw pause never blocks `repayFor`.
 * @dev There is no `pauseRepayments` on the product path. No function accepts a testnet credit grant.
 */
interface ICreditFacilityManager {
    event FacilityOpened(
        GpuTypes.FacilityId indexed facilityId,
        bytes32 indexed borrowerId,
        GpuTypes.ExecutionProfile profile,
        bytes32 termsVersionId
    );
    event StateChanged(
        GpuTypes.FacilityId indexed facilityId,
        GpuTypes.FacilityState from,
        GpuTypes.FacilityState to,
        bytes32 trigger,
        address authority
    );
    event AuthorizationAnchored(
        GpuTypes.FacilityId indexed facilityId,
        bytes32 indexed decisionHash,
        uint256 limit,
        uint64 validUntil,
        bytes32 manifestHash
    );
    event Borrowed(GpuTypes.FacilityId indexed facilityId, uint256 amount, uint256 newDebt, bytes32 decisionHash);
    event Repaid(
        GpuTypes.FacilityId indexed facilityId,
        address indexed payer,
        uint256 requested,
        uint256 received,
        uint256 applied,
        uint256 excess,
        uint256 newDebt
    );
    event DrawsPaused(address indexed by, bool paused);

    error NativeEvidenceRequired(GpuTypes.FacilityId facilityId);
    error AuthorizationMissingOrExpired(GpuTypes.FacilityId facilityId);
    error AuthorizationManifestMismatch(bytes32 expected, bytes32 actual);
    error ControlInsufficientOrStale(GpuTypes.FacilityId facilityId);
    error ExceedsAvailableDraw(uint256 requested, uint256 available);
    error DrawsArePaused();
    error IllegalTransition(GpuTypes.FacilityState from, GpuTypes.FacilityState to);
    error ProfileMismatch(GpuTypes.ExecutionProfile expected, GpuTypes.ExecutionProfile actual);
    error NotBorrower(GpuTypes.FacilityId facilityId, address caller);
    error DebtOutstanding(GpuTypes.FacilityId facilityId, uint256 debt);

    function facility(GpuTypes.FacilityId facilityId) external view returns (GpuTypes.FacilityLedgerView memory);
    function state(GpuTypes.FacilityId facilityId) external view returns (GpuTypes.FacilityState);
    function evaluateDraw(GpuTypes.FacilityId facilityId, uint256 amount)
        external
        view
        returns (GpuTypes.DrawEvaluation memory);
    function anchorAuthorization(
        GpuTypes.CreditAuthorization calldata auth,
        GpuTypes.SupplementaryAssertion calldata underwriterApproval
    ) external;
    function borrow(GpuTypes.FacilityId facilityId, uint256 amount, uint256 minReceived) external;
    /// @notice Anyone may repay for a facility; funds are pulled from `msg.sender` in the loan asset.
    function repayFor(GpuTypes.FacilityId facilityId, uint256 amount) external returns (GpuTypes.RepayResult memory);
    function pauseDraws(bool paused) external;
    function drawsPaused() external view returns (bool);
}
