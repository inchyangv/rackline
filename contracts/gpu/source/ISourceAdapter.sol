// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

/**
 * @title ISourceAdapter
 * @notice Capability description of one provider's source contract as seen by the destination app (GPU-077).
 *         A real partner adapter (Aethir / GPU.net) is recorded only after GPU-004/005/008 confirm its ABI; until
 *         then the only implementation is the TEST_ONLY `SourceEscrow` + `MockDePINPayout` pair.
 * @dev Capabilities are declarations for admission logic, never evidence: a payout-only source cannot create a
 *      borrowing base (R2-O03 / evidence-contract.md §4 "payout-only providers").
 */
interface ISourceAdapter {
    struct Capabilities {
        bool provableObligation; // ObligationRecognized natively provable
        bool provableAssignment; // ObligationAssigned natively provable
        bool provablePayout; // PayoutReceived natively provable
        bool provableCheckpoint; // SourceCheckpoint natively provable (freshness gate)
        bool measuredPayouts; // payout amounts are escrow-measured deltas, not caller-supplied
        bool simulatedRevenue; // TEST_ONLY provider: earningsProvenance = SIMULATED
    }

    function capabilities() external pure returns (Capabilities memory);
    function sourceContract() external view returns (address);
}
