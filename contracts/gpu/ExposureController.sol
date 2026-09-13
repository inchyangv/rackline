// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import { GpuTypes } from "./types/GpuTypes.sol";
import { IExposureController, IVaultCashView } from "./interfaces/IExposureController.sol";
import { IReceivableBook } from "./interfaces/IReceivableBook.sol";
import { IDebtLedger } from "./interfaces/IDebtLedger.sol";
import { IControlRegistry } from "./interfaces/IControlRegistry.sol";
import { IProtocolRoles } from "./interfaces/IProtocolRoles.sol";
import { IRiskPolicy } from "./interfaces/IRiskPolicy.sol";
import { GpuRiskPolicy } from "./GpuRiskPolicy.sol";

/**
 * @title ExposureController
 * @notice Borrowing base × policy × concentration × reservations (GPU-035.b). Reads the authoritative ledger for
 *         debt (interest included), the ReceivableBook for the proven eligible base, the ControlRegistry for E2
 *         validity and the vault for cash; it never recomputes interest and never creates limits from evidence
 *         that did not pass the native path.
 * @dev  Roles: UNDERWRITER enrolls facilities and sets authorizations; MANAGER (allow-listed by ADMIN, the
 *       CreditFacilityManager of GPU-036) reserves/consumes/cancels; anyone may expire a past-expiry reservation
 *       on-chain. `consumeReservation` calls `IDebtLedger.recordDraw` itself (this contract is a ledger writer), so
 *       reserved ↓ and debt ↑ happen atomically. Impairment / NAV write-off lives in the vault and is not coupled
 * to
 *       exposure here (docs/gpu/accounting.md: exposure keeps the legal debt until a policy decision).
 */
contract ExposureController is IExposureController {
    bytes32 public constant ADMIN_ROLE = keccak256("ADMIN");

    IProtocolRoles public immutable ROLES;
    IReceivableBook public immutable BOOK;
    IDebtLedger public immutable LEDGER;
    IControlRegistry public immutable CONTROL;
    GpuRiskPolicy public immutable POLICY;
    IVaultCashView public immutable VAULT;

    struct Enrollment {
        bytes32 borrowerId;
        bytes32 groupId;
        GpuTypes.ProviderId providerId;
        bool exists;
    }

    mapping(GpuTypes.FacilityId => Enrollment) private _enrolled;
    mapping(bytes32 borrowerId => GpuTypes.FacilityId[]) private _byBorrower;
    mapping(bytes32 groupId => GpuTypes.FacilityId[]) private _byGroup;
    mapping(GpuTypes.ProviderId => GpuTypes.FacilityId[]) private _byProvider;
    GpuTypes.FacilityId[] private _all;
    mapping(GpuTypes.FacilityId => Authorization) private _auth;
    mapping(GpuTypes.FacilityId => uint256) private _reserved;
    mapping(GpuTypes.FacilityId => mapping(uint64 => bool)) private _nonceUsed;
    mapping(bytes32 => Reservation) private _reservations;
    mapping(address => bool) public isManager;

    event ManagerSet(address indexed manager, bool enabled);

    error NotRole(bytes32 role, address caller);
    error ZeroAddress();

    constructor(
        IProtocolRoles roles,
        IReceivableBook book,
        IDebtLedger ledger,
        IControlRegistry control,
        GpuRiskPolicy policy,
        IVaultCashView vault
    ) {
        if (
            address(roles) == address(0) || address(book) == address(0) || address(ledger) == address(0)
                || address(control) == address(0) || address(policy) == address(0) || address(vault) == address(0)
        ) revert ZeroAddress();
        ROLES = roles;
        BOOK = book;
        LEDGER = ledger;
        CONTROL = control;
        POLICY = policy;
        VAULT = vault;
    }

    modifier onlyRole(bytes32 role) {
        if (!ROLES.hasRole(role, msg.sender)) revert NotRole(role, msg.sender);
        _;
    }

    modifier onlyManager() {
        if (!isManager[msg.sender]) revert NotManager(msg.sender);
        _;
    }

    // ------------------------------------------------------------------ wiring / authority

    function setManager(address manager, bool enabled) external onlyRole(ADMIN_ROLE) {
        if (manager == address(0)) revert ZeroAddress();
        isManager[manager] = enabled;
        emit ManagerSet(manager, enabled);
    }

    /// @notice Enroll a facility in its concentration categories. Requires the ReceivableBook binding and an opened
    ///         ledger facility; the pilot only supports 1:1 stablecoin pairs (equal decimals).
    function enrollFacility(GpuTypes.FacilityId facilityId, bytes32 groupId) external onlyRole(ROLES.UNDERWRITER()) {
        if (_enrolled[facilityId].exists) revert FacilityAlreadyEnrolled(facilityId);
        IReceivableBook.Facility memory f = BOOK.facility(facilityId);
        if (!f.exists) revert IReceivableBook.FacilityUnknown(facilityId);
        IDebtLedger.Terms memory t = LEDGER.terms(facilityId); // reverts when the ledger facility is not open
        if (t.loanAsset.decimals != f.sourceAsset.decimals) revert PilotValuationUnsupported("decimals differ");
        if (groupId == bytes32(0)) groupId = f.borrowerId;
        _enrolled[facilityId] =
            Enrollment({ borrowerId: f.borrowerId, groupId: groupId, providerId: f.providerId, exists: true });
        _byBorrower[f.borrowerId].push(facilityId);
        _byGroup[groupId].push(facilityId);
        _byProvider[f.providerId].push(facilityId);
        _all.push(facilityId);
        emit FacilityEnrolled(facilityId, f.borrowerId, groupId);
    }

    /// @notice Pin the underwriting decision: limit, current policy version, effective control agreement version
    ///         and decision expiry. Every call bumps the epoch and invalidates reservations of the previous one.
    ///         Lowering the limit never changes recorded debt.
    function setAuthorization(
        GpuTypes.FacilityId facilityId,
        uint256 limit,
        bytes32 policyVersionId,
        bytes32 controlAgreementId,
        uint32 controlVersion,
        uint64 validUntil
    ) external onlyRole(ROLES.UNDERWRITER()) {
        if (!_enrolled[facilityId].exists) revert FacilityNotEnrolled(facilityId);
        if (!POLICY.isCurrent(policyVersionId)) revert PolicyStale(policyVersionId);
        if (!CONTROL.isEffective(controlAgreementId, controlVersion, uint64(block.timestamp))) {
            revert ControlNotUsable(controlAgreementId, controlVersion);
        }
        if (validUntil <= block.timestamp) revert AuthorizationExpired(facilityId, validUntil);
        Authorization storage a = _auth[facilityId];
        a.limit = limit;
        a.policyVersionId = policyVersionId;
        a.controlAgreementId = controlAgreementId;
        a.controlVersion = controlVersion;
        a.validUntil = validUntil;
        a.epoch += 1;
        a.exists = true;
        emit AuthorizationSet(facilityId, limit, policyVersionId, validUntil, a.epoch);
    }

    // ------------------------------------------------------------------ views

    function authorization(GpuTypes.FacilityId facilityId) external view override returns (Authorization memory) {
        return _auth[facilityId];
    }

    function reservation(bytes32 reservationId) external view override returns (Reservation memory) {
        return _reservations[reservationId];
    }

    function reservedOf(GpuTypes.FacilityId facilityId) external view override returns (uint256) {
        return _reserved[facilityId];
    }

    function reservationId(GpuTypes.FacilityId facilityId, uint64 approvalNonce) public pure returns (bytes32) {
        return keccak256(abi.encode(facilityId, approvalNonce));
    }

    function exposureOfBorrower(bytes32 borrowerId, uint64 at) public view override returns (uint256) {
        return _exposure(_byBorrower[borrowerId], at);
    }

    function exposureOfGroup(bytes32 groupId, uint64 at) public view override returns (uint256) {
        return _exposure(_byGroup[groupId], at);
    }

    function exposureOfProvider(GpuTypes.ProviderId providerId, uint64 at) public view override returns (uint256) {
        return _exposure(_byProvider[providerId], at);
    }

    function exposureGlobal(uint64 at) public view override returns (uint256) {
        return _exposure(_all, at);
    }

    /// @notice Headroom = min over the facility's categories of (cap − exposure). Reverts `CapNotSet` on a 0 cap.
    function headroomOf(GpuTypes.FacilityId facilityId, bytes32 policyVersionId, uint64 at)
        public
        view
        returns (uint256 headroom)
    {
        Enrollment storage e = _enrolled[facilityId];
        if (!e.exists) revert FacilityNotEnrolled(facilityId);
        (uint256 cb, uint256 cg, uint256 cp, uint256 cglob) = POLICY.caps(policyVersionId);
        headroom = _room(cb, exposureOfBorrower(e.borrowerId, at));
        headroom = _min(headroom, _room(cg, exposureOfGroup(e.groupId, at)));
        headroom = _min(headroom, _room(cp, exposureOfProvider(e.providerId, at)));
        headroom = _min(headroom, _room(cglob, exposureGlobal(at)));
    }

    function evaluateDraw(GpuTypes.FacilityId facilityId)
        public
        view
        override
        returns (GpuTypes.DrawEvaluation memory e)
    {
        Authorization storage a = _auth[facilityId];
        if (!a.exists) revert NoAuthorization(facilityId);
        uint64 nowTs = uint64(block.timestamp);
        IRiskPolicy.Params memory p = POLICY.params(a.policyVersionId);
        uint256 debt = LEDGER.legalDebtAt(facilityId, nowTs);
        uint256 reserved = _reserved[facilityId];
        uint256 headroom = headroomOf(facilityId, a.policyVersionId, nowTs);
        (uint256 eligible, uint64 validUntil, uint64 cpAge) = BOOK.eligibleUnpaid(
            facilityId, p.checkpointMaxAge, POLICY.checkpointToleranceBps(a.policyVersionId), p.overdueHaircutBps, nowTs
        );
        e = POLICY.evaluate(a.policyVersionId, eligible, a.limit, debt, reserved, headroom, VAULT.availableCash());
        e.evidenceValidUntil = validUntil;
        e.checkpointAge = cpAge;
        if (!_authorityUsable(facilityId, a, p, nowTs)) e.availableDraw = 0;
    }

    // ------------------------------------------------------------------ reservations (MANAGER)

    function reserve(GpuTypes.FacilityId facilityId, uint256 amount, uint64 approvalNonce, uint64 expiresAt)
        external
        override
        onlyManager
        returns (bytes32 id)
    {
        if (amount == 0) revert IDebtLedger.ZeroAmount();
        Authorization storage a = _auth[facilityId];
        if (!a.exists) revert NoAuthorization(facilityId);
        if (a.limit == 0) revert FacilityLimitZero(facilityId);
        uint64 nowTs = uint64(block.timestamp);
        if (a.validUntil <= nowTs) revert AuthorizationExpired(facilityId, a.validUntil);
        if (!POLICY.isCurrent(a.policyVersionId)) revert PolicyStale(a.policyVersionId);
        IRiskPolicy.Params memory p = POLICY.params(a.policyVersionId);
        if (!_controlUsable(a, p, nowTs)) revert ControlNotUsable(a.controlAgreementId, a.controlVersion);
        if (expiresAt <= nowTs) revert ReservationExpired(bytes32(0), expiresAt);
        if (_nonceUsed[facilityId][approvalNonce]) revert NonceUsed(facilityId, approvalNonce);
        GpuTypes.DrawEvaluation memory ev = evaluateDraw(facilityId);
        if (ev.availableDraw < amount) revert InsufficientHeadroom(amount, ev.availableDraw);

        _nonceUsed[facilityId][approvalNonce] = true;
        id = reservationId(facilityId, approvalNonce);
        _reservations[id] = Reservation({
            facilityId: facilityId,
            amount: amount,
            approvalNonce: approvalNonce,
            expiresAt: expiresAt,
            policyVersionId: a.policyVersionId,
            authorizationEpoch: a.epoch,
            state: ReservationState.ACTIVE
        });
        _reserved[facilityId] += amount;
        emit Reserved(id, facilityId, amount, expiresAt);
    }

    /// @notice Turn a reservation into recorded debt (ledger `recordDraw`) atomically. Cash movement is the
    ///         manager's/vault's job in the same transaction (GPU-036).
    function consumeReservation(bytes32 id) external override onlyManager {
        Reservation storage r = _reservations[id];
        if (r.state != ReservationState.ACTIVE) revert ReservationNotActive(id, r.state);
        if (block.timestamp >= r.expiresAt) revert ReservationExpired(id, r.expiresAt);
        Authorization storage a = _auth[r.facilityId];
        if (a.epoch != r.authorizationEpoch) revert ReservationInvalidated(id, "authorization changed");
        if (!POLICY.isCurrent(r.policyVersionId)) revert ReservationInvalidated(id, "policy changed");
        IRiskPolicy.Params memory p = POLICY.params(a.policyVersionId);
        if (!_controlUsable(a, p, uint64(block.timestamp))) revert ReservationInvalidated(id, "control changed");
        r.state = ReservationState.CONSUMED;
        _reserved[r.facilityId] -= r.amount;
        LEDGER.recordDraw(r.facilityId, r.amount);
        emit ReservationConsumed(id, r.facilityId, r.amount);
    }

    function cancelReservation(bytes32 id) external override {
        if (!isManager[msg.sender] && !ROLES.hasRole(ROLES.UNDERWRITER(), msg.sender)) revert NotManager(msg.sender);
        _release(id, ReservationState.CANCELLED);
    }

    /// @notice Explicit on-chain expiry; callable by anyone once `expiresAt` has passed.
    function expireReservation(bytes32 id) external override {
        Reservation storage r = _reservations[id];
        if (r.state == ReservationState.ACTIVE && block.timestamp < r.expiresAt) {
            revert ReservationInvalidated(id, "not yet expired");
        }
        _release(id, ReservationState.EXPIRED);
    }

    // ------------------------------------------------------------------ internals

    function _release(bytes32 id, ReservationState to) internal {
        Reservation storage r = _reservations[id];
        if (r.state != ReservationState.ACTIVE) revert ReservationNotActive(id, r.state);
        r.state = to;
        _reserved[r.facilityId] -= r.amount;
        emit ReservationReleased(id, to);
    }

    function _exposure(GpuTypes.FacilityId[] storage ids, uint64 at) internal view returns (uint256 total) {
        for (uint256 i = 0; i < ids.length; i++) {
            total += LEDGER.legalDebtAt(ids[i], at) + _reserved[ids[i]];
        }
    }

    /// @dev G-D (underwriting-policy §2): effective, unexpired agreement version pinned on the facility, grade >= E2,
    ///      observation not older than the policy's `controlObservationMaxAge`.
    function _controlUsable(Authorization storage a, IRiskPolicy.Params memory p, uint64 at)
        internal
        view
        returns (bool)
    {
        if (!CONTROL.isEffective(a.controlAgreementId, a.controlVersion, at)) return false;
        if (CONTROL.agreement(a.controlAgreementId).grade < GpuTypes.ControlGrade.E2) return false;
        return CONTROL.isFresh(a.controlAgreementId, p.controlObservationMaxAge);
    }

    function _authorityUsable(
        GpuTypes.FacilityId facilityId,
        Authorization storage a,
        IRiskPolicy.Params memory p,
        uint64 at
    ) internal view returns (bool) {
        if (a.limit == 0 || a.validUntil <= at) return false;
        if (!POLICY.isCurrent(a.policyVersionId)) return false;
        if (!_controlUsable(a, p, at)) return false;
        uint64 maturity = LEDGER.view_(facilityId).maturityAt;
        if (maturity != 0 && at >= maturity) return false;
        return true;
    }

    function _room(uint256 cap, uint256 exposure) internal pure returns (uint256) {
        return cap > exposure ? cap - exposure : 0;
    }

    function _min(uint256 a, uint256 b) internal pure returns (uint256) {
        return a < b ? a : b;
    }
}
