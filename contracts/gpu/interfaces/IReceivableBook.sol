// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import { GpuTypes } from "../types/GpuTypes.sol";

/**
 * @title IReceivableBook
 * @notice Destination-side mirror of natively proven source receivables (GPU-035.a). Receivables are created and
 *         changed only by consuming proof-bound records through the EvidenceBook; every claimed field is checked
 *         against the verified log (`dataHash`) before it changes a balance.
 * @dev  - Meaning-driven transitions mirror the TEST_ONLY `SourceEscrow` state machine (GPU-077); revisions are
 *         applied strictly in order (gap or stale revision ⇒ revert, nothing consumed).
 *       - A PAID/CANCELLED receivable contributes 0 forever; it can never be re-recognized as new base.
 *       - Eligible unpaid per facility requires a fresh `SourceCheckpoint` whose `latestRevision` equals the number
 *         of obligation-state events we consumed for the account and whose `openAmount` reconciles with our Σ unpaid
 *         (R2-D06). Missing / stale / gapped checkpoint ⇒ 0 for that account.
 *       - Amounts are source-token base units; the pilot requires a 1:1 stablecoin pair (facility registration
 *         checks decimals), valuation with rate provenance is a later ADR.
 */
interface IReceivableBook {
    enum ReceivableState {
        NONE,
        OPEN,
        ASSIGNED,
        PAID,
        CANCELLED
    }

    struct Facility {
        bytes32 borrowerId;
        GpuTypes.ProviderId providerId;
        GpuTypes.AssetRef sourceAsset; // admitted source-chain asset the receivables are denominated in
        bool exists;
    }

    struct Receivable {
        GpuTypes.ProviderId providerId;
        GpuTypes.AccountKey accountKey;
        bytes32 obligationRef;
        address payer;
        address token; // v2 recognition binds this before any payment; v1 remains ineligible
        bool denominationProven;
        uint256 net;
        uint256 paid;
        uint32 revision; // mirrors SourceEscrow.Obligation.revision
        uint64 dueAt; // issuer-claimed
        uint64 evidenceValidUntil; // policy validity of the latest obligation-defining proof
        GpuTypes.FacilityId facilityId;
        ReceivableState state;
        bool disputed;
    }

    struct Checkpoint {
        uint64 checkpointSeq;
        uint32 latestRevision;
        uint256 openAmount;
        uint256 paidCumulative;
        uint64 provenAt; // destination block time of consumption
        uint64 observedAt; // source contract block.timestamp, never destination submission time
        uint64 protectedUntil; // immutable source reservation prevents intervening paid/cancel changes
        bool exists;
    }

    /// @notice One verified log to apply. Topics/data are the exact log content; they are re-hashed against the
    ///         EvidenceBook record before use, so nothing here is trusted on its own.
    struct ReceivableClaim {
        uint32 logOrdinal;
        GpuTypes.AccountKey accountKey; // topics[1]
        bytes32 topic2; // obligationRef (0 for SourceCheckpoint)
        bytes32 topic3; // issuer / facilityKey / token as bytes32; 0 when the event has 3 or fewer topics
        bytes data; // unindexed data exactly as emitted
        uint64 validUntil; // policy validity to record for this proof
    }

    struct AccountStats {
        uint32 eventsConsumed; // == SourceEscrow.accountLatestRevision when fully caught up
        uint256 openAmount; // Σ (net - paid) over OPEN/ASSIGNED receivables of the account
        uint256 paidCumulative;
    }

    event FacilityRegistered(
        GpuTypes.FacilityId indexed facilityId, bytes32 indexed borrowerId, GpuTypes.ProviderId indexed providerId
    );
    event ReceivableRecognized(
        bytes32 indexed receivableId, GpuTypes.AccountKey indexed accountKey, bytes32 indexed obligationRef, uint256 net
    );
    event ReceivableAssigned(bytes32 indexed receivableId, GpuTypes.FacilityId indexed facilityId, uint32 revision);
    event ReceivableCorrected(bytes32 indexed receivableId, int256 delta, uint32 revision, uint8 reason);
    event ReceivablePaid(bytes32 indexed receivableId, uint256 amount, uint64 settlementSeq, uint256 unpaidAfter);
    event ReceivablePayoutCancelled(bytes32 indexed receivableId, uint256 amount, uint64 settlementSeq);
    event UnattributedPayoutRecorded(GpuTypes.AccountKey indexed accountKey, uint256 amount, uint64 settlementSeq);
    event CheckpointRecorded(GpuTypes.AccountKey indexed accountKey, uint64 checkpointSeq, uint32 latestRevision);
    event ReceivableDisputed(bytes32 indexed receivableId, bool disputed, string reason);

    error FacilityUnknown(GpuTypes.FacilityId facilityId);
    error FacilityExists(GpuTypes.FacilityId facilityId);
    error UnknownTopic(bytes32 topic0);
    error MeaningMismatch(GpuTypes.EvidenceMeaning expected, GpuTypes.EvidenceMeaning actual);
    error ClaimMismatch(bytes32 expectedDataHash, bytes32 claimedDataHash);
    error ReceivableExists(bytes32 receivableId);
    error ReceivableUnknown(bytes32 receivableId);
    error ReceivableNotOpen(bytes32 receivableId, ReceivableState state);
    error RevisionGap(bytes32 receivableId, uint32 expected, uint32 actual);
    error RevisionStale(bytes32 receivableId, uint32 current, uint32 actual);
    error AccountNotOfBorrower(GpuTypes.AccountKey accountKey, bytes32 borrowerId);
    error AlreadyAssigned(bytes32 receivableId, GpuTypes.FacilityId facilityId);
    error FacilityKeyMismatch(bytes32 facilityKey);
    error TokenMismatch(address expected, address actual);
    error Overpayment(bytes32 receivableId, uint256 remaining, uint256 amount);
    error SettlementSeen(uint64 settlementSeq);
    error SettlementUnknown(uint64 settlementSeq);
    error CheckpointNotNewer(uint64 currentSeq, uint64 claimedSeq);
    error CorrectionBelowPaid(bytes32 receivableId, uint256 paid, int256 delta);
    error CancelMustZeroOpen(bytes32 receivableId, uint256 open);
    error PilotValuationUnsupported(string reason);

    function facility(GpuTypes.FacilityId facilityId) external view returns (Facility memory);
    function receivableId(GpuTypes.ProviderId providerId, GpuTypes.AccountKey accountKey, bytes32 obligationRef)
        external
        pure
        returns (bytes32);
    function receivable(bytes32 id) external view returns (Receivable memory);
    function checkpoint(GpuTypes.ProviderId providerId, GpuTypes.AccountKey accountKey)
        external
        view
        returns (Checkpoint memory);
    function accountStats(GpuTypes.ProviderId providerId, GpuTypes.AccountKey accountKey)
        external
        view
        returns (AccountStats memory);
    function facilityKey(GpuTypes.FacilityId facilityId) external pure returns (bytes32);

    /**
     * @notice Σ haircut-adjusted unpaid of ASSIGNED, undisputed, unexpired receivables of `facilityId` whose account
     *         has a fresh, reconciled checkpoint. Returns the base in source-asset units, the earliest evidence expiry
     *         among included receivables and the oldest checkpoint age used (0 when nothing included).
     */
    function eligibleUnpaid(
        GpuTypes.FacilityId facilityId,
        uint64 checkpointMaxAge,
        uint32 checkpointToleranceBps,
        uint32 overdueHaircutBps,
        uint64 at
    ) external view returns (uint256 eligible, uint64 evidenceValidUntil, uint64 checkpointAge);

    /**
     * @notice Consume verified logs through the EvidenceBook and apply them to receivables.
     */
    function ingest(
        GpuTypes.ProviderId providerId,
        GpuTypes.NativeProofEnvelope calldata envelope,
        address expectedEmitter,
        bytes32[] calldata topic0s,
        ReceivableClaim[] calldata claims
    ) external;
}
