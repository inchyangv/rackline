// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import { GpuTypes } from "../types/GpuTypes.sol";

/**
 * @title IRevenueVerifier
 * @notice Native verification adapter over the official BlockProver precompile (GPU-078). It calls
 *         `INativeQueryVerifier.verifyAndEmit` on exactly the supplied bytes, decodes the receipt with the official
 *         `EvmV1Decoder`, and returns the logs that match the registered emitters/topics as `VerifiedSourceEvent`s.
 * @dev  - Fail-closed: precompile `false`/revert/empty, receipt status != 1, manifest mismatch, unregistered emitter,
 *         unsupported encoding, oversized input => revert. There is no signature or admin fallback (R2-D03).
 *       - Never consumes: consumption/dedup is the evidence book's job (GPU-031). Verification is not an economic act.
 *       - Never trusts worker-supplied amount/recipient/timestamp/txIndex; `txIndex` comes from `calculateTxIndex`.
 *       - LOCAL_MOCK deployments bind to a test double explicitly; a native profile cannot point at a mock address.
 */
interface IRevenueVerifier {
    event SourceEventVerified(
        GpuTypes.SourceEventId indexed id,
        uint64 indexed chainKey,
        uint64 indexed height,
        uint64 txIndex,
        uint32 logOrdinal,
        address emitter,
        bytes32 topic0
    );

    error NativeVerificationFailed(bytes reason);
    error ReceiptNotSuccessful(uint8 status);
    error ManifestMismatch(bytes32 expected, bytes32 actual);
    error ChainKeyMismatch(uint64 expected, uint64 actual);
    error EncodingUnsupported(uint8 encoding);
    error TransactionTypeUnsupported(uint8 txType);
    error EmitterNotRegistered(address emitter, bytes32 topic0);
    error NoMatchingLogs();
    error InputTooLarge(uint256 size, uint256 max);
    error MockNotAllowedInProfile(GpuTypes.ExecutionProfile profile);
    /// @notice The verified bytes could not be decoded by the official decoder (reason = decoder revert data).
    error MalformedEncoding(bytes reason);
    /// @notice The bound provider exists but admission is switched off (guardian/underwriter decision).
    error ProviderNotAdmitted(GpuTypes.ProviderId providerId);

    function manifestHash() external view returns (bytes32);
    /// @notice The single provider this adapter is bound to (registry binding checked at construction).
    function providerId() external view returns (GpuTypes.ProviderId);
    function sourceChain() external view returns (GpuTypes.SourceChainRef memory);
    function executionProfile() external view returns (GpuTypes.ExecutionProfile);
    function verificationMethod() external view returns (GpuTypes.VerificationMethod);
    function maxEncodedTransactionBytes() external view returns (uint256);

    /**
     * @notice Verify `envelope` natively and extract logs from `expectedEmitter` whose topic0 is in `topic0s`.
     * @return events one entry per matching receipt log, in receipt order (logOrdinal ascending)
     */
    function verifyAndExtract(
        GpuTypes.NativeProofEnvelope calldata envelope,
        address expectedEmitter,
        bytes32[] calldata topic0s
    ) external returns (GpuTypes.VerifiedSourceEvent[] memory events);
}
