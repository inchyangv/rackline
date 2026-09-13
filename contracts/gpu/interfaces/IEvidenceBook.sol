// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import { GpuTypes } from "../types/GpuTypes.sol";
import { IRevenueVerifier } from "./IRevenueVerifier.sol";

/**
 * @title IEvidenceBook
 * @notice Canonical on-chain record and one-time consumption of verified source events (GPU-031).
 * @dev  - The book itself calls the bound `IRevenueVerifier` for the provider and consumes only the events that
 *         verifier returned in the same transaction; a caller can never hand in a `VerifiedSourceEvent` it built.
 *       - One consumption per `SourceEventId` per environment; a second attempt reverts `AlreadyConsumed`.
 *       - Consumption is atomic with the consumer's business effect: the allowed consumer calls `consume` from its
 *         own transaction, so a business revert rolls the consumption back. A public verifier call never pre-empts a
 *         consumer because verification is stateless.
 *       - Economic dedup (same economic event via other proofs/verifiers/APIs) keys on `EconomicEventId`, which is
 *         derived off-chain from provider/account/eventType/provider ref — never from proof bytes, verifier address
 *         or SDK/ABI version. Verifier replacement therefore replays into `AlreadyConsumed`.
 *       - Auxiliary signatures (IAuthorizationVerifier) have no entry point here: nothing but a native verification
 *         result creates a record (R2-D03/D04). Events from Rackline-controlled anchor emitters stay
 *         `OFFCHAIN_ASSERTION` / `ASSERTED` even when natively proven (R2-D05).
 */
interface IEvidenceBook {
    struct EvidenceRecord {
        GpuTypes.SourceEventId id;
        GpuTypes.EconomicEventId economicEventId;
        GpuTypes.ProviderId providerId;
        GpuTypes.AccountKey accountKey;
        GpuTypes.EvidenceMeaning meaning;
        GpuTypes.VerificationMethod method;
        GpuTypes.Trust trust;
        address consumer;
        bytes32 manifestHash;
        uint64 provenAt; // destination block time of consumption
        uint64 validUntil;
        GpuTypes.SourceEventLocator locator;
        address emitter;
        bytes32 topic0;
        bytes32 dataHash; // keccak256(abi.encode(topics, data)) of the verified log
    }

    /// @notice What the consumer wants to consume out of one verified transaction. Instructions address returned
    ///         logs by receipt ordinal; a subset may be consumed now and the rest later (each log at most once).
    struct ConsumeInstruction {
        uint32 logOrdinal; // must equal the ordinal of a log the verifier returned
        GpuTypes.EconomicEventId economicEventId;
        GpuTypes.AccountKey accountKey;
        uint64 validUntil; // policy validity of the proof; must be in the future and within maxValidity
    }

    event SourceEventConsumed(
        GpuTypes.SourceEventId indexed id,
        GpuTypes.EconomicEventId indexed economicEventId,
        address indexed consumer,
        GpuTypes.EvidenceMeaning meaning,
        bytes32 manifestHash
    );
    event EconomicEventFirstSeen(
        GpuTypes.EconomicEventId indexed economicEventId, GpuTypes.SourceEventId indexed firstSourceEventId
    );
    event VerifierBound(GpuTypes.ProviderId indexed providerId, address indexed verifier, bytes32 manifestHash);
    event ConsumerSet(address indexed consumer, bool allowed);
    event SelfAssertedEmitterSet(GpuTypes.ProviderId indexed providerId, address indexed emitter, bool selfAsserted);

    error AlreadyConsumed(GpuTypes.SourceEventId id);
    error NotFromVerifier(address caller);
    error ConsumerNotAllowed(address consumer);
    error StaleVerification(GpuTypes.SourceEventId id);
    error VerifierNotBound(GpuTypes.ProviderId providerId);
    error VerifierEnvMismatch(bytes32 expectedEnvIdHash, bytes32 actualEnvIdHash);
    error EconomicEventAlreadyRecorded(GpuTypes.EconomicEventId economicEventId, GpuTypes.SourceEventId first);
    error InstructionMismatch(uint256 expectedCount, uint256 actualCount);
    error UnknownLogOrdinal(uint32 logOrdinal);
    error InvalidInstruction(string reason);

    function envIdHash() external view returns (bytes32);
    function maxValidity() external view returns (uint64);
    function verifierOf(GpuTypes.ProviderId providerId) external view returns (IRevenueVerifier);
    function isConsumer(address consumer) external view returns (bool);
    function isConsumed(GpuTypes.SourceEventId id) external view returns (bool);
    function record(GpuTypes.SourceEventId id) external view returns (EvidenceRecord memory);
    function economicEventSeen(GpuTypes.EconomicEventId economicEventId) external view returns (bool);
    function firstSourceEventOf(GpuTypes.EconomicEventId economicEventId) external view returns (GpuTypes.SourceEventId);

    /**
     * @notice Verify `envelope` through the provider's bound verifier and consume the instructed returned logs for
     *         `msg.sender` (an allowed consumer), each at most once per environment.
     * @return records the consumed records in instruction order
     */
    function consume(
        GpuTypes.ProviderId providerId,
        GpuTypes.NativeProofEnvelope calldata envelope,
        address expectedEmitter,
        bytes32[] calldata topic0s,
        ConsumeInstruction[] calldata instructions
    ) external returns (EvidenceRecord[] memory records);
}
