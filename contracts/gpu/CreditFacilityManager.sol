// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import { GpuTypes } from "./types/GpuTypes.sol";
import { ICreditFacilityManager } from "./interfaces/ICreditFacilityManager.sol";
import { IProtocolRoles } from "./interfaces/IProtocolRoles.sol";
import { IDebtLedger } from "./interfaces/IDebtLedger.sol";
import { ILendingVaultV2 } from "./interfaces/ILendingVaultV2.sol";
import { IAccountRegistry } from "./interfaces/IAccountRegistry.sol";
import { IControlRegistry } from "./interfaces/IControlRegistry.sol";
import { IExposureController } from "./interfaces/IExposureController.sol";
import { IReceivableBook } from "./interfaces/IReceivableBook.sol";
import { IEvidenceBook } from "./interfaces/IEvidenceBook.sol";
import { IRevenueVerifier } from "./interfaces/IRevenueVerifier.sol";
import { IAuthorizationVerifier } from "./interfaces/IAuthorizationVerifier.sol";
import { GpuRiskPolicy } from "./GpuRiskPolicy.sol";

/// @dev Ledger surface beyond IDebtLedger that the manager needs (GPU-033 `DebtLedger.setState`).
interface IDebtLedgerState {
    function setState(GpuTypes.FacilityId facilityId, GpuTypes.FacilityState state) external;
}

/// @dev Control registry surface beyond IControlRegistry (GPU-032 `ControlRegistry.requireUsable`).
interface IControlUsable {
    function requireUsable(bytes32 agreementId, uint32 version, GpuTypes.ControlGrade required) external view;
}

/// @dev Vault surface beyond ILendingVaultV2 that the manager needs (GPU-034 `refundExcess`, `refundableOf`).
interface IVaultRefunds {
    function refundExcess(GpuTypes.FacilityId facilityId, address to, uint256 amount) external;
    function refundableOf(GpuTypes.FacilityId facilityId) external view returns (uint256);
}

interface IERC20Minimal {
    function balanceOf(address) external view returns (uint256);
}

/**
 * @title CreditFacilityManager
 * @notice Facility lifecycle, credit-authorization anchoring, atomic draws and `repayFor` (GPU-036, PIVOT §5/§7).
 * @dev Composition (single writer of the DebtLedger through the ExposureController, MANAGER of the vault):
 *      - `openFacility` (UNDERWRITER): ledger facility opened with the terms; borrower wallet must be linked in
 *        the AccountRegistry; the ReceivableBook facility must exist for the same borrower; execution profile must
 *        equal the provider's EvidenceBook-bound verifier profile (no LOCAL_MOCK facility on a native provider).
 *      - `anchorAuthorization`: the underwriter's CREDIT_APPROVAL signature (AuthorizationVerifier: role, epoch,
 *        nonce, expiry) over `keccak256(abi.encode(CreditAuthorization))`. The struct binds facility, decision
 *        hash, limit, validity, policy version, verifier manifest and control agreement version. The anchor must
 *        equal the ExposureController authorization set by the underwriter (limit / policy / control / validity):
 *        two independent records must agree before any draw. A newer anchor supersedes; nothing renews itself.
 *      - `borrow` (linked borrower wallet only): draws not paused, state ACTIVE, anchor valid now, manifest still
 *        the verifier's, policy version current, control agreement usable at E2, `evaluateDraw` shows a natively
 *        proven eligible base (`NativeEvidenceRequired` otherwise) and `amount <= availableDraw`, vault cash
 *        sufficient; then in ONE transaction: reserve → consume (ledger `recordDraw`) → `vault.lend` to the linked
 *        wallet → measured recipient delta >= `minReceived`. Any failure reverts everything. Recipient is never a
 *        parameter. The two-step `reserveDraw` / `executeReservedDraw` path exists for keepers; expiry, duplicate
 *        consumption and authority changes are enforced by the ExposureController.
 *      - `repayFor` (anyone, any state with a ledger facility, never paused): pulls loan asset from the caller into
 *        the vault (measured), `ledger.allocate`, `vault.onRepayment`; excess is borrower-owned refundable cash
 *        (`claimRefund`). No proof, signature or evidence is involved (R2-D07 / PD-06). Debt == 0 ⇒ REPAID.
 *      - State machine mirrors docs/gpu/permissions-and-states.md §4 (`facility-transitions-v1.json`); `system`
 *        transitions that need schedules/monitors (delinquency, cure, evidence-stale freeze) are GPU-041/044 and
 *        are exposed here only through the authorities the table names. `credit_committee` maps to ADMIN_ROLE
 *        (timelocked multisig) until GPU-043 wires a dedicated committee.
 *      - No testnet grant, no limit increase, no `pauseRepayments`, no recipient override (PD-08).
 */
contract CreditFacilityManager is ICreditFacilityManager {
    bytes32 public constant ADMIN_ROLE = keccak256("ADMIN");

    IProtocolRoles public immutable ROLES;
    IDebtLedger public immutable LEDGER;
    ILendingVaultV2 public immutable VAULT;
    IAccountRegistry public immutable ACCOUNTS;
    IControlRegistry public immutable CONTROL;
    IExposureController public immutable EXPOSURE;
    GpuRiskPolicy public immutable POLICY;
    IReceivableBook public immutable BOOK;
    IEvidenceBook public immutable EVIDENCE;
    IAuthorizationVerifier public immutable AUTH;

    struct Facility {
        bytes32 borrowerId;
        address wallet;
        GpuTypes.ProviderId providerId;
        bytes32 controlAgreementId;
        uint32 controlVersion;
        GpuTypes.ExecutionProfile profile;
        GpuTypes.FacilityState state;
        bool exists;
    }

    struct Anchor {
        GpuTypes.CreditAuthorization auth;
        address signer;
        uint64 epoch;
        uint64 anchoredAt;
        bool exists;
    }

    mapping(GpuTypes.FacilityId => Facility) private _facilities;
    mapping(GpuTypes.FacilityId => Anchor) private _anchors;
    mapping(GpuTypes.FacilityId => uint64) private _drawNonce;
    mapping(bytes32 reservationId => GpuTypes.FacilityId) private _reservationFacility;
    bool private _drawsPaused;
    uint256 private _lock = 1;

    event FacilityFrozen(GpuTypes.FacilityId indexed facilityId, address indexed by, bytes32 trigger);
    event DrawReserved(
        GpuTypes.FacilityId indexed facilityId, bytes32 indexed reservationId, uint256 amount, uint64 expiresAt
    );
    event ExcessRefunded(GpuTypes.FacilityId indexed facilityId, address indexed to, uint256 amount);

    error ZeroAddress();
    error ZeroAmount();
    error Reentrancy();
    error FacilityExists(GpuTypes.FacilityId facilityId);
    error FacilityUnknown(GpuTypes.FacilityId facilityId);
    error FacilityNotActive(GpuTypes.FacilityId facilityId, GpuTypes.FacilityState state);
    error NotRole(bytes32 role, address caller);
    error WalletNotLinked(bytes32 borrowerId, address wallet);
    error BookFacilityMismatch(GpuTypes.FacilityId facilityId);
    error ControlAgreementMismatch(bytes32 agreementId, bytes32 borrowerId);
    error AuthorizationFacilityMismatch(GpuTypes.FacilityId expected, GpuTypes.FacilityId actual);
    error PolicyVersionStale(bytes32 policyVersionId);
    error ExposureAuthorizationMismatch(GpuTypes.FacilityId facilityId, string field);
    error InsufficientReceived(uint256 minReceived, uint256 received);
    error ReservationUnknown(bytes32 reservationId);
    error TransferFailed();
    error NothingToRefund(GpuTypes.FacilityId facilityId);

    constructor(
        IProtocolRoles roles,
        IDebtLedger ledger,
        ILendingVaultV2 vault,
        IAccountRegistry accounts,
        IControlRegistry control,
        IExposureController exposure,
        GpuRiskPolicy policy,
        IReceivableBook book,
        IEvidenceBook evidence,
        IAuthorizationVerifier auth
    ) {
        if (
            address(roles) == address(0) || address(ledger) == address(0) || address(vault) == address(0)
                || address(accounts) == address(0) || address(control) == address(0) || address(exposure) == address(0)
                || address(policy) == address(0) || address(book) == address(0) || address(evidence) == address(0)
                || address(auth) == address(0)
        ) revert ZeroAddress();
        ROLES = roles;
        LEDGER = ledger;
        VAULT = vault;
        ACCOUNTS = accounts;
        CONTROL = control;
        EXPOSURE = exposure;
        POLICY = policy;
        BOOK = book;
        EVIDENCE = evidence;
        AUTH = auth;
    }

    modifier nonReentrant() {
        if (_lock != 1) revert Reentrancy();
        _lock = 2;
        _;
        _lock = 1;
    }

    modifier onlyRole(bytes32 role) {
        if (!ROLES.hasRole(role, msg.sender)) revert NotRole(role, msg.sender);
        _;
    }

    modifier exists(GpuTypes.FacilityId facilityId) {
        if (!_facilities[facilityId].exists) revert FacilityUnknown(facilityId);
        _;
    }

    // ------------------------------------------------------------------ facility lifecycle

    /// @notice Open a facility in DRAFT with fixed terms. The wallet must already be linked to `borrowerId`, the
    ///         ReceivableBook facility must exist for the same borrower/provider, and the execution profile must
    ///         match the provider's bound verifier (ProfileMismatch otherwise).
    function openFacility(
        GpuTypes.FacilityId facilityId,
        bytes32 borrowerId,
        address wallet,
        IDebtLedger.Terms calldata terms,
        bytes32 controlAgreementId,
        uint32 controlVersion
    ) external onlyRole(ROLES.UNDERWRITER()) {
        if (_facilities[facilityId].exists) revert FacilityExists(facilityId);
        if (!ACCOUNTS.isWalletOf(borrowerId, wallet)) revert WalletNotLinked(borrowerId, wallet);
        IReceivableBook.Facility memory bf = BOOK.facility(facilityId);
        if (!bf.exists || bf.borrowerId != borrowerId) revert BookFacilityMismatch(facilityId);
        IRevenueVerifier verifier = EVIDENCE.verifierOf(bf.providerId);
        if (address(verifier) == address(0)) revert NativeEvidenceRequired(facilityId);
        GpuTypes.ExecutionProfile vp = verifier.executionProfile();
        if (vp != terms.executionProfile) revert ProfileMismatch(vp, terms.executionProfile);
        IControlRegistry.Agreement memory agr = CONTROL.agreement(controlAgreementId);
        if (agr.borrowerId != borrowerId || agr.version != controlVersion) {
            revert ControlAgreementMismatch(controlAgreementId, borrowerId);
        }
        LEDGER.open(facilityId, terms);
        _facilities[facilityId] = Facility({
            borrowerId: borrowerId,
            wallet: wallet,
            providerId: bf.providerId,
            controlAgreementId: controlAgreementId,
            controlVersion: controlVersion,
            profile: terms.executionProfile,
            state: GpuTypes.FacilityState.DRAFT,
            exists: true
        });
        IDebtLedgerState(address(LEDGER)).setState(facilityId, GpuTypes.FacilityState.DRAFT);
        emit FacilityOpened(facilityId, borrowerId, terms.executionProfile, terms.termsVersionId);
    }

    /// @notice Explicit state transition by the authority the GPU-013 table names for (from, to).
    function transition(GpuTypes.FacilityId facilityId, GpuTypes.FacilityState to, bytes32 trigger)
        external
        exists(facilityId)
    {
        Facility storage f = _facilities[facilityId];
        GpuTypes.FacilityState from = f.state;
        if (!isTransitionAllowed(from, to)) revert IllegalTransition(from, to);
        if (!_hasAuthority(f, from, to, msg.sender)) revert NotRole(_authorityLabel(from, to), msg.sender);
        _guard(facilityId, f, from, to);
        _setState(facilityId, f, to, trigger, msg.sender);
    }

    /// @notice GUARDIAN per-facility freeze (ACTIVE -> DRAW_FROZEN). Global pause is `pauseDraws`.
    function freezeDraws(GpuTypes.FacilityId facilityId, bytes32 trigger)
        external
        exists(facilityId)
        onlyRole(ROLES.GUARDIAN())
    {
        Facility storage f = _facilities[facilityId];
        if (f.state != GpuTypes.FacilityState.ACTIVE) {
            revert IllegalTransition(f.state, GpuTypes.FacilityState.DRAW_FROZEN);
        }
        _setState(facilityId, f, GpuTypes.FacilityState.DRAW_FROZEN, trigger, msg.sender);
        emit FacilityFrozen(facilityId, msg.sender, trigger);
    }

    function pauseDraws(bool paused) external override onlyRole(ROLES.GUARDIAN()) {
        _drawsPaused = paused;
        emit DrawsPaused(msg.sender, paused);
    }

    // ------------------------------------------------------------------ authorization anchoring

    function anchorAuthorization(
        GpuTypes.CreditAuthorization calldata auth,
        GpuTypes.SupplementaryAssertion calldata underwriterApproval
    ) external override exists(auth.facilityId) {
        Facility storage f = _facilities[auth.facilityId];
        if (auth.validUntil <= block.timestamp) revert AuthorizationMissingOrExpired(auth.facilityId);
        if (!POLICY.isCurrent(auth.policyVersionId)) revert PolicyVersionStale(auth.policyVersionId);
        bytes32 expectedManifest = EVIDENCE.verifierOf(f.providerId).manifestHash();
        if (auth.manifestHash != expectedManifest) {
            revert AuthorizationManifestMismatch(expectedManifest, auth.manifestHash);
        }
        if (auth.controlAgreementVersionHash != controlVersionHash(f.controlAgreementId, f.controlVersion)) {
            revert ControlInsufficientOrStale(auth.facilityId);
        }
        _requireExposureAgrees(auth);
        // The underwriter signature is an auxiliary approval (R2-D04): it is checked for role, epoch, nonce and
        // expiry by the AuthorizationVerifier and never creates evidence or a limit by itself.
        AUTH.verifyAndConsume(
            underwriterApproval, GpuTypes.AssertionPurpose.CREDIT_APPROVAL, authorizationSubject(auth)
        );
        Anchor storage a = _anchors[auth.facilityId];
        a.auth = auth;
        a.signer = underwriterApproval.signer;
        a.epoch += 1;
        a.anchoredAt = uint64(block.timestamp);
        a.exists = true;
        emit AuthorizationAnchored(auth.facilityId, auth.decisionHash, auth.limit, auth.validUntil, auth.manifestHash);
    }

    function authorizationSubject(GpuTypes.CreditAuthorization calldata auth) public pure returns (bytes32) {
        return keccak256(abi.encode(auth));
    }

    function controlVersionHash(bytes32 agreementId, uint32 version) public pure returns (bytes32) {
        return keccak256(abi.encode(agreementId, version));
    }

    function anchor(GpuTypes.FacilityId facilityId) external view returns (Anchor memory) {
        return _anchors[facilityId];
    }

    // ------------------------------------------------------------------ draws

    function borrow(GpuTypes.FacilityId facilityId, uint256 amount, uint256 minReceived)
        external
        override
        nonReentrant
    {
        bytes32 id = _reserve(facilityId, amount, uint64(block.timestamp + 1));
        _execute(id, minReceived);
    }

    /// @notice Two-step path: reserve now, execute within `ttl` seconds (keeper-friendly). Borrower wallet only.
    function reserveDraw(GpuTypes.FacilityId facilityId, uint256 amount, uint64 ttl)
        external
        nonReentrant
        returns (bytes32 reservationId)
    {
        if (ttl == 0) revert ZeroAmount();
        reservationId = _reserve(facilityId, amount, uint64(block.timestamp) + ttl);
    }

    function executeReservedDraw(bytes32 reservationId, uint256 minReceived) external nonReentrant {
        _execute(reservationId, minReceived);
    }

    function evaluateDraw(GpuTypes.FacilityId facilityId, uint256)
        external
        view
        override
        exists(facilityId)
        returns (GpuTypes.DrawEvaluation memory e)
    {
        e = EXPOSURE.evaluateDraw(facilityId);
        if (!_anchorValid(facilityId) || _drawsPaused || _facilities[facilityId].state != GpuTypes.FacilityState.ACTIVE)
        {
            e.availableDraw = 0;
        }
    }

    function _reserve(GpuTypes.FacilityId facilityId, uint256 amount, uint64 expiresAt)
        internal
        exists(facilityId)
        returns (bytes32 id)
    {
        Facility storage f = _facilities[facilityId];
        if (msg.sender != f.wallet) revert NotBorrower(facilityId, msg.sender);
        if (amount == 0) revert ZeroAmount();
        _checkDrawable(facilityId, f);
        GpuTypes.DrawEvaluation memory ev = EXPOSURE.evaluateDraw(facilityId);
        if (ev.eligibleReceivables == 0 || ev.evidenceValidUntil <= block.timestamp) {
            revert NativeEvidenceRequired(facilityId);
        }
        if (amount > ev.availableDraw) revert ExceedsAvailableDraw(amount, ev.availableDraw);
        if (amount > VAULT.availableCash()) revert ExceedsAvailableDraw(amount, VAULT.availableCash());
        uint64 nonce = ++_drawNonce[facilityId];
        id = EXPOSURE.reserve(facilityId, amount, nonce, expiresAt);
        _reservationFacility[id] = facilityId;
        emit DrawReserved(facilityId, id, amount, expiresAt);
    }

    function _execute(bytes32 id, uint256 minReceived) internal {
        GpuTypes.FacilityId facilityId = _reservationFacility[id];
        if (GpuTypes.FacilityId.unwrap(facilityId) == bytes32(0)) revert ReservationUnknown(id);
        Facility storage f = _facilities[facilityId];
        if (msg.sender != f.wallet) revert NotBorrower(facilityId, msg.sender);
        _checkDrawable(facilityId, f);
        IExposureController.Reservation memory r = EXPOSURE.reservation(id);
        // reserved -> consumed and ledger recordDraw happen inside the controller (atomic with this call)
        EXPOSURE.consumeReservation(id);
        address asset = VAULT.asset();
        uint256 before = IERC20Minimal(asset).balanceOf(f.wallet);
        VAULT.lend(facilityId, f.wallet, r.amount);
        uint256 received = IERC20Minimal(asset).balanceOf(f.wallet) - before;
        if (received < minReceived || received == 0) revert InsufficientReceived(minReceived, received);
        uint256 newDebt = LEDGER.legalDebtAt(facilityId, uint64(block.timestamp));
        emit Borrowed(facilityId, r.amount, newDebt, _anchors[facilityId].auth.decisionHash);
    }

    /// @dev Common draw gates: pause, state, anchored authorization (fresh, manifest, policy, control), E2 usable.
    function _checkDrawable(GpuTypes.FacilityId facilityId, Facility storage f) internal view {
        if (_drawsPaused) revert DrawsArePaused();
        if (f.state != GpuTypes.FacilityState.ACTIVE) revert FacilityNotActive(facilityId, f.state);
        Anchor storage a = _anchors[facilityId];
        if (!a.exists || a.auth.validUntil <= block.timestamp) revert AuthorizationMissingOrExpired(facilityId);
        bytes32 expectedManifest = EVIDENCE.verifierOf(f.providerId).manifestHash();
        if (a.auth.manifestHash != expectedManifest) {
            revert AuthorizationManifestMismatch(expectedManifest, a.auth.manifestHash);
        }
        if (!POLICY.isCurrent(a.auth.policyVersionId)) revert PolicyVersionStale(a.auth.policyVersionId);
        if (a.auth.controlAgreementVersionHash != controlVersionHash(f.controlAgreementId, f.controlVersion)) {
            revert ControlInsufficientOrStale(facilityId);
        }
        try IControlUsable(address(CONTROL))
            .requireUsable(f.controlAgreementId, f.controlVersion, GpuTypes.ControlGrade.E2) { }
        catch {
            revert ControlInsufficientOrStale(facilityId);
        }
    }

    function _anchorValid(GpuTypes.FacilityId facilityId) internal view returns (bool) {
        Anchor storage a = _anchors[facilityId];
        if (!a.exists || a.auth.validUntil <= block.timestamp) return false;
        Facility storage f = _facilities[facilityId];
        if (a.auth.manifestHash != EVIDENCE.verifierOf(f.providerId).manifestHash()) return false;
        if (!POLICY.isCurrent(a.auth.policyVersionId)) return false;
        return a.auth.controlAgreementVersionHash == controlVersionHash(f.controlAgreementId, f.controlVersion);
    }

    /// @dev The ExposureController authorization (set by the underwriter on-chain) must equal the signed anchor.
    function _requireExposureAgrees(GpuTypes.CreditAuthorization calldata auth) internal view {
        IExposureController.Authorization memory ea = EXPOSURE.authorization(auth.facilityId);
        Facility storage f = _facilities[auth.facilityId];
        if (!ea.exists) revert ExposureAuthorizationMismatch(auth.facilityId, "missing");
        if (ea.limit != auth.limit) revert ExposureAuthorizationMismatch(auth.facilityId, "limit");
        if (ea.policyVersionId != auth.policyVersionId) {
            revert ExposureAuthorizationMismatch(auth.facilityId, "policy");
        }
        if (ea.controlAgreementId != f.controlAgreementId || ea.controlVersion != f.controlVersion) {
            revert ExposureAuthorizationMismatch(auth.facilityId, "control");
        }
        if (ea.validUntil != auth.validUntil) revert ExposureAuthorizationMismatch(auth.facilityId, "validUntil");
    }

    // ------------------------------------------------------------------ repayments (never paused, no evidence)

    function repayFor(GpuTypes.FacilityId facilityId, uint256 amount)
        external
        override
        nonReentrant
        exists(facilityId)
        returns (GpuTypes.RepayResult memory r)
    {
        if (amount == 0) revert ZeroAmount();
        address asset = VAULT.asset();
        uint256 before = IERC20Minimal(asset).balanceOf(address(VAULT));
        _pullToVault(asset, msg.sender, amount);
        uint256 received = IERC20Minimal(asset).balanceOf(address(VAULT)) - before;
        if (received == 0) revert TransferFailed();
        r = LEDGER.allocate(facilityId, received);
        VAULT.onRepayment(facilityId, r);
        emit Repaid(facilityId, msg.sender, amount, received, r.applied, r.excess, r.newDebt);
        Facility storage f = _facilities[facilityId];
        if (r.newDebt == 0 && isTransitionAllowed(f.state, GpuTypes.FacilityState.REPAID)) {
            _setState(facilityId, f, GpuTypes.FacilityState.REPAID, "debt_zero", address(this));
        }
    }

    /// @notice Borrower-owned excess (over-repayment) is refundable to the linked wallet only.
    function claimRefund(GpuTypes.FacilityId facilityId) external nonReentrant exists(facilityId) {
        Facility storage f = _facilities[facilityId];
        if (msg.sender != f.wallet) revert NotBorrower(facilityId, msg.sender);
        uint256 amount = IVaultRefunds(address(VAULT)).refundableOf(facilityId);
        if (amount == 0) revert NothingToRefund(facilityId);
        IVaultRefunds(address(VAULT)).refundExcess(facilityId, f.wallet, amount);
        emit ExcessRefunded(facilityId, f.wallet, amount);
    }

    // ------------------------------------------------------------------ views

    function facility(GpuTypes.FacilityId facilityId)
        external
        view
        override
        exists(facilityId)
        returns (GpuTypes.FacilityLedgerView memory v)
    {
        v = LEDGER.view_(facilityId);
        v.state = _facilities[facilityId].state;
        v.reservedDraws = EXPOSURE.reservedOf(facilityId);
    }

    function state(GpuTypes.FacilityId facilityId)
        external
        view
        override
        exists(facilityId)
        returns (GpuTypes.FacilityState)
    {
        return _facilities[facilityId].state;
    }

    function facilityInfo(GpuTypes.FacilityId facilityId) external view returns (Facility memory) {
        return _facilities[facilityId];
    }

    function drawsPaused() external view override returns (bool) {
        return _drawsPaused;
    }

    // ------------------------------------------------------------------ state machine
    // (docs/gpu/permissions-and-states.md §4)

    /// @notice Mirror of `config/gpu/schema/facility-transitions-v1.json` (parity asserted in GPU036DrawTest).
    function isTransitionAllowed(GpuTypes.FacilityState from, GpuTypes.FacilityState to) public pure returns (bool) {
        GpuTypes.FacilityState S_DRAFT = GpuTypes.FacilityState.DRAFT;
        if (from == S_DRAFT) return to == GpuTypes.FacilityState.UNDER_REVIEW;
        if (from == GpuTypes.FacilityState.UNDER_REVIEW) return to == GpuTypes.FacilityState.CONTROL_PENDING;
        if (from == GpuTypes.FacilityState.CONTROL_PENDING) return to == GpuTypes.FacilityState.ACTIVE;
        if (from == GpuTypes.FacilityState.ACTIVE) {
            return to == GpuTypes.FacilityState.DRAW_FROZEN || to == GpuTypes.FacilityState.DELINQUENT
                || to == GpuTypes.FacilityState.REPAID;
        }
        if (from == GpuTypes.FacilityState.DRAW_FROZEN) {
            return to == GpuTypes.FacilityState.ACTIVE || to == GpuTypes.FacilityState.DELINQUENT;
        }
        if (from == GpuTypes.FacilityState.DELINQUENT) {
            return to == GpuTypes.FacilityState.ACTIVE || to == GpuTypes.FacilityState.DEFAULTED;
        }
        if (from == GpuTypes.FacilityState.DEFAULTED) return to == GpuTypes.FacilityState.RECOVERY;
        if (from == GpuTypes.FacilityState.RECOVERY) {
            return to == GpuTypes.FacilityState.REPAID || to == GpuTypes.FacilityState.CLOSED_WITH_LOSS;
        }
        if (from == GpuTypes.FacilityState.REPAID) return to == GpuTypes.FacilityState.RELEASED;
        return false;
    }

    /// @dev Authorities per the table. `system` transitions are performed by this contract itself (repayFor →
    ///      REPAID) or by GPU-041/044 automation later; `credit_committee` = ADMIN_ROLE for now.
    function _hasAuthority(Facility storage f, GpuTypes.FacilityState from, GpuTypes.FacilityState to, address who)
        internal
        view
        returns (bool)
    {
        if (from == GpuTypes.FacilityState.DRAFT) return ROLES.hasRole(ROLES.REGISTRAR(), who);
        if (from == GpuTypes.FacilityState.UNDER_REVIEW) return ROLES.hasRole(ROLES.UNDERWRITER(), who);
        if (from == GpuTypes.FacilityState.CONTROL_PENDING) {
            return ROLES.hasRole(ROLES.UNDERWRITER(), who) || ROLES.hasRole(ROLES.SERVICER(), who);
        }
        if (to == GpuTypes.FacilityState.DRAW_FROZEN) return ROLES.hasRole(ROLES.GUARDIAN(), who);
        if (from == GpuTypes.FacilityState.DRAW_FROZEN && to == GpuTypes.FacilityState.ACTIVE) {
            return ROLES.hasRole(ROLES.UNDERWRITER(), who);
        }
        if (
            to == GpuTypes.FacilityState.DELINQUENT
                || (from == GpuTypes.FacilityState.DELINQUENT && to == GpuTypes.FacilityState.ACTIVE)
        ) {
            return who == address(this); // system (GPU-041 monitor) — not externally callable yet
        }
        if (to == GpuTypes.FacilityState.DEFAULTED) return ROLES.hasRole(ADMIN_ROLE, who);
        if (to == GpuTypes.FacilityState.RECOVERY) return ROLES.hasRole(ROLES.SERVICER(), who);
        if (to == GpuTypes.FacilityState.CLOSED_WITH_LOSS) {
            return ROLES.hasRole(ADMIN_ROLE, who) || ROLES.hasRole(ROLES.TREASURY(), who);
        }
        if (to == GpuTypes.FacilityState.REPAID) return who == address(this); // system: debt_zero via repayFor
        if (to == GpuTypes.FacilityState.RELEASED) {
            return ROLES.hasRole(ROLES.SERVICER(), who) || ROLES.hasRole(ROLES.TREASURY(), who);
        }
        f;
        return false;
    }

    function _authorityLabel(GpuTypes.FacilityState from, GpuTypes.FacilityState to) internal pure returns (bytes32) {
        return keccak256(abi.encode("transition-authority", from, to));
    }

    /// @dev Guards named in the table that are computable on-chain today.
    function _guard(
        GpuTypes.FacilityId facilityId,
        Facility storage f,
        GpuTypes.FacilityState from,
        GpuTypes.FacilityState to
    ) internal view {
        if (from == GpuTypes.FacilityState.UNDER_REVIEW) {
            // credit_decision_approved: decision anchored, native-required manifest bound, control referenced
            if (!_anchorValid(facilityId)) revert AuthorizationMissingOrExpired(facilityId);
            if (f.controlAgreementId == bytes32(0)) revert ControlInsufficientOrStale(facilityId);
        }
        if (to == GpuTypes.FacilityState.ACTIVE && from != GpuTypes.FacilityState.DELINQUENT) {
            // control_grade_e2_effective / cause_cleared: agreement version fixed and usable at E2 now
            try IControlUsable(address(CONTROL))
                .requireUsable(f.controlAgreementId, f.controlVersion, GpuTypes.ControlGrade.E2) { }
            catch {
                revert ControlInsufficientOrStale(facilityId);
            }
        }
        if (to == GpuTypes.FacilityState.REPAID || to == GpuTypes.FacilityState.RELEASED) {
            uint256 debt = LEDGER.legalDebtAt(facilityId, uint64(block.timestamp));
            if (debt != 0) revert DebtOutstanding(facilityId, debt);
        }
    }

    function _setState(
        GpuTypes.FacilityId facilityId,
        Facility storage f,
        GpuTypes.FacilityState to,
        bytes32 trigger,
        address authority
    ) internal {
        GpuTypes.FacilityState from = f.state;
        f.state = to;
        IDebtLedgerState(address(LEDGER)).setState(facilityId, to);
        emit StateChanged(facilityId, from, to, trigger, authority);
    }

    // ------------------------------------------------------------------ token helper

    /// @dev transferFrom(msg.sender -> vault); tolerates non-returning tokens, reverts on `false` or revert.
    function _pullToVault(address asset, address from, uint256 amount) internal {
        (bool ok, bytes memory ret) =
            asset.call(abi.encodeWithSignature("transferFrom(address,address,uint256)", from, address(VAULT), amount));
        if (!ok || (ret.length != 0 && !abi.decode(ret, (bool)))) revert TransferFailed();
    }
}
