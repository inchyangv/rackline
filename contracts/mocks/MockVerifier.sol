// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import { IVerifierAdapter, PayoutEvidence } from "../interfaces/IVerifierAdapter.sol";

/**
 * @title MockVerifier
 * @notice Mock verifier for testing HashCreditManager
 * @dev Always verifies successfully, decodes PayoutEvidence from proof bytes
 */
contract MockVerifier is IVerifierAdapter {
    /// @notice Mapping of processed payouts
    mapping(bytes32 => bool) private _processed;

    /// @notice Counter for test purposes
    uint256 public verifyCallCount;

    /**
     * @inheritdoc IVerifierAdapter
     */
    function verifyPayout(bytes calldata proof) external override returns (PayoutEvidence memory evidence) {
        verifyCallCount++;

        // Decode evidence from proof (for testing, proof is just the encoded evidence)
        evidence = abi.decode(proof, (PayoutEvidence));

        // Mark as processed
        bytes32 key = keccak256(abi.encodePacked(evidence.txid, evidence.vout));
        _processed[key] = true;

        return evidence;
    }

    /**
     * @inheritdoc IVerifierAdapter
     */
    function isPayoutProcessed(bytes32 txid, uint32 vout) external view override returns (bool) {
        return _processed[keccak256(abi.encodePacked(txid, vout))];
    }

    /**
     * @notice Helper to encode evidence for testing
     */
    function encodeEvidence(PayoutEvidence memory evidence) external pure returns (bytes memory) {
        return abi.encode(evidence);
    }
}
