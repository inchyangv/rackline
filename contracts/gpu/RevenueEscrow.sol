// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import { GpuTypes } from "./types/GpuTypes.sol";
import { IRevenueEscrow } from "./interfaces/IRevenueEscrow.sol";
import { IControlRegistry } from "./interfaces/IControlRegistry.sol";
import { ControlRegistry } from "./ControlRegistry.sol";
import { IProtocolRoles } from "./interfaces/IProtocolRoles.sol";
import { ISourceEscrow } from "./source/ISourceEscrow.sol";

interface IERC20Min {
    function balanceOf(address) external view returns (uint256);
    function transfer(address, uint256) external returns (bool);
    function approve(address, uint256) external returns (bool);
}

/// @dev The subset of SourceEscrow (GPU-077) this controlled account drives as its OWNER / registered PAYER.
interface ISourceEscrowOwner is ISourceEscrow {
    function owner() external view returns (address);
    function settlementSeq() external view returns (uint64);
    function withdraw(address token, address to, uint256 amount) external;
    function transferOwnership(address newOwner) external;
    function settle(bytes32 accountKey, bytes32 obligationRef, address token, uint256 amount, bytes32 settlementId)
        external
        returns (uint64 seq, uint256 measured);
}

/**
 * @title RevenueEscrow
 * @notice Controlled account for ONE control agreement (GPU-037): it owns the account's `SourceEscrow` (GPU-077),
 *         sweeps only payouts that the SourceEscrow classified as provider settlements, and distributes them through
 *         a fixed waterfall — operating allowance → borrower-owned reserve → debt sweep to the settlement leg (by
 *         facility seniority) → residual to the borrower. It is leg 1→2 of the settlement path
 *         (docs/gpu/decisions/settlement-rails.md §3): funds handed to the settlement leg carry a `settlementId`;
 *         **debt is never changed here** (R2-D07 / SR-D03) — there is no ledger call in this contract.
 * @dev Composition with GPU-077: this contract is the `owner` of the SourceEscrow (so it can `withdraw`) and may be
 *      a registered payer (to forward upstream claim proceeds through the same measured path). It reads only
 *      SourceEscrow's classified state (`payout(seq)`, `unattributedBalance`); it never re-reports a balance, and
 *      there is no `notify(amount)` anywhere in the pair. SourceEscrow.withdraw books an outflow against the
 *      unattributed bucket first (GPU-077 quirk); this contract shadows that so unattributed refunds stay exact.
 *      Control binding: sweeps require `CONTROL.requireUsable(agreementId, version, E2)`. In LOCAL tests CONTROL is the
 *      real ControlRegistry; on a real source chain it must be a role-maintained mirror of the Creditcoin registry
 *      (GPU-038/040) — a mirror is configuration, never E2 evidence (R2-D09: no Writability/cross-chain call).
 *      Authority limits: no generic `execute`, no `approve`, no module swap. Waterfall/claim allowlists are immutable
 *      per registry version and can only be (re)declared for the registry's *current* version, so a mid-agreement
 *      change requires a new reviewed version in the registry. Claims are exact (target, selector) with the recipient
 *      argument forced to this escrow; a successful claim is an upstream action, never control evidence.
 *      Priority rule: facilities are served in array order (seniority), each up to its asserted `target`.
 *      Rounding: beneficiaries floor; the remainder is residual (borrower-owned).
 *      Release: only after the ControlRegistry reports the agreement released and this escrow has no pending refund
 *      flag and no unswept classified payout; reserve/residual/claim buckets and SourceEscrow ownership go back to
 *      the borrower wallet. `debt == 0` alone never releases (that gate lives in the registry with servicer approval).
 */
contract RevenueEscrow is IRevenueEscrow {
    IProtocolRoles public immutable ROLES;
    ControlRegistry public immutable CONTROL;
    ISourceEscrowOwner public immutable SOURCE;
    bytes32 public immutable AGREEMENT_ID;
    bytes32 private immutable _ACCOUNT_KEY;

    struct StoredWaterfall {
        bool exists;
        address token;
        uint16 operatingBps;
        uint256 operatingCapPerSweep;
        address operatingRecipient;
        uint256 reserveTarget;
        address settlementLeg;
        address residualRecipient;
        FacilityAllocation[] facilities;
        ClaimTarget[] claimTargets;
    }

    mapping(uint32 version => StoredWaterfall) private _waterfalls;
    mapping(uint64 payoutSeq => bool) public isSwept;
    mapping(GpuTypes.FacilityId => uint256) public sweptToFacility; // cumulative across versions
    mapping(address token => uint256) public reserveBalance; // borrower-owned reserve held here
    mapping(address token => uint256) public claimedBalance; // upstream claim proceeds, unclassified until forwarded
    mapping(address token => uint256) private _unattributedShadow; // unattributed bookkeeping consumed by withdraws
    uint64 public sweepCount;
    bool private _released;
    bool public refundPending;
    uint256 private _lock = 1;

    constructor(IProtocolRoles roles, ControlRegistry control, ISourceEscrowOwner source, bytes32 agreementId) {
        ROLES = roles;
        CONTROL = control;
        SOURCE = source;
        AGREEMENT_ID = agreementId;
        IControlRegistry.Agreement memory a = control.agreement(agreementId);
        _ACCOUNT_KEY = GpuTypes.AccountKey.unwrap(a.accountKey);
    }

    // ------------------------------------------------------------------ modifiers

    modifier onlyRole(bytes32 role) {
        if (!ROLES.hasRole(role, msg.sender)) revert NotRole(role, msg.sender);
        _;
    }

    modifier nonReentrant() {
        if (_lock != 1) revert Reentrancy();
        _lock = 2;
        _;
        _lock = 1;
    }

    modifier notReleased() {
        if (_released) revert AlreadyReleased();
        _;
    }

    // ------------------------------------------------------------------ IRevenueEscrow views

    function accountKey() external view override returns (bytes32) {
        return _ACCOUNT_KEY;
    }

    function settlementSeq() external view override returns (uint64) {
        return sweepCount;
    }

    /// @notice The controller of the account is this contract (it owns the SourceEscrow); roles act through it.
    function controller() external view override returns (address) {
        return address(this);
    }

    function isReleased() external view override returns (bool) {
        return _released;
    }

    function waterfall(uint32 version) external view returns (Waterfall memory w) {
        StoredWaterfall storage s = _waterfalls[version];
        if (!s.exists) revert NoWaterfall(version);
        w = Waterfall({
            version: version,
            token: s.token,
            operatingBps: s.operatingBps,
            operatingCapPerSweep: s.operatingCapPerSweep,
            operatingRecipient: s.operatingRecipient,
            reserveTarget: s.reserveTarget,
            settlementLeg: s.settlementLeg,
            residualRecipient: s.residualRecipient,
            facilities: s.facilities,
            claimTargets: s.claimTargets
        });
    }

    function currentVersion() public view returns (uint32) {
        return CONTROL.agreement(AGREEMENT_ID).version;
    }

    /// @notice Unattributed (donation / self-transfer / unknown) funds still refundable, exact despite withdraws.
    function refundableUnattributed(address token) public view returns (uint256) {
        return SOURCE.unattributedBalance(token) + _unattributedShadow[token];
    }

    /// @notice Canonical settlement id of a debt-sweep leg (links leg 2/3 to the destination receipt, SR-D08).
    function settlementIdOf(uint64 payoutSeq, uint32 version, GpuTypes.FacilityId facilityId)
        public
        view
        returns (bytes32)
    {
        return keccak256(abi.encode(AGREEMENT_ID, version, payoutSeq, facilityId));
    }

    // ------------------------------------------------------------------ waterfall (UNDERWRITER, current version only)

    /// @notice Declare the waterfall for the registry's current agreement version. Immutable once set: a change in
    ///         beneficiaries/allowlists needs a new reviewed version in the ControlRegistry (no mid-agreement edits).
    function setWaterfall(Waterfall calldata w) external onlyRole(ROLES.UNDERWRITER()) notReleased {
        uint32 v = currentVersion();
        if (w.version != v) revert WaterfallVersionMismatch(v, w.version);
        StoredWaterfall storage s = _waterfalls[v];
        if (s.exists) revert WaterfallExists(v);
        if (w.token == address(0) || w.settlementLeg == address(0) || w.residualRecipient == address(0)) {
            revert InvalidWaterfall("zero address");
        }
        if (w.operatingBps > 10_000) revert InvalidWaterfall("operatingBps");
        if (w.operatingBps != 0 && w.operatingRecipient == address(0)) revert InvalidWaterfall("operating recipient");
        if (w.settlementLeg == address(this) || w.residualRecipient == address(this)) {
            revert InvalidWaterfall("self recipient");
        }
        s.exists = true;
        s.token = w.token;
        s.operatingBps = w.operatingBps;
        s.operatingCapPerSweep = w.operatingCapPerSweep;
        s.operatingRecipient = w.operatingRecipient;
        s.reserveTarget = w.reserveTarget;
        s.settlementLeg = w.settlementLeg;
        s.residualRecipient = w.residualRecipient;
        for (uint256 i = 0; i < w.facilities.length; i++) {
            for (uint256 j = 0; j < i; j++) {
                if (
                    GpuTypes.FacilityId.unwrap(w.facilities[j].facilityId)
                        == GpuTypes.FacilityId.unwrap(w.facilities[i].facilityId)
                ) revert InvalidWaterfall("duplicate facility");
            }
            s.facilities.push(w.facilities[i]);
        }
        for (uint256 i = 0; i < w.claimTargets.length; i++) {
            if (w.claimTargets[i].target == address(0) || w.claimTargets[i].target == w.token) {
                revert InvalidWaterfall("claim target");
            }
            s.claimTargets.push(w.claimTargets[i]);
        }
        emit WaterfallSet(AGREEMENT_ID, v, w.token, w.settlementLeg);
    }

    // ------------------------------------------------------------------ sweep (SERVICER)

    /**
     * @notice Sweep one SourceEscrow-classified payout through the waterfall of the current, usable (E2) agreement
     *         version. Idempotent per `payoutSeq`; unattributed / cancelled / foreign-account payouts are refused.
     */
    function sweep(uint64 payoutSeq) external onlyRole(ROLES.SERVICER()) notReleased nonReentrant {
        if (isSwept[payoutSeq]) revert AlreadySwept(payoutSeq);
        ISourceEscrow.Payout memory p = SOURCE.payout(payoutSeq);
        if (p.payer == address(0)) revert PayoutNotSweepable(payoutSeq, "unknown");
        if (p.cancelled) revert PayoutNotSweepable(payoutSeq, "cancelled");
        if (p.accountKey != _ACCOUNT_KEY) revert PayoutNotSweepable(payoutSeq, "other account");
        uint32 v = currentVersion();
        StoredWaterfall storage w = _waterfalls[v];
        if (!w.exists) revert NoWaterfall(v);
        if (p.token != w.token) revert PayoutNotSweepable(payoutSeq, "token");
        // control gate: current version effective, grade >= E2, observation fresh (fail closed in the registry)
        CONTROL.requireUsable(AGREEMENT_ID, v, GpuTypes.ControlGrade.E2);
        isSwept[payoutSeq] = true;

        uint256 amount = _pullFromSource(w.token, p.amount);
        (uint256 operating, uint256 reserve, uint256 debt, uint256 residual) = _distribute(w, v, payoutSeq, amount);
        sweepCount++;
        emit PayoutSwept(payoutSeq, v, amount, operating, reserve, debt, residual);
        emit Swept(_ACCOUNT_KEY, w.token, debt, operating, payoutSeq);
    }

    function _distribute(StoredWaterfall storage w, uint32 v, uint64 payoutSeq, uint256 amount)
        internal
        returns (uint256 operating, uint256 reserve, uint256 debt, uint256 residual)
    {
        uint256 remaining = amount;
        // 1. operating allowance (floor, capped per sweep)
        operating = (remaining * w.operatingBps) / 10_000;
        if (operating > w.operatingCapPerSweep) operating = w.operatingCapPerSweep;
        if (operating > 0) {
            remaining -= operating;
            _push(w.token, w.operatingRecipient, operating);
        }
        // 2. borrower-owned reserve up to target (held here, never LP cash)
        uint256 held = reserveBalance[w.token];
        if (held < w.reserveTarget) {
            reserve = w.reserveTarget - held;
            if (reserve > remaining) reserve = remaining;
            reserveBalance[w.token] = held + reserve;
            remaining -= reserve;
        }
        // 3. debt sweep to the settlement leg by facility seniority, each up to its asserted target
        (debt, remaining) = _sweepDebt(w, v, payoutSeq, remaining);
        // 4. residual (incl. rounding remainder) to the borrower
        residual = remaining;
        if (residual > 0) _push(w.token, w.residualRecipient, residual);
    }

    function _sweepDebt(StoredWaterfall storage w, uint32 v, uint64 payoutSeq, uint256 remaining)
        internal
        returns (uint256 debt, uint256 left)
    {
        for (uint256 i = 0; i < w.facilities.length && remaining > 0; i++) {
            FacilityAllocation storage f = w.facilities[i];
            uint256 already = sweptToFacility[f.facilityId];
            if (already >= f.target) continue;
            uint256 take = f.target - already;
            if (take > remaining) take = remaining;
            sweptToFacility[f.facilityId] = already + take;
            remaining -= take;
            debt += take;
            _push(w.token, w.settlementLeg, take);
            emit SweptToSettlement(f.facilityId, settlementIdOf(payoutSeq, v, f.facilityId), payoutSeq, take);
        }
        left = remaining;
    }

    // ------------------------------------------------------------------ restricted upstream claim (SERVICER)

    /**
     * @notice Execute an allow-listed upstream claim whose recipient argument is this escrow. Proceeds land in
     *         `claimedBalance` (unclassified) and can only enter the waterfall after `forwardClaimed` puts them
     *         through the SourceEscrow's measured settlement path. Success here says nothing about control grade.
     */
    function claim(address target, bytes calldata data)
        external
        onlyRole(ROLES.SERVICER())
        notReleased
        nonReentrant
        returns (uint256 measured)
    {
        address token = _checkClaim(target, data);
        uint256 before = IERC20Min(token).balanceOf(address(this));
        (bool ok, bytes memory ret) = target.call(data);
        if (!ok) revert ClaimFailed(ret);
        uint256 after_ = IERC20Min(token).balanceOf(address(this));
        measured = after_ > before ? after_ - before : 0;
        claimedBalance[token] += measured;
        emit ClaimExecuted(target, bytes4(data[:4]), measured);
    }

    /// @dev Allow-list (target, selector) of the current version and force the recipient argument to this escrow.
    function _checkClaim(address target, bytes calldata data) internal view returns (address token) {
        uint32 v = currentVersion();
        StoredWaterfall storage w = _waterfalls[v];
        if (!w.exists) revert NoWaterfall(v);
        if (data.length < 4) revert ClaimNotAllowed(target, bytes4(0));
        bytes4 sel = bytes4(data[:4]);
        uint256 recipientIdx = type(uint256).max;
        for (uint256 i = 0; i < w.claimTargets.length; i++) {
            if (w.claimTargets[i].target == target && w.claimTargets[i].selector == sel) {
                recipientIdx = w.claimTargets[i].recipientArgIndex;
                break;
            }
        }
        if (recipientIdx == type(uint256).max) revert ClaimNotAllowed(target, sel);
        uint256 off = 4 + 32 * recipientIdx;
        if (data.length < off + 32) revert ClaimRecipientMismatch(address(this), address(0));
        address recipient = address(uint160(uint256(bytes32(data[off:off + 32]))));
        if (recipient != address(this)) revert ClaimRecipientMismatch(address(this), recipient);
        token = w.token;
    }

    /// @notice Forward claim proceeds into the SourceEscrow as a registered payer settlement (measured there).
    function forwardClaimed(bytes32 obligationRef, uint256 amount, bytes32 settlementId)
        external
        onlyRole(ROLES.SERVICER())
        notReleased
        nonReentrant
    {
        uint32 v = currentVersion();
        StoredWaterfall storage w = _waterfalls[v];
        if (!w.exists) revert NoWaterfall(v);
        if (amount == 0 || amount > claimedBalance[w.token]) revert InvalidWaterfall("claimed amount");
        claimedBalance[w.token] -= amount;
        _callToken(w.token, abi.encodeCall(IERC20Min.approve, (address(SOURCE), amount)));
        SOURCE.settle(_ACCOUNT_KEY, obligationRef, w.token, amount, settlementId);
        emit ClaimForwarded(obligationRef, settlementId, amount);
    }

    // ------------------------------------------------------------------ unattributed refunds (TREASURY)

    /// @notice Refund unattributed (donation / self-transfer / unknown) funds. Never enters the waterfall.
    function refundUnattributed(address token, address to, uint256 amount)
        external
        onlyRole(ROLES.TREASURY())
        nonReentrant
    {
        if (amount == 0 || amount > refundableUnattributed(token)) {
            revert InvalidWaterfall("unattributed amount");
        }
        uint256 shadow = _unattributedShadow[token];
        uint256 fromShadow = amount <= shadow ? amount : shadow;
        _unattributedShadow[token] = shadow - fromShadow;
        uint256 before = SOURCE.unattributedBalance(token);
        SOURCE.withdraw(token, to, amount);
        uint256 after_ = SOURCE.unattributedBalance(token);
        // withdraw consumed min(amount, bucket) from the bucket; whatever it did not consume is shadow we already cut
        uint256 consumed = before - after_;
        if (consumed + fromShadow < amount) _unattributedShadow[token] += amount - consumed - fromShadow;
        emit UnattributedRefunded(token, to, amount);
    }

    // ------------------------------------------------------------------ refund flag / release

    function setRefundPending(bool pending, string calldata reason) external onlyRole(ROLES.SERVICER()) notReleased {
        refundPending = pending;
        emit RefundPendingSet(pending, reason);
    }

    /**
     * @notice Return residual rights after the ControlRegistry released the agreement. Blocked while a refund is
     *         pending or a classified payout is still unswept. Debt == 0 alone never gets here (registry gate).
     */
    function release(address token, address returnTo) external onlyRole(ROLES.TREASURY()) notReleased nonReentrant {
        if (!_registryReleased()) revert ReleaseBlocked("control registry has not released the agreement");
        if (refundPending) revert ReleaseBlocked("refund pending");
        if (_hasUnsweptPayout(token)) revert ReleaseBlocked("unswept classified payout");
        if (returnTo == address(0) || returnTo != SOURCE.borrowerWalletOf(_ACCOUNT_KEY)) {
            revert ReleaseBlocked("return address is not the borrower wallet");
        }
        _released = true;
        uint256 reserve = reserveBalance[token];
        reserveBalance[token] = 0;
        uint256 claimed = claimedBalance[token];
        claimedBalance[token] = 0;
        uint256 total = reserve + claimed;
        if (total > 0) _push(token, returnTo, total);
        SOURCE.transferOwnership(returnTo);
        emit Released(_ACCOUNT_KEY, returnTo, uint64(block.timestamp));
    }

    function _registryReleased() internal view returns (bool) {
        return CONTROL.status(AGREEMENT_ID).released;
    }

    function _hasUnsweptPayout(address token) internal view returns (bool) {
        uint64 last = SOURCE.settlementSeq();
        for (uint64 s = 1; s <= last; s++) {
            if (isSwept[s]) continue;
            ISourceEscrow.Payout memory p = SOURCE.payout(s);
            if (p.accountKey == _ACCOUNT_KEY && !p.cancelled && p.token == token) return true;
        }
        return false;
    }

    // ------------------------------------------------------------------ internals

    /// @dev Withdraw a classified payout from the SourceEscrow and verify the measured delta (fee-on-transfer on the
    ///      sweep leg is refused). Shadow the unattributed bookkeeping the SourceEscrow consumed.
    function _pullFromSource(address token, uint256 amount) internal returns (uint256) {
        uint256 unattrBefore = SOURCE.unattributedBalance(token);
        uint256 before = IERC20Min(token).balanceOf(address(this));
        SOURCE.withdraw(token, address(this), amount);
        uint256 measured = IERC20Min(token).balanceOf(address(this)) - before;
        if (measured != amount) revert MeasuredDeltaMismatch(amount, measured);
        uint256 consumed = unattrBefore - SOURCE.unattributedBalance(token);
        if (consumed > 0) _unattributedShadow[token] += consumed;
        return measured;
    }

    function _push(address token, address to, uint256 amount) internal {
        _callToken(token, abi.encodeCall(IERC20Min.transfer, (to, amount)));
    }

    function _callToken(address token, bytes memory data) internal {
        (bool ok, bytes memory ret) = token.call(data);
        if (!ok || (ret.length != 0 && !abi.decode(ret, (bool)))) revert TransferFailed();
    }
}
