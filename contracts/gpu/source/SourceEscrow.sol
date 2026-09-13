// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import { ISourceEscrow } from "./ISourceEscrow.sol";

interface IERC20Minimal {
    function balanceOf(address) external view returns (uint256);
    function transfer(address, uint256) external returns (bool);
    function transferFrom(address, address, uint256) external returns (bool);
}

/**
 * @title SourceEscrow (Rackline-controlled source contract; TEST_ONLY until a partner binding exists)
 * @notice Minimal receipt / issuer-binding module for the source chain (GPU-077). It is the `payee` of recognised
 *         obligations and the emitter that GPU-078 verifies. `partnerSourceBinding` is permanently UNCONFIGURED: no
 *         real partner has recognised this contract as its settlement path (GPU-004/005/009/056 are external gates).
 * @dev Invariants enforced in code (not by convention):
 *      - A PAYOUT event carries only the balance delta measured by this contract inside the same call
 *        (`transferFrom` before/after); `settle` from anyone but a registered payer reverts. No `notify(amount)`.
 *      - `settlementId` is unique per payer; `settlementSeq` is a global monotonic counter — replay is impossible.
 *      - Non-standard tokens (fee-on-transfer, rebasing): measured delta != declared amount reverts unless the token
 * was
 *        admitted with `nonstandardAllowed`; then only the measured delta is credited.
 *      - Direct transfers / self-transfers / donations are recorded as `UnattributedDeposit` in a separate bucket and
 * are
 *        never re-labelled as a payout on-chain (off-chain reconciliation only; refund via `withdraw`).
 *      - Obligation events are issuer-only and always a stored state transition with a monotonic revision;
 *        a ref is single-use (PAID/CANCELLED refs cannot be re-recognised as a new receivable).
 *      - `StatementAnchored` is an explicit OFFCHAIN_ASSERTION by our anchor role; it never touches obligations.
 *      - Every role / registration change emits `RoleChanged` history.
 */
contract SourceEscrow is ISourceEscrow {
    bytes32 public constant ROLE_OWNER = keccak256("OWNER");
    bytes32 public constant ROLE_ISSUER = keccak256("ISSUER");
    bytes32 public constant ROLE_CONTROLLER = keccak256("CONTROLLER");
    bytes32 public constant ROLE_PAYER = keccak256("PAYER");
    bytes32 public constant ROLE_ANCHOR = keccak256("ANCHOR");
    bytes32 public constant ROLE_UPGRADE_ADMIN = keccak256("UPGRADE_ADMIN");

    address public owner;
    /// @dev Informational: who could upgrade this contract on the source chain. This deployment is not a proxy.
    address public upgradeAdmin;

    mapping(address => bool) private _issuers;
    mapping(address => bool) private _controllers;
    mapping(address => bool) private _payers;
    mapping(address => bool) private _anchors;

    struct TokenInfo {
        bool admitted;
        uint8 decimals;
        bool nonstandardAllowed;
    }

    mapping(address => TokenInfo) public tokenInfo;
    mapping(bytes32 => address) private _borrowerWallet; // accountKey => borrower wallet (self-transfer detection)
    mapping(address => bool) private _isBorrowerWallet;

    mapping(bytes32 => mapping(bytes32 => Obligation)) private _obligations;
    mapping(bytes32 => uint32) private _latestRevision;
    mapping(bytes32 => uint256) private _openAmount;
    mapping(bytes32 => uint256) private _paidCumulative;
    mapping(bytes32 => uint64) public checkpointSeq;

    mapping(address => mapping(bytes32 => bool)) private _settlementUsed; // payer => settlementId
    mapping(uint64 => Payout) private _payouts;
    uint64 public settlementSeq;
    uint64 public depositSeq;

    mapping(address => uint256) private _tracked; // token => balance this contract accounted for
    mapping(address => uint256) private _unattributed; // token => unattributed bucket

    uint256 private _lock = 1;

    constructor(address owner_, address upgradeAdmin_) {
        owner = owner_;
        upgradeAdmin = upgradeAdmin_;
        emit RoleChanged(ROLE_OWNER, owner_, true, msg.sender);
        emit RoleChanged(ROLE_UPGRADE_ADMIN, upgradeAdmin_, true, msg.sender);
    }

    // ------------------------------------------------------------------ modifiers

    modifier onlyOwner() {
        if (msg.sender != owner) revert NotOwner(msg.sender);
        _;
    }

    modifier onlyIssuer() {
        if (!_issuers[msg.sender]) revert NotIssuer(msg.sender);
        _;
    }

    modifier nonReentrant() {
        if (_lock != 1) revert Reentrancy();
        _lock = 2;
        _;
        _lock = 1;
    }

    // ------------------------------------------------------------------ binding views

    function partnerSourceBinding() external pure override returns (PartnerSourceBinding) {
        return PartnerSourceBinding.UNCONFIGURED;
    }

    // ------------------------------------------------------------------ roles / registration (OWNER)

    function transferOwnership(address newOwner) external onlyOwner {
        emit RoleChanged(ROLE_OWNER, owner, false, msg.sender);
        owner = newOwner;
        emit RoleChanged(ROLE_OWNER, newOwner, true, msg.sender);
    }

    function setUpgradeAdmin(address admin) external onlyOwner {
        emit RoleChanged(ROLE_UPGRADE_ADMIN, upgradeAdmin, false, msg.sender);
        upgradeAdmin = admin;
        emit RoleChanged(ROLE_UPGRADE_ADMIN, admin, true, msg.sender);
    }

    function setIssuer(address account, bool enabled) external onlyOwner {
        _issuers[account] = enabled;
        emit RoleChanged(ROLE_ISSUER, account, enabled, msg.sender);
    }

    function setController(address account, bool enabled) external onlyOwner {
        _controllers[account] = enabled;
        emit RoleChanged(ROLE_CONTROLLER, account, enabled, msg.sender);
    }

    function setAnchor(address account, bool enabled) external onlyOwner {
        _anchors[account] = enabled;
        emit RoleChanged(ROLE_ANCHOR, account, enabled, msg.sender);
    }

    /// @notice Register a settlement payer (the provider's paying contract/wallet). Borrower wallets are refused so a
    ///         borrower can never make its own transfer look like a provider settlement.
    function setPayer(address account, bool enabled) external onlyOwner {
        if (enabled && _isBorrowerWallet[account]) revert PayerIsBorrowerWallet(account);
        _payers[account] = enabled;
        emit RoleChanged(ROLE_PAYER, account, enabled, msg.sender);
    }

    function registerAccount(bytes32 accountKey, address borrowerWallet) external onlyOwner {
        if (_payers[borrowerWallet]) revert PayerIsBorrowerWallet(borrowerWallet);
        address previous = _borrowerWallet[accountKey];
        if (previous != address(0)) _isBorrowerWallet[previous] = false;
        _borrowerWallet[accountKey] = borrowerWallet;
        _isBorrowerWallet[borrowerWallet] = true;
        emit AccountRegistered(accountKey, borrowerWallet, msg.sender);
    }

    function admitToken(address token, uint8 decimals, bool nonstandardAllowed) external onlyOwner {
        tokenInfo[token] = TokenInfo({ admitted: true, decimals: decimals, nonstandardAllowed: nonstandardAllowed });
        emit TokenAdmitted(token, decimals, nonstandardAllowed, msg.sender);
    }

    // ------------------------------------------------------------------ obligations (ISSUER)

    function recognizeObligation(
        bytes32 accountKey,
        bytes32 obligationRef,
        address payer,
        address token,
        uint256 amount,
        uint64 dueAt
    ) external onlyIssuer {
        if (_borrowerWallet[accountKey] == address(0)) revert AccountUnknown(accountKey);
        if (!tokenInfo[token].admitted) revert TokenNotAdmitted(token);
        if (amount == 0) revert ZeroAmount();
        Obligation storage o = _obligations[accountKey][obligationRef];
        if (o.status != ObligationStatus.NONE) revert ObligationExists(accountKey, obligationRef);
        o.accountKey = accountKey;
        o.payer = payer;
        o.token = token;
        o.net = amount;
        o.dueAt = dueAt;
        o.revision = 1;
        o.status = ObligationStatus.OPEN;
        _openAmount[accountKey] += amount;
        _bumpAccountRevision(accountKey, 1);
        emit ObligationRecognized(accountKey, obligationRef, msg.sender, payer, address(this), amount, dueAt, 1);
    }

    function assignObligation(bytes32 accountKey, bytes32 obligationRef, bytes32 facilityKey) external {
        if (!_issuers[msg.sender] && !_controllers[msg.sender]) revert NotIssuerOrController(msg.sender);
        Obligation storage o = _obligations[accountKey][obligationRef];
        if (o.status != ObligationStatus.OPEN) revert ObligationNotOpen(accountKey, obligationRef, o.status);
        if (o.assignedTo != bytes32(0) && o.assignedTo != facilityKey) {
            revert AlreadyAssigned(obligationRef, o.assignedTo);
        }
        o.assignedTo = facilityKey;
        uint32 rev = ++o.revision;
        _bumpAccountRevision(accountKey, rev);
        emit ObligationAssigned(accountKey, obligationRef, facilityKey, rev);
    }

    /// @notice Signed correction of the recognised net amount. CANCEL must bring the open (unpaid) amount to zero.
    function correctObligation(bytes32 accountKey, bytes32 obligationRef, int256 delta, CorrectionReason reason)
        external
        onlyIssuer
    {
        Obligation storage o = _obligations[accountKey][obligationRef];
        if (o.status != ObligationStatus.OPEN) revert ObligationNotOpen(accountKey, obligationRef, o.status);
        uint256 newNet;
        if (delta < 0) {
            uint256 dec = uint256(-delta);
            if (dec > o.net || o.net - dec < o.paid) revert CorrectionBelowPaid(o.paid, delta);
            newNet = o.net - dec;
        } else {
            newNet = o.net + uint256(delta);
        }
        uint256 openBefore = o.net - o.paid;
        uint256 openAfter = newNet - o.paid;
        if (reason == CorrectionReason.CANCEL) {
            if (openAfter != 0) revert CancelMustZeroOpenAmount(openBefore, delta);
            o.status = ObligationStatus.CANCELLED;
        }
        o.net = newNet;
        _openAmount[accountKey] = _openAmount[accountKey] - openBefore + openAfter;
        uint32 rev = ++o.revision;
        _bumpAccountRevision(accountKey, rev);
        emit ObligationCorrected(accountKey, obligationRef, delta, rev, uint8(reason));
    }

    /// @notice Issuer publishes the account's current state (freshness gate input, evidence-contract.md §6).
    function publishCheckpoint(bytes32 accountKey) external onlyIssuer {
        if (_borrowerWallet[accountKey] == address(0)) revert AccountUnknown(accountKey);
        uint64 seq = ++checkpointSeq[accountKey];
        emit SourceCheckpoint(
            accountKey, seq, _latestRevision[accountKey], _openAmount[accountKey], _paidCumulative[accountKey]
        );
    }

    /// @notice Our own server's statement hash. Explicit assertion; changes no obligation state.
    function anchorStatement(bytes32 accountKey, bytes32 statementHash) external {
        if (!_anchors[msg.sender]) revert NotAnchor(msg.sender);
        emit StatementAnchored(accountKey, statementHash, msg.sender);
    }

    // ------------------------------------------------------------------ receipts (registered PAYER)

    /**
     * @notice Settle `amount` of `token` from the calling registered payer. The PAYOUT amount is the measured delta.
     * @param obligationRef 0 when the payment is not attributable to one obligation (stays unattributed-to-obligation
     *        but is still a provider settlement).
     */
    function settle(bytes32 accountKey, bytes32 obligationRef, address token, uint256 amount, bytes32 settlementId)
        external
        nonReentrant
        returns (uint64 seq, uint256 measured)
    {
        if (!_payers[msg.sender]) revert NotRegisteredPayer(msg.sender);
        if (_borrowerWallet[accountKey] == address(0)) revert AccountUnknown(accountKey);
        TokenInfo memory t = tokenInfo[token];
        if (!t.admitted) revert TokenNotAdmitted(token);
        if (amount == 0) revert ZeroAmount();
        if (_settlementUsed[msg.sender][settlementId]) revert SettlementIdUsed(msg.sender, settlementId);
        _settlementUsed[msg.sender][settlementId] = true;

        measured = _pull(token, msg.sender, amount);
        if (measured != amount && !t.nonstandardAllowed) revert MeasuredDeltaMismatch(amount, measured);
        if (measured == 0) revert ZeroAmount();

        if (obligationRef != bytes32(0)) {
            Obligation storage o = _obligations[accountKey][obligationRef];
            if (o.status != ObligationStatus.OPEN) revert ObligationNotOpen(accountKey, obligationRef, o.status);
            if (o.token != token) revert ObligationTokenMismatch(o.token, token);
            uint256 remaining = o.net - o.paid;
            if (measured > remaining) revert Overpayment(remaining, measured);
            o.paid += measured;
            _openAmount[accountKey] -= measured;
            if (o.paid == o.net) o.status = ObligationStatus.PAID;
            uint32 rev = ++o.revision;
            _bumpAccountRevision(accountKey, rev);
        }
        _paidCumulative[accountKey] += measured;
        _tracked[token] += measured;
        seq = ++settlementSeq;
        _payouts[seq] = Payout({
            accountKey: accountKey,
            obligationRef: obligationRef,
            token: token,
            payer: msg.sender,
            amount: measured,
            cancelled: false
        });
        emit PayoutReceived(accountKey, obligationRef, token, msg.sender, measured, seq);
    }

    /// @notice Reverse a prior payout (chargeback/clawback). Tokens actually leave the escrow back to the payer.
    function cancelPayout(uint64 seq) external onlyIssuer nonReentrant {
        Payout storage p = _payouts[seq];
        if (p.payer == address(0)) revert PayoutUnknown(seq);
        if (p.cancelled) revert PayoutAlreadyCancelled(seq);
        p.cancelled = true;
        if (p.obligationRef != bytes32(0)) {
            Obligation storage o = _obligations[p.accountKey][p.obligationRef];
            o.paid -= p.amount;
            _openAmount[p.accountKey] += p.amount;
            if (o.status == ObligationStatus.PAID) o.status = ObligationStatus.OPEN;
            uint32 rev = ++o.revision;
            _bumpAccountRevision(p.accountKey, rev);
        }
        _paidCumulative[p.accountKey] -= p.amount;
        _tracked[p.token] -= p.amount;
        _push(p.token, p.payer, p.amount);
        emit PayoutCancelled(p.accountKey, p.obligationRef, seq, p.amount);
    }

    // ------------------------------------------------------------------ unattributed deposits (anyone)

    /// @notice Deposit through the module without being a registered payer. Measured, bucketed, never a payout.
    function depositUnattributed(address token, uint256 amount)
        external
        nonReentrant
        returns (uint64 seq, uint256 measured)
    {
        if (!tokenInfo[token].admitted) revert TokenNotAdmitted(token);
        if (amount == 0) revert ZeroAmount();
        measured = _pull(token, msg.sender, amount);
        if (measured == 0) revert ZeroAmount();
        seq = _recordUnattributed(token, msg.sender, measured);
    }

    /// @notice Sweep a direct `transfer` into the unattributed bucket (origin unknown ⇒ THIRD_PARTY_UNKNOWN).
    function recordDirectDeposit(address token) external nonReentrant returns (uint64 seq, uint256 measured) {
        if (!tokenInfo[token].admitted) revert TokenNotAdmitted(token);
        uint256 bal = IERC20Minimal(token).balanceOf(address(this));
        if (bal <= _tracked[token]) revert NoUnattributedBalance(token);
        measured = bal - _tracked[token];
        seq = _recordUnattributed(token, address(0), measured);
    }

    function _recordUnattributed(address token, address from, uint256 measured) internal returns (uint64 seq) {
        _tracked[token] += measured;
        _unattributed[token] += measured;
        seq = ++depositSeq;
        UnattributedOrigin origin =
            _isBorrowerWallet[from] ? UnattributedOrigin.SELF_TRANSFER : UnattributedOrigin.THIRD_PARTY_UNKNOWN;
        emit UnattributedDeposit(token, from, measured, seq, origin);
    }

    // ------------------------------------------------------------------ treasury (OWNER)

    /// @notice Move tokens out (sweep to destination rail or refund). Tracked balance shrinks; a later `settle` still
    ///         needs a fresh measured transfer, so "sweep then re-notify" cannot re-create a payout.
    function withdraw(address token, address to, uint256 amount) external onlyOwner nonReentrant {
        if (amount == 0) revert ZeroAmount();
        uint256 fromUnattributed = amount <= _unattributed[token] ? amount : _unattributed[token];
        _unattributed[token] -= fromUnattributed;
        _tracked[token] -= amount;
        _push(token, to, amount);
        emit Withdrawn(token, to, amount, msg.sender);
    }

    // ------------------------------------------------------------------ views

    function obligation(bytes32 accountKey, bytes32 obligationRef) external view override returns (Obligation memory) {
        return _obligations[accountKey][obligationRef];
    }

    function payout(uint64 seq) external view override returns (Payout memory) {
        return _payouts[seq];
    }

    function accountLatestRevision(bytes32 accountKey) external view override returns (uint32) {
        return _latestRevision[accountKey];
    }

    function accountOpenAmount(bytes32 accountKey) external view override returns (uint256) {
        return _openAmount[accountKey];
    }

    function accountPaidCumulative(bytes32 accountKey) external view override returns (uint256) {
        return _paidCumulative[accountKey];
    }

    function trackedBalance(address token) external view override returns (uint256) {
        return _tracked[token];
    }

    function unattributedBalance(address token) external view override returns (uint256) {
        return _unattributed[token];
    }

    function isIssuer(address account) external view override returns (bool) {
        return _issuers[account];
    }

    function isController(address account) external view override returns (bool) {
        return _controllers[account];
    }

    function isRegisteredPayer(address account) external view override returns (bool) {
        return _payers[account];
    }

    function borrowerWalletOf(bytes32 accountKey) external view override returns (address) {
        return _borrowerWallet[accountKey];
    }

    // ------------------------------------------------------------------ internals

    /// @dev Account-level revision counter: +1 per obligation-state event. Because every obligation starts at
    ///      revision 1 and each event bumps exactly one obligation by 1, the invariant
    ///      `accountLatestRevision == Σ obligation.revision over the account` holds; the destination uses it as the
    ///      revision-gap detector against `SourceCheckpoint.latestRevision` (evidence-contract.md §6).
    function _bumpAccountRevision(bytes32 accountKey, uint32) internal {
        _latestRevision[accountKey] += 1;
    }

    /// @dev Pull `amount` via transferFrom and return the balance delta this contract actually observed.
    function _pull(address token, address from, uint256 amount) internal returns (uint256 measured) {
        IERC20Minimal t = IERC20Minimal(token);
        uint256 before = t.balanceOf(address(this));
        _call(token, abi.encodeCall(t.transferFrom, (from, address(this), amount)));
        uint256 after_ = t.balanceOf(address(this));
        measured = after_ > before ? after_ - before : 0;
    }

    function _push(address token, address to, uint256 amount) internal {
        _call(token, abi.encodeCall(IERC20Minimal(token).transfer, (to, amount)));
    }

    /// @dev Tolerates no-return tokens; `false` or revert fails closed.
    function _call(address token, bytes memory data) internal {
        (bool ok, bytes memory ret) = token.call(data);
        if (!ok || (ret.length != 0 && !abi.decode(ret, (bool)))) revert TransferFailed();
    }
}
