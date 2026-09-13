// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

/**
 * @title ISourceEscrow
 * @notice Source-chain receipt + issuer-binding module (GPU-077). Lives on the SOURCE chain (e.g. Sepolia for the
 *         TEST_ONLY MockDePIN path); its logs are what GPU-078 verifies natively on Creditcoin.
 * @dev The six business events below are byte-identical to `test/fixtures/gpu/attestcoin/source-events-v1.abi.json`
 *      (GPU-076 proposal, NOT a partner ABI). `UnattributedDeposit`, `StatementAnchored` and `RoleChanged` are escrow
 *      internal events: they are never registered as revenue meanings in the ProviderRegistry.
 *      - `PayoutReceived.amount` is always the balance delta the escrow measured itself; there is no `notify(amount)`.
 *      - Obligation events correspond to a stored state transition (created / assigned / corrected / paid).
 *      - Unattributed deposits (self-transfer, donation, unknown origin) are held in a separate bucket and never emit
 *        a PAYOUT/OBLIGATION event.
 */
interface ISourceEscrow {
    enum ObligationStatus {
        NONE,
        OPEN,
        PAID,
        CANCELLED
    }

    enum CorrectionReason {
        DISPUTE,
        REFUND,
        SLA,
        CANCEL,
        OTHER
    }

    /// @notice Origin class of an unattributed deposit; mirrors GpuTypes.EarningsProvenance names for the two cases.
    enum UnattributedOrigin {
        SELF_TRANSFER,
        THIRD_PARTY_UNKNOWN
    }

    /// @notice Whether this deployment is bound to a real partner's settlement flow. Always UNCONFIGURED here.
    enum PartnerSourceBinding {
        UNCONFIGURED,
        VERIFIED
    }

    struct Obligation {
        bytes32 accountKey;
        address payer;
        address token;
        uint256 net; // current recognised amount net of issuer deductions (after corrections)
        uint256 paid; // sum of measured payouts attributed to this obligation, minus cancellations
        uint64 dueAt; // issuer-claimed, never proven time
        uint32 revision; // monotonic; every event on this obligation bumps it
        bytes32 assignedTo; // facilityKey or 0
        ObligationStatus status;
    }

    struct Payout {
        bytes32 accountKey;
        bytes32 obligationRef;
        address token;
        address payer;
        uint256 amount;
        bool cancelled;
    }

    // ------------------------------------------------------------------ events == source-events-v1.abi.json

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

    /// @notice v2 binds the denomination before the first payment. v1 remains an audit/history event only.
    event ObligationRecognizedV2(
        bytes32 indexed accountKey, bytes32 indexed obligationRef, address indexed issuer,
        address payer, address payee, address token, uint256 amount, uint64 dueAt, uint32 revision
    );
    /// @notice Source time and a non-revocable reservation bound the current-unpaid claim through draw execution.
    event SourceCheckpointV2(
        bytes32 indexed accountKey, uint64 checkpointSeq, uint32 latestRevision, uint256 openAmount,
        uint256 paidCumulative, uint64 observedAt, uint64 protectedUntil
    );

    // ------------------------------------------------------------------ escrow-internal events (never revenue)

    /// @notice Measured deposit that is not a registered-payer settlement. Never a PAYOUT.
    event UnattributedDeposit(
        address indexed token, address indexed from, uint256 amount, uint64 depositSeq, UnattributedOrigin origin
    );
    /// @notice Our own server anchoring a statement hash. OFFCHAIN_ASSERTION provenance; never an obligation.
    event StatementAnchored(bytes32 indexed accountKey, bytes32 indexed statementHash, address indexed anchoredBy);
    /// @notice Role / registration change history (owner, issuer, controller, payer, anchor, upgradeAdmin).
    event RoleChanged(bytes32 indexed role, address indexed account, bool enabled, address indexed by);
    event AccountRegistered(bytes32 indexed accountKey, address indexed borrowerWallet, address indexed by);
    event TokenAdmitted(address indexed token, uint8 decimals, bool nonstandardAllowed, address indexed by);
    event Withdrawn(address indexed token, address indexed to, uint256 amount, address indexed by);

    // ------------------------------------------------------------------ errors

    error NotOwner(address caller);
    error NotIssuer(address caller);
    error NotIssuerOrController(address caller);
    error NotAnchor(address caller);
    error NotRegisteredPayer(address caller);
    error PayerIsBorrowerWallet(address account);
    error TokenNotAdmitted(address token);
    error AccountUnknown(bytes32 accountKey);
    error ObligationExists(bytes32 accountKey, bytes32 obligationRef);
    error ObligationNotOpen(bytes32 accountKey, bytes32 obligationRef, ObligationStatus status);
    error ObligationTokenMismatch(address expected, address actual);
    error AlreadyAssigned(bytes32 obligationRef, bytes32 facilityKey);
    error SettlementIdUsed(address payer, bytes32 settlementId);
    error MeasuredDeltaMismatch(uint256 declared, uint256 measured);
    error Overpayment(uint256 remaining, uint256 amount);
    error PayoutAlreadyCancelled(uint64 settlementSeq);
    error PayoutUnknown(uint64 settlementSeq);
    error CorrectionBelowPaid(uint256 paid, int256 delta);
    error CancelMustZeroOpenAmount(uint256 open, int256 delta);
    error NoUnattributedBalance(address token);
    error ZeroAmount();
    error Reentrancy();
    error TransferFailed();
    error AccountReserved(bytes32 accountKey, uint64 protectedUntil);
    error InvalidReservationWindow();

    // ------------------------------------------------------------------ views

    function partnerSourceBinding() external pure returns (PartnerSourceBinding);
    function obligation(bytes32 accountKey, bytes32 obligationRef) external view returns (Obligation memory);
    function payout(uint64 settlementSeq) external view returns (Payout memory);
    function accountLatestRevision(bytes32 accountKey) external view returns (uint32);
    function accountOpenAmount(bytes32 accountKey) external view returns (uint256);
    function accountPaidCumulative(bytes32 accountKey) external view returns (uint256);
    function trackedBalance(address token) external view returns (uint256);
    function unattributedBalance(address token) external view returns (uint256);
    function isIssuer(address account) external view returns (bool);
    function isController(address account) external view returns (bool);
    function isRegisteredPayer(address account) external view returns (bool);
    function borrowerWalletOf(bytes32 accountKey) external view returns (address);
}
