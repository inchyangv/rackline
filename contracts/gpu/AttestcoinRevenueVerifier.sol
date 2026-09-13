// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import { INativeQueryVerifier } from "@gluwa/asc-contracts/contracts/write-ability/common/INativeQueryVerifier.sol";
import { EvmV1Decoder } from "@gluwa/asc-contracts/contracts/common/EvmV1Decoder.sol";
import { GpuTypes } from "./types/GpuTypes.sol";
import { IRevenueVerifier } from "./interfaces/IRevenueVerifier.sol";
import { IProviderRegistry } from "./interfaces/IProviderRegistry.sol";

/**
 * @title AttestcoinRevenueVerifier
 * @notice Native verification adapter (GPU-078). Calls the official BlockProver precompile
 *         (`INativeQueryVerifier.verifyAndEmit`, state-changing) on exactly the supplied bytes, then decodes the
 *         receipt with the official `EvmV1Decoder` and returns the logs emitted by `expectedEmitter` whose topic0 is
 *         in `topic0s`.
 * @dev Fail-closed, no fallback (R2-D03). Every failure reverts; nothing is signed, overridden or downgraded:
 *      - chainKey not the manifest's                                      -> ChainKeyMismatch
 *      - encodedTransaction / siblings / continuity roots over the caps   -> InputTooLarge
 *      - emitter/topic not registered for the bound provider              -> EmitterNotRegistered
 *      - provider admission off / manifest of the provider differs        -> ProviderNotAdmitted / ManifestMismatch
 *      - precompile returns false, reverts, returns empty or non-bool     -> NativeVerificationFailed(reason)
 *      - official decoder cannot decode the verified bytes                -> MalformedEncoding(reason)
 *      - unsupported tx type, receipt status != 1, too many logs          -> TransactionTypeUnsupported /
 *                                                                            ReceiptNotSuccessful / InputTooLarge
 *      - no log from `expectedEmitter` with an allowed topic0             -> NoMatchingLogs
 *      Proven values only: height (continuity-bound input the precompile verified), txIndex (precompile
 *      `calculateTxIndex` over the verified merkle proof), receipt fields and log bytes decoded from the verified
 *      `encodedTransaction`. Worker hints (txHash, timestamps, amounts, recipients) are never inputs here.
 *      This contract is stateless and never consumes: it emits `SourceEventVerified` and returns events; one-time
 *      consumption, economic dedup and business validation belong to the EvidenceBook (GPU-031). Anyone may call
 *      `verifyAndExtract`; a front-run changes nothing because verification is not an economic act. Indexers must
 *      key on EvidenceBook events, not on `SourceEventVerified`. Success means "this log occurred on the source
 *      chain", not revenue eligibility, unpaid balance, cash, or a legal right (R2-D05).
 *      Profiles: a NATIVE_TESTNET/PRODUCTION deployment must bind `PRECOMPILE` to the official address 0x…0FD2;
 *      a LOCAL_MOCK deployment must bind an explicit test double and reports verificationMethod = LOCAL_MOCK.
 *      The provider's registered source chain (env, chainKey, chainId, encoding, manifest) and execution profile
 *      must equal this verifier's binding at construction; the registry cannot change a provider's chain later.
 */
contract AttestcoinRevenueVerifier is IRevenueVerifier {
    address public constant OFFICIAL_PRECOMPILE = 0x0000000000000000000000000000000000000FD2;
    uint8 public constant SUPPORTED_ENCODING = 1; // SDK EncodingVersion.V1 / asc-contracts 0.2.1 EvmV1Decoder

    INativeQueryVerifier public immutable PRECOMPILE;
    IProviderRegistry public immutable PROVIDERS;
    GpuTypes.ProviderId public immutable PROVIDER_ID;
    bytes32 private immutable _MANIFEST_HASH;
    bytes32 private immutable _ENV_ID_HASH;
    uint64 private immutable _CHAIN_KEY;
    uint64 private immutable _SOURCE_CHAIN_ID;
    GpuTypes.ExecutionProfile private immutable _PROFILE;
    uint256 private immutable _MAX_TX_BYTES;
    uint256 public immutable MAX_LOGS;
    uint256 public immutable MAX_SIBLINGS;
    uint256 public immutable MAX_CONTINUITY_ROOTS;

    error InvalidBinding(string reason);
    error NotSelf();

    struct Limits {
        uint256 maxTxBytes;
        uint256 maxLogs;
        uint256 maxSiblings;
        uint256 maxContinuityRoots;
    }

    constructor(
        address precompile,
        IProviderRegistry providers,
        GpuTypes.ProviderId providerId,
        GpuTypes.SourceChainRef memory source,
        GpuTypes.ExecutionProfile profile,
        Limits memory limits
    ) {
        if (source.encoding != SUPPORTED_ENCODING) {
            revert EncodingUnsupported(source.encoding);
        }
        if (profile != GpuTypes.ExecutionProfile.LOCAL_MOCK && precompile != OFFICIAL_PRECOMPILE) {
            revert MockNotAllowedInProfile(profile);
        }
        if (profile == GpuTypes.ExecutionProfile.LOCAL_MOCK && precompile == OFFICIAL_PRECOMPILE) {
            revert InvalidBinding("LOCAL_MOCK must bind an explicit test double, not the official address");
        }
        if (source.manifestHash == bytes32(0) || source.chainKey == 0 || source.chainId == 0) {
            revert InvalidBinding("manifest/chainKey/chainId");
        }
        if (limits.maxTxBytes == 0 || limits.maxLogs == 0 || limits.maxSiblings == 0 || limits.maxContinuityRoots == 0)
        {
            revert InvalidBinding("limits");
        }
        // The provider must already be registered with exactly this binding (registry is configuration, GPU-030).
        IProviderRegistry.ProviderConfig memory cfg = providers.provider(providerId);
        if (cfg.executionProfile != profile) revert InvalidBinding("provider profile");
        if (
            cfg.sourceChain.envIdHash != source.envIdHash || cfg.sourceChain.chainKey != source.chainKey
                || cfg.sourceChain.chainId != source.chainId || cfg.sourceChain.encoding != source.encoding
                || cfg.sourceChain.manifestHash != source.manifestHash
        ) revert InvalidBinding("provider source chain");

        PRECOMPILE = INativeQueryVerifier(precompile);
        PROVIDERS = providers;
        PROVIDER_ID = providerId;
        _MANIFEST_HASH = source.manifestHash;
        _ENV_ID_HASH = source.envIdHash;
        _CHAIN_KEY = source.chainKey;
        _SOURCE_CHAIN_ID = source.chainId;
        _PROFILE = profile;
        _MAX_TX_BYTES = limits.maxTxBytes;
        MAX_LOGS = limits.maxLogs;
        MAX_SIBLINGS = limits.maxSiblings;
        MAX_CONTINUITY_ROOTS = limits.maxContinuityRoots;
    }

    // ------------------------------------------------------------------ views

    function manifestHash() external view override returns (bytes32) {
        return _MANIFEST_HASH;
    }

    function providerId() external view override returns (GpuTypes.ProviderId) {
        return PROVIDER_ID;
    }

    function sourceChain() external view override returns (GpuTypes.SourceChainRef memory) {
        return GpuTypes.SourceChainRef({
            envIdHash: _ENV_ID_HASH,
            chainKey: _CHAIN_KEY,
            chainId: _SOURCE_CHAIN_ID,
            encoding: SUPPORTED_ENCODING,
            manifestHash: _MANIFEST_HASH
        });
    }

    function executionProfile() external view override returns (GpuTypes.ExecutionProfile) {
        return _PROFILE;
    }

    function verificationMethod() external view override returns (GpuTypes.VerificationMethod) {
        return _PROFILE == GpuTypes.ExecutionProfile.LOCAL_MOCK
            ? GpuTypes.VerificationMethod.LOCAL_MOCK
            : GpuTypes.VerificationMethod.ATTESTCOIN_NATIVE;
    }

    function maxEncodedTransactionBytes() external view override returns (uint256) {
        return _MAX_TX_BYTES;
    }

    /// @notice Canonical consumption key (GPU-076 §3):
    ///         keccak256(abi.encode(keccak256(envId), chainKey, height, txIndex, logOrdinal)).
    function sourceEventId(uint64 height, uint64 txIndex, uint32 logOrdinal)
        public
        view
        returns (GpuTypes.SourceEventId)
    {
        return GpuTypes.SourceEventId.wrap(keccak256(abi.encode(_ENV_ID_HASH, _CHAIN_KEY, height, txIndex, logOrdinal)));
    }

    // ------------------------------------------------------------------ verification

    function verifyAndExtract(
        GpuTypes.NativeProofEnvelope calldata envelope,
        address expectedEmitter,
        bytes32[] calldata topic0s
    ) external override returns (GpuTypes.VerifiedSourceEvent[] memory events) {
        _checkBinding(envelope, expectedEmitter, topic0s);
        uint64 txIndex = _nativeVerify(envelope);
        // Decode with the official decoder from the verified bytes only (never from an RPC receipt).
        EvmV1Decoder.ReceiptFields memory receipt = _decodeVerified(envelope.encodedTransaction);
        events = _extract(receipt, envelope.height, txIndex, expectedEmitter, topic0s);
    }

    /// @dev External only so that decoder reverts can be caught and reported as MalformedEncoding.
    function decodeReceiptForSelf(bytes calldata encodedTransaction)
        external
        view
        returns (EvmV1Decoder.ReceiptFields memory receipt)
    {
        if (msg.sender != address(this)) revert NotSelf();
        bytes memory encoded = encodedTransaction;
        uint8 txType = EvmV1Decoder.getTransactionType(encoded);
        if (!EvmV1Decoder.isValidTransactionType(txType)) revert TransactionTypeUnsupported(txType);
        receipt = EvmV1Decoder.decodeReceiptFields(encoded);
    }

    /// @dev Manifest / registry binding checks run before any gas is spent on the precompile.
    function _checkBinding(
        GpuTypes.NativeProofEnvelope calldata envelope,
        address expectedEmitter,
        bytes32[] calldata topic0s
    ) internal view {
        if (envelope.chainKey != _CHAIN_KEY) {
            revert ChainKeyMismatch(_CHAIN_KEY, envelope.chainKey);
        }
        if (envelope.encodedTransaction.length == 0) revert MalformedEncoding("");
        if (envelope.encodedTransaction.length > _MAX_TX_BYTES) {
            revert InputTooLarge(envelope.encodedTransaction.length, _MAX_TX_BYTES);
        }
        if (envelope.siblings.length > MAX_SIBLINGS) revert InputTooLarge(envelope.siblings.length, MAX_SIBLINGS);
        if (envelope.continuityRoots.length > MAX_CONTINUITY_ROOTS) {
            revert InputTooLarge(envelope.continuityRoots.length, MAX_CONTINUITY_ROOTS);
        }
        if (topic0s.length == 0) revert NoMatchingLogs();
        for (uint256 i = 0; i < topic0s.length; i++) {
            if (!PROVIDERS.isEmitterRegistered(PROVIDER_ID, expectedEmitter, topic0s[i])) {
                revert EmitterNotRegistered(expectedEmitter, topic0s[i]);
            }
        }
        if (!PROVIDERS.isAdmitted(PROVIDER_ID, _MANIFEST_HASH)) {
            bytes32 providerManifest = PROVIDERS.provider(PROVIDER_ID).sourceChain.manifestHash;
            if (providerManifest != _MANIFEST_HASH) revert ManifestMismatch(_MANIFEST_HASH, providerManifest);
            revert ProviderNotAdmitted(PROVIDER_ID);
        }
    }

    /// @dev Native verification on exactly the supplied bytes via the official state-changing `verifyAndEmit`,
    ///      then the proven txIndex. Low-level calls are used on purpose: the precompile has no bytecode and any
    ///      revert / `false` / empty / non-boolean return must end in NativeVerificationFailed instead of an
    ///      undecodable revert.
    function _nativeVerify(GpuTypes.NativeProofEnvelope calldata envelope) internal returns (uint64 txIndex) {
        INativeQueryVerifier.MerkleProof memory merkleProof =
            INativeQueryVerifier.MerkleProof({ root: envelope.merkleRoot, siblings: envelope.siblings });
        INativeQueryVerifier.ContinuityProof memory continuityProof = INativeQueryVerifier.ContinuityProof({
            lowerEndpointDigest: envelope.lowerEndpointDigest, roots: envelope.continuityRoots
        });
        (bool ok, bytes memory ret) = address(PRECOMPILE)
            .call(
                abi.encodeWithSelector(
                    _VERIFY_AND_EMIT_SINGLE,
                    envelope.chainKey,
                    envelope.height,
                    envelope.encodedTransaction,
                    merkleProof,
                    continuityProof
                )
            );
        if (!ok) revert NativeVerificationFailed(ret);
        if (!_isTrue(ret)) revert NativeVerificationFailed(ret);

        (ok, ret) = address(PRECOMPILE)
            .staticcall(abi.encodeWithSelector(INativeQueryVerifier.calculateTxIndex.selector, merkleProof));
        if (!ok || ret.length != 32) revert NativeVerificationFailed(ret);
        uint256 idx = abi.decode(ret, (uint256));
        if (idx > type(uint64).max) revert NativeVerificationFailed(ret);
        txIndex = uint64(idx);
    }

    /// @dev Selector of the single-transaction overload
    ///      `verifyAndEmit(uint64,uint64,bytes,(bytes32,(bytes32,bool)[]),(bytes32,bytes32[]))`.
    bytes4 private constant _VERIFY_AND_EMIT_SINGLE =
        bytes4(keccak256("verifyAndEmit(uint64,uint64,bytes,(bytes32,(bytes32,bool)[]),(bytes32,bytes32[]))"));

    /// @dev Exactly one ABI word equal to 1. Empty, short, long or non-boolean return data is a failure.
    function _isTrue(bytes memory ret) internal pure returns (bool) {
        return ret.length == 32 && abi.decode(ret, (uint256)) == 1;
    }

    function _decodeVerified(bytes calldata encodedTransaction)
        internal
        view
        returns (EvmV1Decoder.ReceiptFields memory receipt)
    {
        try this.decodeReceiptForSelf(encodedTransaction) returns (EvmV1Decoder.ReceiptFields memory decoded) {
            receipt = decoded;
        } catch (bytes memory reason) {
            if (bytes4(reason) == TransactionTypeUnsupported.selector) {
                assembly ("memory-safe") {
                    revert(add(reason, 32), mload(reason))
                }
            }
            revert MalformedEncoding(reason);
        }
        if (receipt.receiptStatus != 1) revert ReceiptNotSuccessful(receipt.receiptStatus);
        if (receipt.receiptLogs.length > MAX_LOGS) revert InputTooLarge(receipt.receiptLogs.length, MAX_LOGS);
    }

    /// @dev Select logs by (emitter, topic0) in receipt order; logOrdinal = index inside the receipt's log array.
    function _extract(
        EvmV1Decoder.ReceiptFields memory receipt,
        uint64 height,
        uint64 txIndex,
        address expectedEmitter,
        bytes32[] calldata topic0s
    ) internal returns (GpuTypes.VerifiedSourceEvent[] memory events) {
        uint256 count;
        for (uint256 i = 0; i < receipt.receiptLogs.length; i++) {
            if (_matches(receipt.receiptLogs[i], expectedEmitter, topic0s)) count++;
        }
        if (count == 0) revert NoMatchingLogs();
        events = new GpuTypes.VerifiedSourceEvent[](count);
        uint256 k;
        for (uint256 i = 0; i < receipt.receiptLogs.length; i++) {
            EvmV1Decoder.LogEntry memory log = receipt.receiptLogs[i];
            if (!_matches(log, expectedEmitter, topic0s)) continue;
            events[k] = _event(log, height, txIndex, uint32(i));
            _emitVerified(events[k]);
            k++;
        }
    }

    function _event(EvmV1Decoder.LogEntry memory log, uint64 height, uint64 txIndex, uint32 ordinal)
        internal
        view
        returns (GpuTypes.VerifiedSourceEvent memory ev)
    {
        ev.id = sourceEventId(height, txIndex, ordinal);
        ev.locator = GpuTypes.SourceEventLocator({
            chainKey: _CHAIN_KEY, height: height, txIndex: txIndex, logOrdinal: ordinal
        });
        ev.emitter = log.address_;
        ev.topic0 = log.topics[0];
        ev.topics = log.topics;
        ev.data = log.data;
        ev.manifestHash = _MANIFEST_HASH;
        ev.verifier = address(this);
    }

    function _emitVerified(GpuTypes.VerifiedSourceEvent memory ev) internal {
        emit SourceEventVerified(
            ev.id,
            ev.locator.chainKey,
            ev.locator.height,
            ev.locator.txIndex,
            ev.locator.logOrdinal,
            ev.emitter,
            ev.topic0
        );
    }

    function _matches(EvmV1Decoder.LogEntry memory log, address emitter, bytes32[] calldata topic0s)
        internal
        pure
        returns (bool)
    {
        if (log.address_ != emitter || log.topics.length == 0) return false;
        for (uint256 j = 0; j < topic0s.length; j++) {
            if (log.topics[0] == topic0s[j]) return true;
        }
        return false;
    }
}
