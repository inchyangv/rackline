// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import { GpuTypes } from "../types/GpuTypes.sol";

/**
 * @title IRevenueEscrow
 * @notice Source-chain controlled receiver (GPU-077/037). Emits the internal source events of
 *         test/fixtures/gpu/attestcoin/source-events-v1.abi.json. Amounts are exact balance deltas measured by the
 *         escrow; there is no `notify(amount)` and re-reporting an existing balance is impossible.
 * @dev Unattributed deposits are UNCLASSIFIED until reconciled; borrower self-transfers are never revenue.
 */
interface IRevenueEscrow {
    event ObligationRecognized(
        bytes32 indexed accountKey,
        bytes32 indexed obligationRef,
        address indexed issuer,
        address payer,
        address payee,
        uint256 amount,
        uint64 dueAt,
        uint32 revision
    );
    event ObligationAssigned(
        bytes32 indexed accountKey, bytes32 indexed obligationRef, bytes32 indexed facilityKey, uint32 revision
    );
    event ObligationCorrected(
        bytes32 indexed accountKey, bytes32 indexed obligationRef, int256 delta, uint32 revision, uint8 reason
    );
    event PayoutReceived(
        bytes32 indexed accountKey,
        bytes32 indexed obligationRef,
        address indexed token,
        address payer,
        uint256 amount,
        uint64 settlementSeq
    );
    event PayoutCancelled(
        bytes32 indexed accountKey, bytes32 indexed obligationRef, uint64 settlementSeq, uint256 amount
    );
    event SourceCheckpoint(
        bytes32 indexed accountKey,
        uint64 checkpointSeq,
        uint32 latestRevision,
        uint256 openAmount,
        uint256 paidCumulative
    );
    event Swept(
        bytes32 indexed accountKey,
        address indexed token,
        uint256 repaymentShare,
        uint256 operatorShare,
        uint64 settlementSeq
    );
    event Released(bytes32 indexed accountKey, address receiverReturnedTo, uint64 at);

    error NotIssuer(address caller);
    error NotController(address caller);
    error NoBalanceDelta();
    error UnsupportedToken(address token);
    error ReleaseBlocked(string reason);
    error RevisionNotMonotonic(uint32 current, uint32 given);

    function accountKey() external view returns (bytes32);
    function settlementSeq() external view returns (uint64);
    function controller() external view returns (address);
    function isReleased() external view returns (bool);
}
