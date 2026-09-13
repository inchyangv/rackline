// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import { GpuTypes } from "../types/GpuTypes.sol";

/**
 * @title IRevenueEscrow
 * @notice Source-chain controlled receiver (GPU-077/037). Emits the internal source events of
 *         test/fixtures/gpu/attestcoin/source-events-v1.abi.json. Amounts are exact balance deltas measured by the
 *         escrow; there is no `notify(amount)` and re-reporting an existing balance is impossible.
 * @dev Unattributed deposits are UNCLASSIFIED until reconciled; borrower self-transfers are never revenue.
 */
interface IRevenueEscrow {
    event ObligationRecognized(
        bytes32 indexed accountKey,
        bytes32 indexed obligationRef,
        address indexed issuer,
        address payer,
        address payee,
        uint256 amount,
        uint64 dueAt,
        uint32 revision
    );
    event ObligationAssigned(
        bytes32 indexed accountKey, bytes32 indexed obligationRef, bytes32 indexed facilityKey, uint32 revision
    );
    event ObligationCorrected(
        bytes32 indexed accountKey, bytes32 indexed obligationRef, int256 delta, uint32 revision, uint8 reason
    );
    event PayoutReceived(
        bytes32 indexed accountKey,
        bytes32 indexed obligationRef,
        address indexed token,
        address payer,
        uint256 amount,
        uint64 settlementSeq
    );
    event PayoutCancelled(
        bytes32 indexed accountKey, bytes32 indexed obligationRef, uint64 settlementSeq, uint256 amount
    );
    event SourceCheckpoint(
        bytes32 indexed accountKey,
        uint64 checkpointSeq,
        uint32 latestRevision,
        uint256 openAmount,
        uint256 paidCumulative
    );
    event Swept(
        bytes32 indexed accountKey,
        address indexed token,
        uint256 repaymentShare,
        uint256 operatorShare,
        uint64 settlementSeq
    );
    event Released(bytes32 indexed accountKey, address receiverReturnedTo, uint64 at);

    error NotIssuer(address caller);
    error NotController(address caller);
    error NoBalanceDelta();
    error UnsupportedToken(address token);
    error ReleaseBlocked(string reason);
    error RevisionNotMonotonic(uint32 current, uint32 given);

    function accountKey() external view returns (bytes32);
    function settlementSeq() external view returns (uint64);
    function controller() external view returns (address);
    function isReleased() external view returns (bool);

    // ------------------------------------------------------------------ GPU-037 additions (controlled account)

    /// @notice Debt-sweep priority entry: seniority by array order, each facility up to `target` (asserted cap).
    struct FacilityAllocation {
        GpuTypes.FacilityId facilityId;
        uint256 target;
    }

    /// @notice Allowed upstream claim: exact (target, selector); the recipient argument at `recipientArgIndex`
    ///         (0-based ABI word index) must be this escrow. Claim success is never control evidence.
    struct ClaimTarget {
        address target;
        bytes4 selector;
        uint8 recipientArgIndex;
    }

    /// @notice Waterfall for one control-agreement version. Order is fixed: operating allowance → reserve →
    ///         debt sweep (to the settlement leg, by facility seniority) → residual to the borrower.
    struct Waterfall {
        uint32 version;
        address token;
        uint16 operatingBps;
        uint256 operatingCapPerSweep;
        address operatingRecipient;
        uint256 reserveTarget;
        address settlementLeg;
        address residualRecipient;
        FacilityAllocation[] facilities;
        ClaimTarget[] claimTargets;
    }

    event WaterfallSet(bytes32 indexed agreementId, uint32 indexed version, address token, address settlementLeg);
    event PayoutSwept(
        uint64 indexed payoutSeq,
        uint32 indexed version,
        uint256 amount,
        uint256 operating,
        uint256 reserve,
        uint256 debt,
        uint256 residual
    );
    event SweptToSettlement(
        GpuTypes.FacilityId indexed facilityId, bytes32 indexed settlementId, uint64 indexed payoutSeq, uint256 amount
    );
    event ClaimExecuted(address indexed target, bytes4 indexed selector, uint256 measuredDelta);
    event ClaimForwarded(bytes32 indexed obligationRef, bytes32 indexed settlementId, uint256 amount);
    event UnattributedRefunded(address indexed token, address indexed to, uint256 amount);
    event RefundPendingSet(bool pending, string reason);

    error NotRole(bytes32 role, address caller);
    error NoWaterfall(uint32 version);
    error WaterfallExists(uint32 version);
    error WaterfallVersionMismatch(uint32 registryVersion, uint32 given);
    error InvalidWaterfall(string reason);
    error PayoutNotSweepable(uint64 payoutSeq, string reason);
    error AlreadySwept(uint64 payoutSeq);
    error ClaimNotAllowed(address target, bytes4 selector);
    error ClaimRecipientMismatch(address expected, address actual);
    error ClaimFailed(bytes reason);
    error AlreadyReleased();
    error Reentrancy();
    error TransferFailed();
    error MeasuredDeltaMismatch(uint256 expected, uint256 measured);
}
