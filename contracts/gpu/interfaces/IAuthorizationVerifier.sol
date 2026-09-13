// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import { GpuTypes } from "../types/GpuTypes.sol";

/**
 * @title IAuthorizationVerifier
 * @notice Verifies auxiliary EIP-712 / ERC-1271 assertions (wallet link, consent, approval, control attestation,
 *         relay, treasury op) with domain, purpose, nonce, expiry and key epoch (GPU-031). Never establishes source
 *         facts and never substitutes native verification (R2-D04).
 */
interface IAuthorizationVerifier {
    event NonceConsumed(address indexed signer, GpuTypes.AssertionPurpose indexed purpose, uint64 nonce);

    error SignatureExpired(uint64 expiresAt, uint64 nowTs);
    error NonceAlreadyUsed(address signer, GpuTypes.AssertionPurpose purpose, uint64 nonce);
    error WrongPurpose(GpuTypes.AssertionPurpose expected, GpuTypes.AssertionPurpose actual);
    error KeyEpochInvalid(address signer, uint64 epoch);
    error BadSignature(address expectedSigner);
    error TtlTooLong(uint64 ttl, uint64 max);

    function domainSeparator() external view returns (bytes32);
    function hashAssertion(GpuTypes.SupplementaryAssertion calldata a) external view returns (bytes32);
    /// @notice View check without consuming the nonce.
    function isValid(GpuTypes.SupplementaryAssertion calldata a, GpuTypes.AssertionPurpose purpose, bytes32 subject)
        external
        view
        returns (bool);
    /// @notice Verify and consume the nonce; reverts with the specific error on failure.
    function verifyAndConsume(
        GpuTypes.SupplementaryAssertion calldata a,
        GpuTypes.AssertionPurpose purpose,
        bytes32 subject
    ) external;
}
