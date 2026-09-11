// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import { IVerifierAdapter, PayoutEvidence } from "../interfaces/IVerifierAdapter.sol";

/**
 * @title MockVerifier
 * @notice Mock verifier for testing HashCreditManager
 * @dev Always verifies successfully, decodes PayoutEvidence from proof bytes
 *      Stateless - replay protection is handled by HashCreditManager
 */
contract MockVerifier is IVerifierAdapter {
    /// @notice Counter for test purposes
    uint256 public verifyCallCount;

    /**
     * @inheritdoc IVerifierAdapter
     */
    function verifyPayout(bytes calldata proof) external override returns (PayoutEvidence memory evidence) {
        verifyCallCount++;

        // Decode evidence from proof (for testing, proof is just the encoded evidence)
        evidence = abi.decode(proof, (PayoutEvidence));

        // NOTE: Verifier is stateless - replay protection is in HashCreditManager
        // This prevents griefing attacks where attacker calls verifyPayout() directly

        return evidence;
    }

    /**
     * @inheritdoc IVerifierAdapter
     * @dev Always returns false - replay protection is in HashCreditManager
     */
    function isPayoutProcessed(bytes32, uint32) external pure override returns (bool) {
        return false;
    }

    /**
     * @notice Helper to encode evidence for testing
     */
    function encodeEvidence(PayoutEvidence memory evidence) external pure returns (bytes memory) {
        return abi.encode(evidence);
    }
}
