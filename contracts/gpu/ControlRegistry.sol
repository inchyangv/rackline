// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import { GpuTypes } from "./types/GpuTypes.sol";
import { IControlRegistry } from "./interfaces/IControlRegistry.sol";
import { IAccountRegistry } from "./interfaces/IAccountRegistry.sol";
import { IDebtLedger } from "./interfaces/IDebtLedger.sol";
import { IProtocolRoles } from "./interfaces/IProtocolRoles.sol";

/**
 * @title ControlRegistry
 * @notice Payment-control agreements: versioned terms (grade, receiver, hash, effective window, PoC reference),
 *         observations, revocation and release (GPU-032; docs/gpu/permissions-and-states.md §3).
 * @dev What this registry is and is not:
 *      - It records agreements our roles have reviewed. An entry is configuration, never proof of partner-side
 *        control: an account link (AccountRegistry) never promotes a grade, and a native proof of a past "lock"
 *        event is not an input here at all. Whether the upstream lock is real is the external gate of
 *        GPU-009/056 (SANDBOX/LIVE evidence); this contract only stores its reference (`pocRef`).
 *      - E2/E3 can only be attested by the UNDERWRITER with a non-zero `pocRef` (E2RequiresPoc). REGISTRAR may
 *        only create/version E0/E1 drafts. Receiver/beneficiary changes are new versions by those roles; nobody
 *        else (keeper, borrower, servicer) can change a receiver.
 *      - Observations (SERVICER or RELAYER keeper, read-only partner facts) refresh `lastObservedAt` and may only
 *        confirm or downgrade what is effective; they never upgrade a grade. A stale observation (older than
 *        `controlObservationMaxAge`) makes `isFresh` false, so draws freeze (PIVOT §4.3 race).
 *      - `isEffective(id, version, at)` is false for unknown ids, older/newer versions, revoked or released
 *        agreements, times outside the effective window, and while the last observation contradicts the agreement
 *        (receiver changed upstream or grade observed lower). Fail closed.
 *      - Release needs two roles and authoritative facts: SERVICER approves a specific version after reconciliation
 *        (stating when the window closes and whether a refund is pending); TREASURY executes only if the bound
 *        facility's debt in the DebtLedger is zero now, the window has closed, no refund is pending, and the
 *        approved version is still current. An approval for an older version cannot release a newer one.
 *      - Agreement ids are never reusable: a released agreement is terminal, and a revoked one can only continue
 *        with a strictly greater version for the same borrower/account.
 */
contract ControlRegistry is IControlRegistry {
    IProtocolRoles public immutable ROLES;
    IAccountRegistry public immutable ACCOUNTS;
    IDebtLedger public immutable DEBT; // authoritative debt source for release; address(0) => release impossible
    uint64 private immutable _OBSERVATION_MAX_AGE;

    struct Status {
        bool exists;
        bool revoked;
        bool released;
        GpuTypes.ControlGrade observedGrade; // last observation (<= agreement grade)
        address observedReceiver; // last observed receiver (address(0) = never observed)
        GpuTypes.FacilityId facilityId; // bound facility whose ledger debt gates release
        uint32 releaseApprovedVersion; // 0 = none
        uint64 reconciliationClosesAt;
        bool refundPending;
    }

    struct ReleaseTerms {
        uint32 version;
        uint64 reconciliationClosesAt;
        bool refundPending;
    }

    mapping(bytes32 agreementId => Agreement) private _agreements;
    mapping(bytes32 agreementId => Status) private _status;

    event FacilityBound(bytes32 indexed agreementId, GpuTypes.FacilityId indexed facilityId);
    event ReleaseApproved(
        bytes32 indexed agreementId, uint32 version, uint64 reconciliationClosesAt, bool refundPending
    );

    error NotRole(bytes32 role, address caller);
    error AgreementExists(bytes32 agreementId);
    error AgreementUnknown(bytes32 agreementId);
    error AgreementTerminal(bytes32 agreementId);
    error AccountNotOwnedByBorrower(GpuTypes.AccountKey accountKey, bytes32 borrowerId);
    error GradeNotAllowedForRole(GpuTypes.ControlGrade grade, address caller);
    error ObservationCannotUpgrade(GpuTypes.ControlGrade agreementGrade, GpuTypes.ControlGrade observed);
    error BadEffectiveWindow(uint64 from, uint64 to);
    error ZeroAddress();

    constructor(IProtocolRoles roles, IAccountRegistry accounts, IDebtLedger debt, uint64 observationMaxAge) {
        if (address(roles) == address(0) || address(accounts) == address(0)) revert ZeroAddress();
        ROLES = roles;
        ACCOUNTS = accounts;
        DEBT = debt;
        _OBSERVATION_MAX_AGE = observationMaxAge;
    }

    modifier onlyRole(bytes32 role) {
        if (!ROLES.hasRole(role, msg.sender)) revert NotRole(role, msg.sender);
        _;
    }

    // ------------------------------------------------------------------ versions (REGISTRAR <= E1, UNDERWRITER >= E2)

    /// @notice Create version 1 of an agreement. Grade E0/E1 by REGISTRAR, E2/E3 by UNDERWRITER with `pocRef`.
    function createAgreement(
        bytes32 agreementId,
        bytes32 borrowerId,
        GpuTypes.AccountKey accountKey,
        GpuTypes.ControlGrade grade,
        address receiver,
        uint64 receiverChainId,
        bytes32 agreementHash,
        uint64 effectiveFrom,
        uint64 effectiveTo,
        bytes32 pocRef
    ) external {
        if (_status[agreementId].exists) revert AgreementExists(agreementId);
        _checkGradeAuthority(agreementId, grade, pocRef);
        if (ACCOUNTS.borrowerOfAccount(accountKey) != borrowerId) {
            revert AccountNotOwnedByBorrower(accountKey, borrowerId);
        }
        _status[agreementId].exists = true;
        _writeVersion(
            agreementId,
            borrowerId,
            accountKey,
            grade,
            1,
            receiver,
            receiverChainId,
            agreementHash,
            effectiveFrom,
            effectiveTo,
            pocRef
        );
    }

    /// @notice Add a strictly greater version (receiver/grade/hash/window change). Clears a revocation only
    ///         because the new version is a fresh review; E2/E3 still require UNDERWRITER + `pocRef`.
    function bumpVersion(
        bytes32 agreementId,
        GpuTypes.ControlGrade grade,
        address receiver,
        uint64 receiverChainId,
        bytes32 agreementHash,
        uint64 effectiveFrom,
        uint64 effectiveTo,
        bytes32 pocRef
    ) external {
        Status storage st = _status[agreementId];
        if (!st.exists) revert AgreementUnknown(agreementId);
        if (st.released) revert AgreementTerminal(agreementId);
        _checkGradeAuthority(agreementId, grade, pocRef);
        Agreement storage a = _agreements[agreementId];
        st.revoked = false;
        st.releaseApprovedVersion = 0; // an approval bound to the previous version cannot release this one
        _writeVersion(
            agreementId,
            a.borrowerId,
            a.accountKey,
            grade,
            a.version + 1,
            receiver,
            receiverChainId,
            agreementHash,
            effectiveFrom,
            effectiveTo,
            pocRef
        );
    }

    /// @notice Bind the facility whose authoritative ledger debt gates release (UNDERWRITER).
    function bindFacility(bytes32 agreementId, GpuTypes.FacilityId facilityId) external onlyRole(ROLES.UNDERWRITER()) {
        Status storage st = _status[agreementId];
        if (!st.exists) revert AgreementUnknown(agreementId);
        if (st.released) revert AgreementTerminal(agreementId);
        st.facilityId = facilityId;
        emit FacilityBound(agreementId, facilityId);
    }

    // ------------------------------------------------------------------ observations (SERVICER / RELAYER keeper)

    /// @notice Record a read-only partner observation. Can confirm or downgrade, never upgrade.
    function observe(bytes32 agreementId, GpuTypes.ControlGrade observedGrade, address observedReceiver) external {
        if (!ROLES.hasRole(ROLES.SERVICER(), msg.sender) && !ROLES.hasRole(ROLES.RELAYER(), msg.sender)) {
            revert NotRole(ROLES.SERVICER(), msg.sender);
        }
        Status storage st = _status[agreementId];
        if (!st.exists) revert AgreementUnknown(agreementId);
        if (st.released) revert AgreementTerminal(agreementId);
        Agreement storage a = _agreements[agreementId];
        if (observedGrade > a.grade) revert ObservationCannotUpgrade(a.grade, observedGrade);
        st.observedGrade = observedGrade;
        st.observedReceiver = observedReceiver;
        a.lastObservedAt = uint64(block.timestamp);
        emit ControlObserved(agreementId, observedGrade, observedReceiver, uint64(block.timestamp));
    }

    // ------------------------------------------------------------------ revoke (GUARDIAN) / release (SERVICER +
    // TREASURY)

    /// @notice Incident revocation: not effective from now on; collections continue elsewhere. Grade drops to E1.
    function revoke(bytes32 agreementId, string calldata reason) external onlyRole(ROLES.GUARDIAN()) {
        Status storage st = _status[agreementId];
        if (!st.exists) revert AgreementUnknown(agreementId);
        if (st.released) revert AgreementTerminal(agreementId);
        st.revoked = true;
        st.releaseApprovedVersion = 0;
        Agreement storage a = _agreements[agreementId];
        if (a.grade > GpuTypes.ControlGrade.E1) a.grade = GpuTypes.ControlGrade.E1;
        if (st.observedGrade > GpuTypes.ControlGrade.E1) st.observedGrade = GpuTypes.ControlGrade.E1;
        emit ControlRevoked(agreementId, reason, uint64(block.timestamp));
    }

    /// @notice SERVICER states the reconciliation outcome for exactly the current version.
    function approveRelease(bytes32 agreementId, ReleaseTerms calldata terms) external onlyRole(ROLES.SERVICER()) {
        Status storage st = _status[agreementId];
        if (!st.exists) revert AgreementUnknown(agreementId);
        if (st.released) revert AgreementTerminal(agreementId);
        if (terms.version == 0 || terms.version != _agreements[agreementId].version) {
            revert AgreementNotEffective(agreementId, terms.version);
        }
        st.releaseApprovedVersion = terms.version;
        st.reconciliationClosesAt = terms.reconciliationClosesAt;
        st.refundPending = terms.refundPending;
        emit ReleaseApproved(agreementId, terms.version, terms.reconciliationClosesAt, terms.refundPending);
    }

    /// @notice TREASURY executes the release. Every condition is checked now, against authoritative state.
    function release(bytes32 agreementId, uint32 version) external onlyRole(ROLES.TREASURY()) {
        Status storage st = _status[agreementId];
        if (!st.exists) revert AgreementUnknown(agreementId);
        if (st.released) revert AgreementTerminal(agreementId);
        Agreement storage a = _agreements[agreementId];
        if (version == 0 || version != a.version) revert AgreementNotEffective(agreementId, version);
        if (st.releaseApprovedVersion != version) revert ReleaseBlocked("servicer approval missing or stale");
        if (st.refundPending) revert ReleaseBlocked("refund pending");
        if (block.timestamp < st.reconciliationClosesAt) revert ReleaseBlocked("reconciliation window open");
        if (address(DEBT) == address(0)) revert ReleaseBlocked("no authoritative debt source");
        if (GpuTypes.FacilityId.unwrap(st.facilityId) == bytes32(0)) revert ReleaseBlocked("no facility bound");
        if (DEBT.legalDebtAt(st.facilityId, uint64(block.timestamp)) != 0) revert ReleaseBlocked("debt outstanding");
        st.released = true;
        st.releaseApprovedVersion = 0;
        a.effectiveTo = uint64(block.timestamp);
        emit ControlReleased(agreementId, uint64(block.timestamp));
    }

    // ------------------------------------------------------------------ views

    function agreement(bytes32 agreementId) external view override returns (Agreement memory) {
        if (!_status[agreementId].exists) revert AgreementUnknown(agreementId);
        return _agreements[agreementId];
    }

    function status(bytes32 agreementId) external view returns (Status memory) {
        return _status[agreementId];
    }

    /// @notice Grade that may be relied on now: min(agreement grade, last observed grade); E0 when not effective.
    function effectiveGrade(bytes32 agreementId) public view returns (GpuTypes.ControlGrade) {
        Agreement storage a = _agreements[agreementId];
        if (!isEffective(agreementId, a.version, uint64(block.timestamp))) return GpuTypes.ControlGrade.E0;
        Status storage st = _status[agreementId];
        return st.observedReceiver == address(0) || st.observedGrade > a.grade ? a.grade : st.observedGrade;
    }

    function isEffective(bytes32 agreementId, uint32 version, uint64 at) public view override returns (bool) {
        Status storage st = _status[agreementId];
        if (!st.exists || st.revoked || st.released) return false;
        Agreement storage a = _agreements[agreementId];
        if (version == 0 || version != a.version) return false;
        if (at < a.effectiveFrom) return false;
        if (a.effectiveTo != 0 && at >= a.effectiveTo) return false;
        // the last observation must not contradict the agreement (upstream receiver change / lower grade)
        if (st.observedReceiver != address(0)) {
            if (st.observedReceiver != a.receiver) return false;
            if (st.observedGrade < a.grade) return false;
        }
        return true;
    }

    function isFresh(bytes32 agreementId, uint64 maxAge) public view override returns (bool) {
        Status storage st = _status[agreementId];
        if (!st.exists || st.revoked || st.released) return false;
        uint64 last = _agreements[agreementId].lastObservedAt;
        if (last == 0) return false;
        return block.timestamp <= uint256(last) + maxAge;
    }

    function controlObservationMaxAge() external view override returns (uint64) {
        return _OBSERVATION_MAX_AGE;
    }

    /// @notice Draw-time check: current version effective, grade >= required, observation fresh. Reverts otherwise.
    function requireUsable(bytes32 agreementId, uint32 version, GpuTypes.ControlGrade required) external view {
        if (!isEffective(agreementId, version, uint64(block.timestamp))) {
            revert AgreementNotEffective(agreementId, version);
        }
        GpuTypes.ControlGrade g = effectiveGrade(agreementId);
        if (g < required) revert GradeInsufficient(required, g);
        if (!isFresh(agreementId, _OBSERVATION_MAX_AGE)) {
            revert ObservationStale(_agreements[agreementId].lastObservedAt, _OBSERVATION_MAX_AGE);
        }
    }

    // ------------------------------------------------------------------ internals

    function _checkGradeAuthority(bytes32 agreementId, GpuTypes.ControlGrade grade, bytes32 pocRef) internal view {
        if (grade >= GpuTypes.ControlGrade.E2) {
            if (!ROLES.hasRole(ROLES.UNDERWRITER(), msg.sender)) revert GradeNotAllowedForRole(grade, msg.sender);
            if (pocRef == bytes32(0)) revert E2RequiresPoc(agreementId);
        } else if (!ROLES.hasRole(ROLES.REGISTRAR(), msg.sender) && !ROLES.hasRole(ROLES.UNDERWRITER(), msg.sender)) {
            revert GradeNotAllowedForRole(grade, msg.sender);
        }
    }

    function _writeVersion(
        bytes32 agreementId,
        bytes32 borrowerId,
        GpuTypes.AccountKey accountKey,
        GpuTypes.ControlGrade grade,
        uint32 version,
        address receiver,
        uint64 receiverChainId,
        bytes32 agreementHash,
        uint64 effectiveFrom,
        uint64 effectiveTo,
        bytes32 pocRef
    ) internal {
        if (receiver == address(0) || agreementHash == bytes32(0)) revert ZeroAddress();
        if (effectiveTo != 0 && effectiveTo <= effectiveFrom) revert BadEffectiveWindow(effectiveFrom, effectiveTo);
        Agreement storage a = _agreements[agreementId];
        a.agreementId = agreementId;
        a.borrowerId = borrowerId;
        a.accountKey = accountKey;
        a.grade = grade;
        a.version = version;
        a.receiver = receiver;
        a.receiverChainId = receiverChainId;
        a.agreementHash = agreementHash;
        a.effectiveFrom = effectiveFrom;
        a.effectiveTo = effectiveTo;
        a.pocRef = pocRef;
        // a new version has not been observed yet: the previous observation cannot vouch for the new receiver
        a.lastObservedAt = 0;
        Status storage st = _status[agreementId];
        st.observedReceiver = address(0);
        st.observedGrade = GpuTypes.ControlGrade.E0;
        emit AgreementVersioned(agreementId, version, grade, agreementHash);
    }
}
