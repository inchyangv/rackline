// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import { GpuTypes } from "./types/GpuTypes.sol";
import { IProviderRegistry } from "./interfaces/IProviderRegistry.sol";
import { IProtocolRoles } from "./interfaces/IProtocolRoles.sol";

/**
 * @title ProviderRegistry
 * @notice Configuration of settlement providers: source chain binding (from the environment manifest), registered
 *         source emitters with the event meaning they may carry, admitted tokens, issuer addresses, admission switch
 *         and policy version (GPU-030). Consulted by the verifier (GPU-078), evidence book (GPU-031) and policy.
 * @dev Registration is configuration, never evidence: it does not prove GPU ownership, revenue or E2 control.
 *      - PRODUCTION providers cannot be testOnly; only encoding 1 is accepted (SDK EncodingVersion.V1).
 *      - `isAdmitted` requires the provider's manifest hash to equal the verifier's manifest hash (no cross-env reuse).
 *      - Emitters are registered per (provider, emitter, topic0) with an optional code hash and upgrade admin;
 *        the same topics from an unregistered emitter never match (fake emitter injection).
 */
contract ProviderRegistry is IProviderRegistry {
    IProtocolRoles public immutable ROLES;

    struct EmitterInfo {
        bool registered;
        GpuTypes.EvidenceMeaning meaning;
        bytes32 codeHash; // optional expected EXTCODEHASH on the source chain (informational; source-chain only)
        address upgradeAdmin; // optional: who may upgrade the emitter on the source chain (informational)
    }

    mapping(GpuTypes.ProviderId => ProviderConfig) private _providers;
    mapping(GpuTypes.ProviderId => bool) private _exists;
    mapping(GpuTypes.ProviderId => mapping(address emitter => mapping(bytes32 topic0 => EmitterInfo))) private
        _emitters;
    mapping(GpuTypes.ProviderId => mapping(uint64 chainId => mapping(address token => uint8 decimalsPlusOne))) private
        _tokens;
    mapping(GpuTypes.ProviderId => mapping(address issuer => bool)) private _issuers;

    error NotRegistrar(address caller);
    error NotGuardianOrUnderwriter(address caller);
    error ProviderExists(GpuTypes.ProviderId providerId);
    error ProviderUnknown(GpuTypes.ProviderId providerId);
    error TestOnlyInProduction(GpuTypes.ProviderId providerId);

    constructor(IProtocolRoles roles) {
        ROLES = roles;
    }

    modifier onlyRegistrar() {
        if (!ROLES.hasRole(ROLES.REGISTRAR(), msg.sender)) revert NotRegistrar(msg.sender);
        _;
    }

    modifier onlyGuardianOrUnderwriter() {
        if (!ROLES.hasRole(ROLES.GUARDIAN(), msg.sender) && !ROLES.hasRole(ROLES.UNDERWRITER(), msg.sender)) {
            revert NotGuardianOrUnderwriter(msg.sender);
        }
        _;
    }

    // ------------------------------------------------------------------ registration (REGISTRAR)

    function registerProvider(GpuTypes.ProviderId providerId, ProviderConfig calldata cfg) external onlyRegistrar {
        if (_exists[providerId]) revert ProviderExists(providerId);
        if (cfg.executionProfile == GpuTypes.ExecutionProfile.PRODUCTION && cfg.testOnly) {
            revert TestOnlyInProduction(providerId);
        }
        if (cfg.executionProfile != GpuTypes.ExecutionProfile.PRODUCTION && !cfg.testOnly) {
            revert TestOnlyInProduction(providerId);
        }
        if (cfg.sourceChain.encoding != 1 || cfg.sourceChain.chainKey == 0 || cfg.sourceChain.chainId == 0) {
            revert UnsupportedSource(providerId, cfg.sourceChain.chainKey, cfg.sourceChain.envIdHash);
        }
        _providers[providerId] = cfg;
        _exists[providerId] = true;
        emit ProviderRegistered(providerId, cfg.sourceChain.manifestHash, cfg.executionProfile, cfg.testOnly);
        if (cfg.admissionEnabled) emit AdmissionChanged(providerId, true, "registered");
    }

    function registerEmitter(
        GpuTypes.ProviderId providerId,
        address emitter,
        bytes32 topic0,
        GpuTypes.EvidenceMeaning meaning,
        bytes32 codeHash,
        address upgradeAdmin
    ) external onlyRegistrar {
        if (!_exists[providerId]) revert ProviderUnknown(providerId);
        _emitters[providerId][emitter][topic0] =
            EmitterInfo({ registered: true, meaning: meaning, codeHash: codeHash, upgradeAdmin: upgradeAdmin });
        emit EmitterRegistered(providerId, emitter, topic0, meaning);
    }

    function revokeEmitter(GpuTypes.ProviderId providerId, address emitter, bytes32 topic0) external onlyRegistrar {
        delete _emitters[providerId][emitter][topic0];
        emit EmitterRevoked(providerId, emitter, topic0);
    }

    function admitToken(GpuTypes.ProviderId providerId, uint64 chainId, address token, uint8 decimals)
        external
        onlyRegistrar
    {
        if (!_exists[providerId]) revert ProviderUnknown(providerId);
        _tokens[providerId][chainId][token] = decimals + 1;
        emit TokenAdmitted(providerId, chainId, token, decimals);
    }

    function setIssuer(GpuTypes.ProviderId providerId, address issuer, bool enabled) external onlyRegistrar {
        if (!_exists[providerId]) revert ProviderUnknown(providerId);
        _issuers[providerId][issuer] = enabled;
        emit IssuerSet(providerId, issuer, enabled);
    }

    function setPolicyVersion(GpuTypes.ProviderId providerId, bytes32 policyVersionId) external onlyRegistrar {
        if (!_exists[providerId]) revert ProviderUnknown(providerId);
        _providers[providerId].policyVersionId = policyVersionId;
    }

    // ------------------------------------------------------------------ admission (GUARDIAN / UNDERWRITER)

    function setAdmission(GpuTypes.ProviderId providerId, bool enabled, string calldata reason)
        external
        onlyGuardianOrUnderwriter
    {
        if (!_exists[providerId]) revert ProviderUnknown(providerId);
        _providers[providerId].admissionEnabled = enabled;
        emit AdmissionChanged(providerId, enabled, reason);
    }

    // ------------------------------------------------------------------ views

    function provider(GpuTypes.ProviderId providerId) external view override returns (ProviderConfig memory) {
        if (!_exists[providerId]) revert ProviderUnknown(providerId);
        return _providers[providerId];
    }

    function exists(GpuTypes.ProviderId providerId) external view returns (bool) {
        return _exists[providerId];
    }

    function isEmitterRegistered(GpuTypes.ProviderId providerId, address emitter, bytes32 topic0)
        public
        view
        override
        returns (bool)
    {
        return _emitters[providerId][emitter][topic0].registered;
    }

    function emitterMeaning(GpuTypes.ProviderId providerId, address emitter, bytes32 topic0)
        external
        view
        override
        returns (GpuTypes.EvidenceMeaning)
    {
        EmitterInfo storage e = _emitters[providerId][emitter][topic0];
        if (!e.registered) revert UnregisteredEmitter(providerId, emitter, topic0);
        return e.meaning;
    }

    function emitterInfo(GpuTypes.ProviderId providerId, address emitter, bytes32 topic0)
        external
        view
        returns (EmitterInfo memory)
    {
        return _emitters[providerId][emitter][topic0];
    }

    function isTokenAdmitted(GpuTypes.ProviderId providerId, uint64 chainId, address token)
        external
        view
        override
        returns (bool)
    {
        return _tokens[providerId][chainId][token] != 0;
    }

    function tokenDecimals(GpuTypes.ProviderId providerId, uint64 chainId, address token)
        external
        view
        returns (uint8)
    {
        uint8 d = _tokens[providerId][chainId][token];
        if (d == 0) revert TokenNotAdmitted(providerId, chainId, token);
        return d - 1;
    }

    function isIssuer(GpuTypes.ProviderId providerId, address issuer) external view override returns (bool) {
        return _issuers[providerId][issuer];
    }

    function isAdmitted(GpuTypes.ProviderId providerId, bytes32 manifestHash) external view override returns (bool) {
        if (!_exists[providerId]) return false;
        ProviderConfig storage cfg = _providers[providerId];
        return cfg.admissionEnabled && cfg.sourceChain.manifestHash == manifestHash && cfg.sourceChain.encoding == 1;
    }
}
