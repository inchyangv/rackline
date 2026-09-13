// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import { GpuTypes } from "./types/GpuTypes.sol";
import { IEvidenceBook } from "./interfaces/IEvidenceBook.sol";
import { IRevenueVerifier } from "./interfaces/IRevenueVerifier.sol";
import { IProviderRegistry } from "./interfaces/IProviderRegistry.sol";
import { IProtocolRoles } from "./interfaces/IProtocolRoles.sol";

/**
 * @title EvidenceBook
 * @notice Canonical record and one-time consumption of natively verified source events (GPU-031).
 * @dev Flow (R2 §0.9 required path): allowed consumer → `consume` → bound `IRevenueVerifier.verifyAndExtract`
 *      (official precompile, GPU-078) → one record per returned log, keyed by the proof-bound `SourceEventId`.
 *      - Nothing but the verifier's return value in this transaction creates a record. There is no function that
 *        accepts a caller-built `VerifiedSourceEvent`, a signature, or an admin assertion (R2-D03/D04).
 *      - `meaning` comes from the provider registry's emitter registration, never from the consumer.
 *      - `method` is the verifier's `verificationMethod()` (LOCAL_MOCK or ATTESTCOIN_NATIVE); production readers
 *        reject LOCAL_MOCK records. Emitters flagged self-asserted (Rackline-controlled anchors) are recorded as
 *        OFFCHAIN_ASSERTION / ASSERTED even though the log itself is natively proven (R2-D05).
 *      - `economicEventId` is the cross-observer dedup key; a second source event claiming an already recorded
 *        economic event reverts (reconciliation is an off-chain act, not a second recognition).
 *      - A record proves that a log occurred; it is not revenue eligibility, unpaid balance, E2, or cash.
 *      - Admin (ProtocolRoles ADMIN) binds verifiers per provider (same environment only) and allowlists consumers;
 *        pausing/wiring policy is GPU-043.
 */
contract EvidenceBook is IEvidenceBook {
    IProtocolRoles public immutable ROLES;
    IProviderRegistry public immutable PROVIDERS;
    bytes32 private immutable _ENV_ID_HASH;
    uint64 private immutable _MAX_VALIDITY;

    mapping(GpuTypes.ProviderId => IRevenueVerifier) private _verifiers;
    mapping(address => bool) private _consumers;
    mapping(GpuTypes.ProviderId => mapping(address => bool)) private _selfAsserted;
    mapping(GpuTypes.SourceEventId => EvidenceRecord) private _records;
    mapping(GpuTypes.SourceEventId => bool) private _consumed;
    mapping(GpuTypes.EconomicEventId => GpuTypes.SourceEventId) private _firstSource;
    mapping(GpuTypes.EconomicEventId => bool) private _economicSeen;

    error NotAdmin(address caller);
    error ZeroAddress();
    error WiringFinalized();
    error EvidencePaused();
    error InvalidVerifierBinding();
    bool public wiringFinalized;
    bool public evidencePaused;
    event WiringSealed();
    event EvidenceIntakePaused(bool paused);

    constructor(IProtocolRoles roles, IProviderRegistry providers, bytes32 envIdHash_, uint64 maxValidity_) {
        if (address(roles) == address(0) || address(providers) == address(0)) revert ZeroAddress();
        if (envIdHash_ == bytes32(0) || maxValidity_ == 0) revert InvalidInstruction("env/maxValidity");
        ROLES = roles;
        PROVIDERS = providers;
        _ENV_ID_HASH = envIdHash_;
        _MAX_VALIDITY = maxValidity_;
    }

    modifier onlyAdmin() {
        if (!ROLES.hasRole(keccak256("ADMIN"), msg.sender)) revert NotAdmin(msg.sender);
        _;
    }

    // ------------------------------------------------------------------ admin wiring

    /// @notice Bind (or replace) the verifier for a provider. The verifier must serve this book's environment and
    ///         the same provider; ids are environment-scoped, so a replacement replays into `AlreadyConsumed`.
    function bindVerifier(GpuTypes.ProviderId providerId, IRevenueVerifier verifier) external onlyAdmin {
        if (wiringFinalized) revert WiringFinalized();
        if (address(verifier) == address(0)) revert ZeroAddress();
        GpuTypes.SourceChainRef memory src = verifier.sourceChain();
        if (src.envIdHash != _ENV_ID_HASH) revert VerifierEnvMismatch(_ENV_ID_HASH, src.envIdHash);
        IProviderRegistry.ProviderConfig memory config = PROVIDERS.provider(providerId);
        if (
            GpuTypes.ProviderId.unwrap(verifier.providerId()) != GpuTypes.ProviderId.unwrap(providerId)
                || verifier.executionProfile() != config.executionProfile
                || src.manifestHash != config.sourceChain.manifestHash || src.chainKey != config.sourceChain.chainKey
                || src.chainId != config.sourceChain.chainId || src.encoding != config.sourceChain.encoding
        ) revert InvalidVerifierBinding();
        if (
            config.executionProfile != GpuTypes.ExecutionProfile.LOCAL_MOCK
                && verifier.verificationMethod() != GpuTypes.VerificationMethod.ATTESTCOIN_NATIVE
        ) {
            revert InvalidVerifierBinding();
        }
        _verifiers[providerId] = verifier;
        emit VerifierBound(providerId, address(verifier), src.manifestHash);
    }

    function setConsumer(address consumer, bool allowed) external onlyAdmin {
        if (wiringFinalized) revert WiringFinalized();
        if (consumer == address(0)) revert ZeroAddress();
        _consumers[consumer] = allowed;
        emit ConsumerSet(consumer, allowed);
    }

    /// @notice Mark an emitter as Rackline-controlled (statement hash anchors etc.). Its events remain assertions.
    function setSelfAssertedEmitter(GpuTypes.ProviderId providerId, address emitter, bool selfAsserted)
        external
        onlyAdmin
    {
        if (wiringFinalized) revert WiringFinalized();
        _selfAsserted[providerId][emitter] = selfAsserted;
        emit SelfAssertedEmitterSet(providerId, emitter, selfAsserted);
    }

    function finalizeWiring() external onlyAdmin {
        if (wiringFinalized) revert WiringFinalized();
        wiringFinalized = true;
        emit WiringSealed();
    }

    function pauseEvidenceIntake(bool paused) external {
        if (!ROLES.hasRole(ROLES.GUARDIAN(), msg.sender)) revert NotAdmin(msg.sender);
        evidencePaused = paused;
        emit EvidenceIntakePaused(paused);
    }

    // ------------------------------------------------------------------ views

    function envIdHash() external view override returns (bytes32) {
        return _ENV_ID_HASH;
    }

    function maxValidity() external view override returns (uint64) {
        return _MAX_VALIDITY;
    }

    function verifierOf(GpuTypes.ProviderId providerId) external view override returns (IRevenueVerifier) {
        return _verifiers[providerId];
    }

    function isConsumer(address consumer) external view override returns (bool) {
        return _consumers[consumer];
    }

    function isConsumed(GpuTypes.SourceEventId id) external view override returns (bool) {
        return _consumed[id];
    }

    function record(GpuTypes.SourceEventId id) external view override returns (EvidenceRecord memory) {
        return _records[id];
    }

    function economicEventSeen(GpuTypes.EconomicEventId economicEventId) external view override returns (bool) {
        return _economicSeen[economicEventId];
    }

    function firstSourceEventOf(GpuTypes.EconomicEventId economicEventId)
        external
        view
        override
        returns (GpuTypes.SourceEventId)
    {
        return _firstSource[economicEventId];
    }

    function isSelfAssertedEmitter(GpuTypes.ProviderId providerId, address emitter) external view returns (bool) {
        return _selfAsserted[providerId][emitter];
    }

    // ------------------------------------------------------------------ consumption

    function consume(
        GpuTypes.ProviderId providerId,
        GpuTypes.NativeProofEnvelope calldata envelope,
        address expectedEmitter,
        bytes32[] calldata topic0s,
        ConsumeInstruction[] calldata instructions
    ) external override returns (EvidenceRecord[] memory records) {
        if (evidencePaused) revert EvidencePaused();
        if (!_consumers[msg.sender]) revert ConsumerNotAllowed(msg.sender);
        IRevenueVerifier verifier = _verifiers[providerId];
        if (address(verifier) == address(0)) revert VerifierNotBound(providerId);
        if (GpuTypes.ProviderId.unwrap(verifier.providerId()) != GpuTypes.ProviderId.unwrap(providerId)) {
            revert VerifierNotBound(providerId);
        }

        // Native verification happens here, in this transaction; the returned events are the only trusted input.
        GpuTypes.VerifiedSourceEvent[] memory events = verifier.verifyAndExtract(envelope, expectedEmitter, topic0s);
        if (instructions.length == 0 || instructions.length > events.length) {
            revert InstructionMismatch(events.length, instructions.length);
        }

        GpuTypes.VerificationMethod method = verifier.verificationMethod();
        bool selfAsserted = _selfAsserted[providerId][expectedEmitter];
        records = new EvidenceRecord[](instructions.length);
        for (uint256 i = 0; i < instructions.length; i++) {
            ConsumeInstruction calldata ins = instructions[i];
            for (uint256 j = 0; j < i; j++) {
                if (instructions[j].logOrdinal == ins.logOrdinal) revert InvalidInstruction("duplicate logOrdinal");
            }
            GpuTypes.VerifiedSourceEvent memory ev = _eventAt(events, ins.logOrdinal);
            if (ev.verifier != address(verifier)) revert NotFromVerifier(ev.verifier);
            records[i] = _consumeOne(providerId, ev, ins, method, selfAsserted);
        }
    }

    /// @dev Instructions address logs by receipt ordinal (proof-bound position), never by array position; a subset
    ///      of the returned logs may be consumed now and the rest later with a fresh submission.
    function _eventAt(GpuTypes.VerifiedSourceEvent[] memory events, uint32 ordinal)
        internal
        pure
        returns (GpuTypes.VerifiedSourceEvent memory)
    {
        for (uint256 j = 0; j < events.length; j++) {
            if (events[j].locator.logOrdinal == ordinal) return events[j];
        }
        revert UnknownLogOrdinal(ordinal);
    }

    function _consumeOne(
        GpuTypes.ProviderId providerId,
        GpuTypes.VerifiedSourceEvent memory ev,
        ConsumeInstruction calldata ins,
        GpuTypes.VerificationMethod method,
        bool selfAsserted
    ) internal returns (EvidenceRecord memory rec) {
        if (_consumed[ev.id]) revert AlreadyConsumed(ev.id);
        if (ins.validUntil <= block.timestamp) revert StaleVerification(ev.id);
        if (ins.validUntil > block.timestamp + _MAX_VALIDITY) revert InvalidInstruction("validUntil beyond policy");
        if (GpuTypes.EconomicEventId.unwrap(ins.economicEventId) == bytes32(0)) {
            revert InvalidInstruction("economicEventId");
        }
        if (GpuTypes.AccountKey.unwrap(ins.accountKey) == bytes32(0)) revert InvalidInstruction("accountKey");
        // Internal source events carry accountKey as topics[1]; when present it must match the instruction.
        if (ev.topics.length > 1 && ev.topics[1] != GpuTypes.AccountKey.unwrap(ins.accountKey)) {
            revert InvalidInstruction("accountKey != topics[1]");
        }
        if (_economicSeen[ins.economicEventId]) {
            revert EconomicEventAlreadyRecorded(ins.economicEventId, _firstSource[ins.economicEventId]);
        }

        // meaning is fixed by the registry for (provider, emitter, topic0); the verifier already required registration
        GpuTypes.EvidenceMeaning meaning = PROVIDERS.emitterMeaning(providerId, ev.emitter, ev.topic0);

        rec = EvidenceRecord({
            id: ev.id,
            economicEventId: ins.economicEventId,
            providerId: providerId,
            accountKey: ins.accountKey,
            meaning: meaning,
            method: selfAsserted ? GpuTypes.VerificationMethod.OFFCHAIN_ASSERTION : method,
            trust: selfAsserted ? GpuTypes.Trust.ASSERTED : GpuTypes.Trust.PROVEN,
            consumer: msg.sender,
            manifestHash: ev.manifestHash,
            provenAt: uint64(block.timestamp),
            validUntil: ins.validUntil,
            locator: ev.locator,
            emitter: ev.emitter,
            topic0: ev.topic0,
            dataHash: keccak256(abi.encode(ev.topics, ev.data))
        });
        _records[ev.id] = rec;
        _consumed[ev.id] = true;
        _economicSeen[ins.economicEventId] = true;
        _firstSource[ins.economicEventId] = ev.id;
        emit EconomicEventFirstSeen(ins.economicEventId, ev.id);
        emit SourceEventConsumed(ev.id, ins.economicEventId, msg.sender, meaning, ev.manifestHash);
    }
}
