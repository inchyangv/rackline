// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import { GpuTypes } from "./types/GpuTypes.sol";
import { IDebtLedger } from "./interfaces/IDebtLedger.sol";
import { IProtocolRoles } from "./interfaces/IProtocolRoles.sol";
import { InterestMath } from "./libraries/InterestMath.sol";

/**
 * @title DebtLedger
 * @notice The single facility ledger (GPU-033; docs/gpu/accounting.md §1–§3). Principal, fees and the exact
 *         interest numerator per facility; forward-only rate segments; waterfall allocation. The manager, router
 *         and vault read this ledger and never keep or recompute their own interest (AR-01/02/03/04 corrected).
 * @dev  - Interest: simple, on principal only, ACT/365, `accum += principal × rateBps × seconds` (exact); units =
 *         floor(accum / DENOM). Accrual frequency does not change the result (AC-03).
 *       - A rate change accrues at the old rate up to `block.timestamp` first and starts a new segment; the past is
 *         never re-priced (AC-02, AR-04).
 *       - Capitalization is disabled unless the facility terms say otherwise; a draw adds only the new amount to
 *         principal (AC-04, AR-03). `capitalize` reverts `CapitalizationDisabled` otherwise.
 *       - `allocate(received)`: fees → unpaid interest → principal → excess. Excess is returned to the caller for
 *         refund bookkeeping; it is never applied to another facility (AC-06). Only actual destination cash that the
 *         writer already holds may be allocated (R2-D07) — this ledger has no dependency on evidence.
 *       - `freezeAccrual` (write-off / non-accrual) stops interest but never forgives debt (AC-08).
 *       - Writers are contracts allow-listed by the protocol ADMIN (manager / router). Views are public.
 *       - `reservedDraws` in the view is 0: reservations belong to the exposure controller (GPU-035).
 */
contract DebtLedger is IDebtLedger {
    using InterestMath for uint256;

    bytes32 public constant ADMIN_ROLE = keccak256("ADMIN");

    IProtocolRoles public immutable ROLES;

    struct RateSegment {
        uint64 start;
        uint32 rateBps;
    }

    struct Facility {
        bool exists;
        bool frozen;
        GpuTypes.FacilityState state;
        Terms terms;
        uint256 principal;
        uint256 fees;
        uint256 interestAccum; // exact numerator, see InterestMath
        uint64 lastAccrualAt;
        uint32 rateBps; // current segment rate
        RateSegment[] segments;
    }

    mapping(GpuTypes.FacilityId => Facility) private _facilities;
    GpuTypes.FacilityId[] private _ids;
    mapping(address => bool) public isWriter;

    event WriterSet(address indexed writer, bool enabled);
    event StateSet(GpuTypes.FacilityId indexed facilityId, GpuTypes.FacilityState state);

    error NotAdmin(address caller);
    error InvalidTerms(string reason);

    constructor(IProtocolRoles roles) {
        ROLES = roles;
    }

    modifier onlyAdmin() {
        if (!ROLES.hasRole(ADMIN_ROLE, msg.sender)) revert NotAdmin(msg.sender);
        _;
    }

    modifier onlyWriter() {
        if (!isWriter[msg.sender]) revert NotLedgerWriter(msg.sender);
        _;
    }

    modifier exists(GpuTypes.FacilityId facilityId) {
        if (!_facilities[facilityId].exists) revert FacilityUnknown(facilityId);
        _;
    }

    // ------------------------------------------------------------------ admin

    function setWriter(address writer, bool enabled) external onlyAdmin {
        isWriter[writer] = enabled;
        emit WriterSet(writer, enabled);
    }

    // ------------------------------------------------------------------ writer operations

    function open(GpuTypes.FacilityId facilityId, Terms calldata t) external override onlyWriter {
        Facility storage f = _facilities[facilityId];
        if (f.exists) revert FacilityExists(facilityId);
        if (t.termsVersionId == bytes32(0) || t.policyVersionId == bytes32(0)) revert InvalidTerms("version ids");
        if (t.loanAsset.chainId == 0) revert InvalidTerms("loan asset");
        if (t.maturityAt != 0 && t.maturityAt <= block.timestamp) revert InvalidTerms("maturity");
        f.exists = true;
        f.state = GpuTypes.FacilityState.ACTIVE;
        f.terms = t;
        f.rateBps = t.rateBps;
        f.lastAccrualAt = uint64(block.timestamp);
        f.segments.push(RateSegment({ start: uint64(block.timestamp), rateBps: t.rateBps }));
        _ids.push(facilityId);
        emit FacilityOpened(facilityId, t.termsVersionId, t.rateBps, uint64(block.timestamp));
        emit RateSegmentAdded(facilityId, uint64(block.timestamp), t.rateBps);
    }

    function setState(GpuTypes.FacilityId facilityId, GpuTypes.FacilityState state)
        external
        onlyWriter
        exists(facilityId)
    {
        _facilities[facilityId].state = state;
        emit StateSet(facilityId, state);
    }

    function accrue(GpuTypes.FacilityId facilityId) external override onlyWriter exists(facilityId) {
        _accrue(_facilities[facilityId], facilityId);
    }

    /// @notice Forward-only: settles the elapsed period at the old rate, then starts a segment at `now`.
    function setRate(GpuTypes.FacilityId facilityId, uint32 rateBps) external override onlyWriter exists(facilityId) {
        Facility storage f = _facilities[facilityId];
        _accrue(f, facilityId);
        uint64 nowTs = uint64(block.timestamp);
        RateSegment storage last = f.segments[f.segments.length - 1];
        if (last.start == nowTs) {
            last.rateBps = rateBps; // same-second change replaces the empty segment (matches the reference model)
        } else {
            f.segments.push(RateSegment({ start: nowTs, rateBps: rateBps }));
        }
        f.rateBps = rateBps;
        emit RateSegmentAdded(facilityId, nowTs, rateBps);
    }

    function recordDraw(GpuTypes.FacilityId facilityId, uint256 amount)
        external
        override
        onlyWriter
        exists(facilityId)
    {
        if (amount == 0) revert ZeroAmount();
        Facility storage f = _facilities[facilityId];
        if (f.frozen) revert AccrualFrozenError(facilityId);
        _accrue(f, facilityId);
        uint256 newPrincipal = f.principal + amount;
        if (newPrincipal > InterestMath.MAX_PRINCIPAL) revert InterestMath.PrincipalTooLarge(newPrincipal);
        f.principal = newPrincipal;
        emit Drawn(facilityId, amount, newPrincipal);
    }

    function recordFee(GpuTypes.FacilityId facilityId, uint256 amount, bytes32 reason)
        external
        override
        onlyWriter
        exists(facilityId)
    {
        if (amount == 0) revert ZeroAmount();
        Facility storage f = _facilities[facilityId];
        _accrue(f, facilityId);
        f.fees += amount;
        emit FeeCharged(facilityId, amount, reason);
    }

    function allocate(GpuTypes.FacilityId facilityId, uint256 received)
        external
        override
        onlyWriter
        exists(facilityId)
        returns (GpuTypes.RepayResult memory r)
    {
        if (received == 0) revert ZeroAmount();
        Facility storage f = _facilities[facilityId];
        _accrue(f, facilityId);
        uint256 remaining = received;

        uint256 feePaid = remaining < f.fees ? remaining : f.fees;
        f.fees -= feePaid;
        remaining -= feePaid;

        uint256 unpaid = f.interestAccum.units();
        uint256 interestPaid = remaining < unpaid ? remaining : unpaid;
        f.interestAccum -= InterestMath.toAccum(interestPaid); // exact: the fractional remainder survives
        remaining -= interestPaid;

        uint256 principalPaid = remaining < f.principal ? remaining : f.principal;
        f.principal -= principalPaid;
        remaining -= principalPaid;

        r = GpuTypes.RepayResult({
            requested: received,
            received: received,
            applied: received - remaining,
            feePaid: feePaid,
            interestPaid: interestPaid,
            principalPaid: principalPaid,
            excess: remaining,
            newDebt: _legalDebt(f)
        });
        emit Allocated(facilityId, feePaid, interestPaid, principalPaid, remaining, r.newDebt);
    }

    function freezeAccrual(GpuTypes.FacilityId facilityId) external override onlyWriter exists(facilityId) {
        Facility storage f = _facilities[facilityId];
        _accrue(f, facilityId);
        f.frozen = true;
        emit AccrualFrozen(facilityId, uint64(block.timestamp));
    }

    function capitalize(GpuTypes.FacilityId facilityId) external override onlyWriter exists(facilityId) {
        Facility storage f = _facilities[facilityId];
        if (!f.terms.capitalizeUnpaidInterest) revert CapitalizationDisabled();
        if (f.frozen) revert AccrualFrozenError(facilityId);
        _accrue(f, facilityId);
        uint256 unpaid = f.interestAccum.units();
        if (unpaid == 0) return;
        f.interestAccum -= InterestMath.toAccum(unpaid);
        uint256 newPrincipal = f.principal + unpaid;
        if (newPrincipal > InterestMath.MAX_PRINCIPAL) revert InterestMath.PrincipalTooLarge(newPrincipal);
        f.principal = newPrincipal;
        emit Capitalized(facilityId, unpaid, newPrincipal);
    }

    // ------------------------------------------------------------------ views

    function terms(GpuTypes.FacilityId facilityId) external view override exists(facilityId) returns (Terms memory) {
        return _facilities[facilityId].terms;
    }

    function view_(GpuTypes.FacilityId facilityId)
        external
        view
        override
        exists(facilityId)
        returns (GpuTypes.FacilityLedgerView memory v)
    {
        Facility storage f = _facilities[facilityId];
        v = GpuTypes.FacilityLedgerView({
            state: f.state,
            loanAsset: f.terms.loanAsset,
            principal: f.principal,
            unpaidInterest: _unpaidInterestAt(f, uint64(block.timestamp)),
            fees: f.fees,
            reservedDraws: 0,
            rateBps: f.rateBps,
            lastAccrualAt: f.lastAccrualAt,
            maturityAt: f.terms.maturityAt,
            termsVersionId: f.terms.termsVersionId,
            policyVersionId: f.terms.policyVersionId,
            executionProfile: f.terms.executionProfile
        });
    }

    /// @notice Unpaid interest as of `at` including accrued-but-unrecorded interest (pending accrual at the current
    ///         rate). For `at` before the last accrual the recorded value is returned (no un-accrual).
    function unpaidInterestAt(GpuTypes.FacilityId facilityId, uint64 at)
        public
        view
        override
        exists(facilityId)
        returns (uint256)
    {
        return _unpaidInterestAt(_facilities[facilityId], at);
    }

    function legalDebtAt(GpuTypes.FacilityId facilityId, uint64 at)
        public
        view
        override
        exists(facilityId)
        returns (uint256)
    {
        Facility storage f = _facilities[facilityId];
        return f.principal + f.fees + _unpaidInterestAt(f, at);
    }

    function totalLegalDebtAt(uint64 at) external view override returns (uint256 total) {
        for (uint256 i = 0; i < _ids.length; i++) {
            Facility storage f = _facilities[_ids[i]];
            total += f.principal + f.fees + _unpaidInterestAt(f, at);
        }
    }

    function facilityCount() external view returns (uint256) {
        return _ids.length;
    }

    function facilityAt(uint256 index) external view returns (GpuTypes.FacilityId) {
        return _ids[index];
    }

    function isFrozen(GpuTypes.FacilityId facilityId) external view exists(facilityId) returns (bool) {
        return _facilities[facilityId].frozen;
    }

    function interestAccumulator(GpuTypes.FacilityId facilityId) external view exists(facilityId) returns (uint256) {
        return _facilities[facilityId].interestAccum;
    }

    function rateSegments(GpuTypes.FacilityId facilityId)
        external
        view
        exists(facilityId)
        returns (RateSegment[] memory)
    {
        return _facilities[facilityId].segments;
    }

    // ------------------------------------------------------------------ internals

    /// @dev Because every rate change accrues first, the pending period [lastAccrualAt, now) is always at the
    ///      current segment rate; earlier segments are already settled in `interestAccum`.
    function _accrue(Facility storage f, GpuTypes.FacilityId facilityId) internal {
        uint64 nowTs = uint64(block.timestamp);
        if (nowTs < f.lastAccrualAt) revert AccrualBackwards(f.lastAccrualAt, nowTs);
        if (nowTs == f.lastAccrualAt) return;
        uint64 from = f.lastAccrualAt;
        if (!f.frozen && f.principal != 0) {
            uint256 before = f.interestAccum.units();
            f.interestAccum += InterestMath.growth(f.principal, f.rateBps, nowTs - from);
            emit Accrued(facilityId, f.interestAccum.units() - before, from, nowTs, f.rateBps);
        }
        f.lastAccrualAt = nowTs;
    }

    function _unpaidInterestAt(Facility storage f, uint64 at) internal view returns (uint256) {
        if (f.frozen || at <= f.lastAccrualAt || f.principal == 0) return f.interestAccum.units();
        return (f.interestAccum + InterestMath.growth(f.principal, f.rateBps, at - f.lastAccrualAt)).units();
    }

    function _legalDebt(Facility storage f) internal view returns (uint256) {
        return f.principal + f.fees + f.interestAccum.units();
    }
}
