// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import { GpuTypes } from "./types/GpuTypes.sol";
import { IProtocolRoles } from "./interfaces/IProtocolRoles.sol";
import { IDebtLedger } from "./interfaces/IDebtLedger.sol";
import { CreditFacilityManager } from "./CreditFacilityManager.sol";
import { LendingVaultV2 } from "./LendingVaultV2.sol";
import { IRepaymentRouter } from "./interfaces/IRepaymentRouter.sol";

interface IRecoveryToken {
    function balanceOf(address) external view returns (uint256);
}

/// @notice Contractual due schedule and two-role default/write-off decisions. No API/uptime/proof status input
/// exists. Only explicitly pledged, physically funded reserves may be applied; borrower refunds stay in Vault.
contract RecoveryManager {
    IProtocolRoles public immutable ROLES;
    IDebtLedger public immutable LEDGER;
    CreditFacilityManager public immutable MANAGER;
    LendingVaultV2 public immutable VAULT;
    IRepaymentRouter public immutable ROUTER;
    address public immutable ASSET;

    struct Schedule {
        uint64 dueAt;
        uint64 graceSeconds;
        uint64 disputeUntil;
        uint256 dueAmount;
        uint256 paidAtSchedule;
        uint256 paidSinceSchedule;
        uint256 pledgedReserve;
        address reserveOwner;
        bool defaultApproved;
        bool disputed;
        bool writtenOff;
        bytes32 defaultReason;
        bytes32 writeOffApproval;
    }
    mapping(GpuTypes.FacilityId => Schedule) private _schedules;
    mapping(GpuTypes.FacilityId => uint256) public totalAllocated;
    mapping(bytes32 => bool) public lossUsed;
    uint256 private _lock;

    error NotRole();
    error InvalidSchedule();
    error DisputeOpen();
    error NotDue();
    error NotApproved();
    error DuplicateLoss();
    error TransferFailed();
    error NotReserveOwner();
    error OutstandingDebt();
    error Reentrancy();

    event ScheduleSet(GpuTypes.FacilityId indexed facilityId, uint64 dueAt, uint64 graceSeconds, uint256 dueAmount);
    event DisputeSet(GpuTypes.FacilityId indexed facilityId, bool disputed, uint64 disputeUntil);
    event DefaultApproved(GpuTypes.FacilityId indexed facilityId, bytes32 indexed reason);
    event ReserveFunded(GpuTypes.FacilityId indexed facilityId, address indexed owner, uint256 amount);
    event ReserveApplied(GpuTypes.FacilityId indexed facilityId, uint256 amount);
    event LossApplied(GpuTypes.FacilityId indexed facilityId, bytes32 indexed lossId, uint256 amount, bool writeOff);

    constructor(
        IProtocolRoles roles,
        IDebtLedger ledger,
        CreditFacilityManager manager,
        LendingVaultV2 vault,
        IRepaymentRouter router
    ) {
        ROLES = roles;
        LEDGER = ledger;
        MANAGER = manager;
        VAULT = vault;
        ROUTER = router;
        ASSET = vault.asset();
    }

    modifier role(bytes32 required) {
        if (!ROLES.hasRole(required, msg.sender)) revert NotRole();
        _;
    }
    modifier nonReentrant() {
        if (_lock != 0) revert Reentrancy();
        _lock = 1;
        _;
        _lock = 0;
    }

    function schedule(GpuTypes.FacilityId id) external view returns (Schedule memory) {
        return _schedules[id];
    }

    /// @notice Schedule changes require current performing status and cannot erase already-overdue installments.
    function setSchedule(GpuTypes.FacilityId id, uint64 dueAt, uint64 grace, uint64 disputeWindow, uint256 dueAmount)
        external
        role(ROLES.UNDERWRITER())
    {
        Schedule storage s = _schedules[id];
        GpuTypes.FacilityState state = MANAGER.state(id);
        if (state != GpuTypes.FacilityState.ACTIVE && state != GpuTypes.FacilityState.CONTROL_PENDING) {
            revert InvalidSchedule();
        }
        if (dueAt <= block.timestamp || grace == 0 || dueAmount == 0 || disputeWindow > grace) {
            revert InvalidSchedule();
        }
        if (s.dueAt != 0 && (s.dueAt <= block.timestamp || s.defaultApproved || s.writtenOff)) {
            revert InvalidSchedule();
        }
        s.dueAt = dueAt;
        s.graceSeconds = grace;
        s.disputeUntil = dueAt + disputeWindow;
        s.dueAmount = dueAmount;
        s.paidAtSchedule = totalAllocated[id];
        emit ScheduleSet(id, dueAt, grace, dueAmount);
    }

    /// @notice The immutable manager/router report allocation only after actual cash has reached the Vault.
    function observeAllocation(GpuTypes.FacilityId id, uint256 amount) external {
        if (msg.sender != address(ROUTER) && msg.sender != address(MANAGER)) revert NotRole();
        totalAllocated[id] += amount;
    }

    function installmentPaid(GpuTypes.FacilityId id) public view returns (bool) {
        Schedule storage s = _schedules[id];
        return LEDGER.legalDebtAt(id, uint64(block.timestamp)) == 0
            || (s.dueAt != 0 && totalAllocated[id] - s.paidAtSchedule >= s.dueAmount);
    }

    function markDelinquent(GpuTypes.FacilityId id) external {
        Schedule storage s = _schedules[id];
        if (s.dueAt == 0 || block.timestamp <= s.dueAt || installmentPaid(id)) revert NotDue();
        MANAGER.recoveryTransition(id, GpuTypes.FacilityState.DELINQUENT, "installment_overdue");
    }

    function cure(GpuTypes.FacilityId id) external {
        if (!installmentPaid(id)) revert NotDue();
        if (LEDGER.legalDebtAt(id, uint64(block.timestamp)) == 0) MANAGER.syncRepaid(id);
        else MANAGER.recoveryTransition(id, GpuTypes.FacilityState.ACTIVE, "installment_cured");
        _schedules[id].defaultApproved = false;
    }

    function setDispute(GpuTypes.FacilityId id, bool disputed) external role(ROLES.SERVICER()) {
        Schedule storage s = _schedules[id];
        if (s.dueAt == 0) revert InvalidSchedule();
        s.disputed = disputed;
        if (disputed) s.defaultApproved = false;
        emit DisputeSet(id, disputed, s.disputeUntil);
    }

    function approveDefault(GpuTypes.FacilityId id, bytes32 reason) external role(ROLES.UNDERWRITER()) {
        _requireDefaultDue(id);
        if (reason == bytes32(0)) revert NotApproved();
        _schedules[id].defaultApproved = true;
        _schedules[id].defaultReason = reason;
        emit DefaultApproved(id, reason);
    }

    function declareDefault(GpuTypes.FacilityId id) external role(ROLES.GUARDIAN()) {
        _requireDefaultDue(id);
        Schedule storage s = _schedules[id];
        if (!s.defaultApproved) revert NotApproved();
        s.defaultApproved = false;
        MANAGER.recoveryTransition(id, GpuTypes.FacilityState.DEFAULTED, s.defaultReason);
        LEDGER.freezeAccrual(id);
    }

    function _requireDefaultDue(GpuTypes.FacilityId id) internal view {
        Schedule storage s = _schedules[id];
        if (s.dueAt == 0 || block.timestamp <= s.dueAt + s.graceSeconds || installmentPaid(id)) revert NotDue();
        if (s.disputed || block.timestamp <= s.disputeUntil) revert DisputeOpen();
        if (MANAGER.state(id) != GpuTypes.FacilityState.DELINQUENT) revert NotDue();
    }

    function beginRecovery(GpuTypes.FacilityId id) external role(ROLES.SERVICER()) {
        MANAGER.recoveryTransition(id, GpuTypes.FacilityState.RECOVERY, "recovery_opened");
    }

    /// @notice A funding call is explicit reserve consent by its owner. It never appropriates refundable cash.
    function fundReserve(GpuTypes.FacilityId id, uint256 amount) external nonReentrant {
        if (!MANAGER.facilityInfo(id).exists) revert InvalidSchedule();
        Schedule storage s = _schedules[id];
        if (amount == 0 || (s.reserveOwner != address(0) && s.reserveOwner != msg.sender)) revert NotReserveOwner();
        uint256 before_ = IRecoveryToken(ASSET).balanceOf(address(this));
        _call(abi.encodeWithSignature("transferFrom(address,address,uint256)", msg.sender, address(this), amount));
        if (IRecoveryToken(ASSET).balanceOf(address(this)) - before_ != amount) revert TransferFailed();
        s.reserveOwner = msg.sender;
        s.pledgedReserve += amount;
        emit ReserveFunded(id, msg.sender, amount);
    }

    function applyReserve(GpuTypes.FacilityId id) external role(ROLES.SERVICER()) nonReentrant {
        _applyReserve(id);
    }

    function _applyReserve(GpuTypes.FacilityId id) internal {
        GpuTypes.FacilityState state = MANAGER.state(id);
        if (state != GpuTypes.FacilityState.DEFAULTED && state != GpuTypes.FacilityState.RECOVERY) revert NotDue();
        Schedule storage s = _schedules[id];
        uint256 debt = LEDGER.legalDebtAt(id, uint64(block.timestamp));
        uint256 amount = s.pledgedReserve < debt ? s.pledgedReserve : debt;
        if (amount == 0) return;
        s.pledgedReserve -= amount;
        _call(abi.encodeWithSignature("approve(address,uint256)", address(ROUTER), amount));
        ROUTER.repayExact(id, amount);
        _call(abi.encodeWithSignature("approve(address,uint256)", address(ROUTER), 0));
        emit ReserveApplied(id, amount);
    }

    function returnReserve(GpuTypes.FacilityId id) external nonReentrant {
        Schedule storage s = _schedules[id];
        if (msg.sender != s.reserveOwner) revert NotReserveOwner();
        if (LEDGER.legalDebtAt(id, uint64(block.timestamp)) != 0) revert OutstandingDebt();
        uint256 amount = s.pledgedReserve;
        s.pledgedReserve = 0;
        _call(abi.encodeWithSignature("transfer(address,uint256)", msg.sender, amount));
    }

    function impair(GpuTypes.FacilityId id, bytes32 lossId, uint256 amount) external role(ROLES.UNDERWRITER()) {
        if (lossId == bytes32(0) || lossUsed[lossId]) revert DuplicateLoss();
        lossUsed[lossId] = true;
        VAULT.recognizeImpairment(id, amount);
        emit LossApplied(id, lossId, amount, false);
    }

    function reverseImpairment(GpuTypes.FacilityId id, uint256 amount) external role(ROLES.UNDERWRITER()) {
        VAULT.reverseImpairment(id, amount);
    }

    function approveWriteOff(GpuTypes.FacilityId id, bytes32 lossId) external role(ROLES.UNDERWRITER()) {
        if (lossId == bytes32(0) || lossUsed[lossId] || MANAGER.state(id) != GpuTypes.FacilityState.RECOVERY) {
            revert NotApproved();
        }
        _schedules[id].writeOffApproval = lossId;
    }

    function writeOff(GpuTypes.FacilityId id, bytes32 lossId) external role(ROLES.TREASURY()) nonReentrant {
        Schedule storage s = _schedules[id];
        if (lossUsed[lossId] || s.writtenOff) revert DuplicateLoss();
        if (lossId == bytes32(0) || s.writeOffApproval != lossId) revert NotApproved();
        _applyReserve(id);
        uint256 debt = LEDGER.legalDebtAt(id, uint64(block.timestamp));
        if (debt == 0) {
            MANAGER.syncRepaid(id);
            return;
        }
        lossUsed[lossId] = true;
        s.writtenOff = true;
        VAULT.writeOff(id);
        MANAGER.recoveryTransition(id, GpuTypes.FacilityState.CLOSED_WITH_LOSS, lossId);
        emit LossApplied(id, lossId, debt, true);
    }

    function _call(bytes memory data) internal {
        (bool ok, bytes memory result) = ASSET.call(data);
        if (!ok || (result.length != 0 && !abi.decode(result, (bool)))) revert TransferFailed();
    }
}
