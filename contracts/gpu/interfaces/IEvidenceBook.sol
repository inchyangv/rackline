// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import { GpuTypes } from "../types/GpuTypes.sol";

/**
 * @title IEvidenceBook
 * @notice Canonical on-chain record and one-time consumption of verified source events (GPU-031).
 * @dev  - Accepts events only from the bound `IRevenueVerifier` in the same transaction as verification.
 *       - One consumption per `SourceEventId` per environment; a second attempt reverts `AlreadyConsumed`.
 *       - Consumption is atomic with the consumer's business effect; a public `verify` never pre-empts a consumer.
 *       - Economic dedup (same economic event via other proofs/verifiers/APIs) keys on `EconomicEventId`, not on ids
 *         derived from proof bytes or verifier address.
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

    error AlreadyConsumed(GpuTypes.SourceEventId id);
    error NotFromVerifier(address caller);
    error ConsumerNotAllowed(address consumer);
    error StaleVerification(GpuTypes.SourceEventId id);

    function isConsumed(GpuTypes.SourceEventId id) external view returns (bool);
    function record(GpuTypes.SourceEventId id) external view returns (EvidenceRecord memory);
    function economicEventSeen(GpuTypes.EconomicEventId economicEventId) external view returns (bool);
    /**
     * @notice Consume a verified event for `consumer` business logic. Callable only by the verifier/consumer pair.
     */
    function consume(
        GpuTypes.VerifiedSourceEvent calldata ev,
        GpuTypes.EconomicEventId economicEventId,
        GpuTypes.ProviderId providerId,
        GpuTypes.AccountKey accountKey,
        GpuTypes.EvidenceMeaning meaning,
        uint64 validUntil
    ) external;
}
