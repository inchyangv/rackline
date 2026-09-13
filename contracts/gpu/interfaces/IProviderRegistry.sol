// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import { GpuTypes } from "../types/GpuTypes.sol";

/**
 * @title IProviderRegistry
 * @notice Registry of settlement providers, their source chain binding, registered emitters, admitted tokens and
 *         issuer roles (PIVOT §7 ProviderRegistry). Implemented by GPU-030; consulted by the verifier (GPU-078),
 *         evidence book (GPU-031) and risk policy.
 * @dev Registration is configuration, not evidence: it never proves GPU ownership, revenue, or E2 control.
 *      Providers whose source chain is not in the manifest's supported table are `UNSUPPORTED_SOURCE` (R2-D08).
 */
interface IProviderRegistry {
    struct ProviderConfig {
        GpuTypes.SourceChainRef sourceChain;
        GpuTypes.ExecutionProfile executionProfile;
        bool testOnly;
        bytes32 policyVersionId;
        bool admissionEnabled;
    }

    event ProviderRegistered(
        GpuTypes.ProviderId indexed providerId,
        bytes32 indexed manifestHash,
        GpuTypes.ExecutionProfile profile,
        bool testOnly
    );
    event EmitterRegistered(
        GpuTypes.ProviderId indexed providerId,
        address indexed emitter,
        bytes32 indexed topic0,
        GpuTypes.EvidenceMeaning meaning
    );
    event EmitterRevoked(GpuTypes.ProviderId indexed providerId, address indexed emitter, bytes32 indexed topic0);
    event TokenAdmitted(GpuTypes.ProviderId indexed providerId, uint64 chainId, address token, uint8 decimals);
    event IssuerSet(GpuTypes.ProviderId indexed providerId, address indexed issuer, bool enabled);
    event AdmissionChanged(GpuTypes.ProviderId indexed providerId, bool enabled, string reason);

    error UnsupportedSource(GpuTypes.ProviderId providerId, uint64 chainKey, bytes32 envIdHash);
    error UnregisteredEmitter(GpuTypes.ProviderId providerId, address emitter, bytes32 topic0);
    error TokenNotAdmitted(GpuTypes.ProviderId providerId, uint64 chainId, address token);
    error ProfileMismatch(GpuTypes.ExecutionProfile expected, GpuTypes.ExecutionProfile actual);
    error AdmissionDisabled(GpuTypes.ProviderId providerId);

    function provider(GpuTypes.ProviderId providerId) external view returns (ProviderConfig memory);
    function isEmitterRegistered(GpuTypes.ProviderId providerId, address emitter, bytes32 topic0)
        external
        view
        returns (bool);
    function emitterMeaning(GpuTypes.ProviderId providerId, address emitter, bytes32 topic0)
        external
        view
        returns (GpuTypes.EvidenceMeaning);
    function isTokenAdmitted(GpuTypes.ProviderId providerId, uint64 chainId, address token) external view returns (bool);
    function isIssuer(GpuTypes.ProviderId providerId, address issuer) external view returns (bool);
    /// @notice True only when the provider's source chain/chainKey/encoding match `manifestHash` and admission is on.
    function isAdmitted(GpuTypes.ProviderId providerId, bytes32 manifestHash) external view returns (bool);
}
