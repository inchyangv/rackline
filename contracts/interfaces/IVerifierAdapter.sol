// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * @title IVerifierAdapter
 * @notice Interface for payout verification adapters
 * @dev Implements the Verifier Adapter Pattern - allows swapping verification logic
 *      (e.g., from RelayerSigVerifier to BtcSpvVerifier) without changing Manager/Vault.
 *
 * Two implementations planned:
 * - RelayerSigVerifier: EIP-712 signature from trusted relayer (Hackathon MVP)
 * - BtcSpvVerifier: Bitcoin SPV proof with checkpoint (Production)
 */
interface IVerifierAdapter {
    /**
     * @notice Verify a payout proof and extract validated data
     * @param proof Encoded proof data (format depends on implementation)
     * @return evidence Validated payout evidence
     * @dev MUST revert if verification fails
     *      MUST return valid PayoutEvidence if verification succeeds
     */
    function verifyPayout(bytes calldata proof) external returns (PayoutEvidence memory evidence);

    /**
     * @notice Check if a payout has already been processed (replay protection)
     * @param txid Bitcoin transaction ID (32 bytes, little-endian)
     * @param vout Output index in the transaction
     * @return True if already processed
     */
    function isPayoutProcessed(bytes32 txid, uint32 vout) external view returns (bool);
}

/**
 * @notice Validated payout evidence returned by verifier
 * @dev All monetary amounts are in satoshis (1 BTC = 100_000_000 sats)
 */
struct PayoutEvidence {
    /// @notice The borrower's EVM address who received this payout
    address borrower;
    /// @notice Bitcoin transaction ID (32 bytes, little-endian as stored in Bitcoin)
    bytes32 txid;
    /// @notice Output index within the transaction
    uint32 vout;
    /// @notice Payout amount in satoshis
    uint64 amountSats;
    /// @notice Bitcoin block height where transaction was confirmed
    uint32 blockHeight;
    /// @notice Block timestamp (for time-based windowing)
    uint32 blockTimestamp;
}
