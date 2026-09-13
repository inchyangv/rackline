// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import { GpuTypes } from "./types/GpuTypes.sol";
import { IRepaymentRouter } from "./interfaces/IRepaymentRouter.sol";
import { IDebtLedger } from "./interfaces/IDebtLedger.sol";
import { ILendingVaultV2 } from "./interfaces/ILendingVaultV2.sol";
import { IProtocolRoles } from "./interfaces/IProtocolRoles.sol";

interface IERC20Minimal {
    function balanceOf(address) external view returns (uint256);
}

/// @dev Vault surface the router needs beyond ILendingVaultV2 (implemented by LendingVaultV2).
interface IVaultRefunds {
    function refundableOf(GpuTypes.FacilityId facilityId) external view returns (uint256);
    function refundExcess(GpuTypes.FacilityId facilityId, address to, uint256 amount) external;
}

/// @dev Facility wallet lookup on the CreditFacilityManager (`facilityInfo(...).wallet`).
interface IFacilityWallets {
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

    function facilityInfo(GpuTypes.FacilityId facilityId) external view returns (Facility memory);
    function syncRepaid(GpuTypes.FacilityId facilityId) external;
    function recoveryManager() external view returns (address);
}

interface IRecoveryObserver {
    function observeAllocation(GpuTypes.FacilityId facilityId, uint256 amount) external;
}

/**
 * @title RepaymentRouter
 * @notice The destination-side repayment entry (GPU-039, PIVOT §5–§7, §10.3; settlement-rails ADR §3 leg 4→5).
 *         Only loan currency that actually arrives here reduces debt: the router measures the token delta,
 *         asks the single ledger to split it (fees → unpaid interest → principal → excess) and reports the same
 *         numbers to the vault, which books `excess` as borrower-owned refundable cash (never LP NAV).
 * @dev Two arrival paths, one accounting:
 *      - direct: `repayFor` / `repayExact` — anyone (payer ≠ debtor allowed) pulls from `msg.sender` straight into
 *        the vault. `repayExact` caps the pull at the current legal debt (cap-before-transfer) so a direct payer
 *        never overpays; `repayFor` accepts an overpayment and credits it as refundable excess.
 *      - settlement leg: `recordDestinationReceipt` (TREASURY/RELAYER) pulls an arrived settlement into the router
 *        and holds it as *unallocated* (neither LP cash nor borrower cash); `allocate` moves a slice to the vault and
 *        applies it to one facility; `receiveSettlement` does both for one facility. A settlementId is recorded
 *        once and can never be allocated beyond what arrived.
 *      Invariant per leg: `received == feePaid + interestPaid + principalPaid + excess` (ledger `applied` + `excess`).
 *      No EvidenceBook, verifier, proof or signature is involved: a proof-service outage cannot block repayment,
 *      and a source-chain proof alone cannot change debt or NAV (R2-D07, PD-03/06, SR-D03/D08).
 *      Relation to `CreditFacilityManager.repayFor` (GPU-036): both call `ledger.allocate` + `vault.onRepayment`
 *      with identical accounting; the product path is this router (settlement ids, cap-before-transfer, refund
 *      authority). The manager's thin `repayFor` remains available for state transitions; the product settlement
 *      path uses this router for destination receipt identity, capped direct payments, and refund authority.
 */
contract RepaymentRouter is IRepaymentRouter {
    IProtocolRoles public immutable ROLES;
    IDebtLedger public immutable LEDGER;
    ILendingVaultV2 public immutable VAULT;
    IFacilityWallets public immutable FACILITIES; // optional: address(0) ⇒ refunds only by SERVICER to a wallet arg
    address public immutable ASSET;

    struct Receipt {
        uint256 total;
        uint256 allocated;
        bool exists;
    }

    mapping(bytes32 => Receipt) private _receipts;
    uint256 private _locked;

    error ZeroAddress();
    error UnknownFacility(GpuTypes.FacilityId facilityId);

    constructor(IProtocolRoles roles, IDebtLedger ledger, ILendingVaultV2 vault, IFacilityWallets facilities) {
        if (address(roles) == address(0) || address(ledger) == address(0) || address(vault) == address(0)) {
            revert ZeroAddress();
        }
        ROLES = roles;
        LEDGER = ledger;
        VAULT = vault;
        FACILITIES = facilities;
        ASSET = vault.asset();
    }

    modifier nonReentrant() {
        if (_locked == 1) revert Reentrancy();
        _locked = 1;
        _;
        _locked = 0;
    }

    modifier onlySettlementLeg() {
        if (!ROLES.hasRole(ROLES.TREASURY(), msg.sender) && !ROLES.hasRole(ROLES.RELAYER(), msg.sender)) {
            revert NotSettlementLeg(msg.sender);
        }
        _;
    }

    // ------------------------------------------------------------------ views

    function received(bytes32 settlementId) external view override returns (uint256 total, uint256 allocated) {
        Receipt storage r = _receipts[settlementId];
        return (r.total, r.allocated);
    }

    function unallocated(bytes32 settlementId) external view override returns (uint256) {
        Receipt storage r = _receipts[settlementId];
        return r.total - r.allocated;
    }

    function refundable(GpuTypes.FacilityId facilityId) external view override returns (uint256) {
        return IVaultRefunds(address(VAULT)).refundableOf(facilityId);
    }

    // ------------------------------------------------------------------ direct repayment (anyone)

    function repayFor(GpuTypes.FacilityId facilityId, uint256 amount, bytes32 settlementRef)
        external
        override
        nonReentrant
        returns (GpuTypes.RepayResult memory r)
    {
        if (amount == 0) revert ZeroAmount();
        _requireDebt(facilityId);
        uint256 got = _pullToVault(msg.sender, amount);
        r = _apply(facilityId, msg.sender, settlementRef, amount, got);
    }

    function repayExact(GpuTypes.FacilityId facilityId, uint256 maxAmount)
        external
        override
        nonReentrant
        returns (GpuTypes.RepayResult memory r)
    {
        if (maxAmount == 0) revert ZeroAmount();
        uint256 debt = _requireDebt(facilityId);
        uint256 amount = maxAmount < debt ? maxAmount : debt;
        uint256 got = _pullToVault(msg.sender, amount);
        r = _apply(facilityId, msg.sender, bytes32(0), amount, got);
    }

    // ------------------------------------------------------------------ settlement leg (TREASURY / RELAYER)

    /// @inheritdoc IRepaymentRouter
    /// @dev Funds are held by the router until allocated: unallocated settlement cash is in-flight/pending, never
    ///      LP NAV and never borrower refundable (settlement-rails ADR §3 leg 4).
    function recordDestinationReceipt(bytes32 settlementId, uint256 amount, bytes32 sourceRef)
        external
        override
        onlySettlementLeg
        nonReentrant
    {
        _record(settlementId, amount, sourceRef);
    }

    /// @inheritdoc IRepaymentRouter
    function allocate(bytes32 settlementId, GpuTypes.FacilityId facilityId, uint256 amount)
        external
        override
        onlySettlementLeg
        nonReentrant
        returns (GpuTypes.RepayResult memory r)
    {
        r = _allocateFromReceipt(settlementId, facilityId, amount);
    }

    function receiveSettlement(GpuTypes.FacilityId facilityId, bytes32 settlementId, uint256 amount)
        external
        override
        onlySettlementLeg
        nonReentrant
        returns (GpuTypes.RepayResult memory r)
    {
        uint256 got = _record(settlementId, amount, settlementId);
        r = _allocateFromReceipt(settlementId, facilityId, got);
    }

    // ------------------------------------------------------------------ refunds (borrower-owned excess)

    /// @inheritdoc IRepaymentRouter
    /// @dev Owner of the excess is the facility's borrower: only the linked wallet (self-service) or a SERVICER may
    ///      trigger the refund, and it can only go to the linked wallet.
    function refundExcess(GpuTypes.FacilityId facilityId, address to)
        external
        override
        nonReentrant
        returns (uint256 amount)
    {
        address wallet = _wallet(facilityId);
        if (to != wallet) revert NotRefundAuthority(facilityId, to);
        if (msg.sender != wallet && !ROLES.hasRole(ROLES.SERVICER(), msg.sender)) {
            revert NotRefundAuthority(facilityId, msg.sender);
        }
        amount = IVaultRefunds(address(VAULT)).refundableOf(facilityId);
        if (amount == 0) revert NothingToRefund(facilityId);
        IVaultRefunds(address(VAULT)).refundExcess(facilityId, wallet, amount);
        emit ExcessRefunded(facilityId, wallet, amount);
    }

    // ------------------------------------------------------------------ internals

    function _requireDebt(GpuTypes.FacilityId facilityId) internal view returns (uint256 debt) {
        debt = LEDGER.legalDebtAt(facilityId, uint64(block.timestamp)); // reverts FacilityUnknown
        if (debt == 0) revert NothingToRepay(facilityId);
    }

    function _record(bytes32 settlementId, uint256 amount, bytes32 sourceRef) internal returns (uint256 got) {
        if (amount == 0) revert ZeroAmount();
        if (_receipts[settlementId].exists) revert DuplicateSettlement(settlementId);
        uint256 before = IERC20Minimal(ASSET).balanceOf(address(this));
        _call(abi.encodeWithSignature("transferFrom(address,address,uint256)", msg.sender, address(this), amount));
        got = IERC20Minimal(ASSET).balanceOf(address(this)) - before;
        if (got == 0) revert TransferFailed();
        _receipts[settlementId] = Receipt({ total: got, allocated: 0, exists: true });
        emit DestinationReceiptRecorded(settlementId, ASSET, got, sourceRef);
    }

    function _allocateFromReceipt(bytes32 settlementId, GpuTypes.FacilityId facilityId, uint256 amount)
        internal
        returns (GpuTypes.RepayResult memory r)
    {
        Receipt storage rc = _receipts[settlementId];
        if (!rc.exists) revert UnknownSettlement(settlementId);
        if (amount == 0) revert ZeroAmount();
        if (rc.allocated + amount > rc.total) {
            revert AllocationExceedsReceipt(settlementId, rc.allocated + amount, rc.total);
        }
        // A settlement may arrive after a direct payer fully repaid. It still belongs to this facility: book
        // zero applied / all excess, so the linked borrower can refund it rather than stranding arrived cash.
        LEDGER.legalDebtAt(facilityId, uint64(block.timestamp)); // existence check
        rc.allocated += amount;
        uint256 before = IERC20Minimal(ASSET).balanceOf(address(VAULT));
        _call(abi.encodeWithSignature("transfer(address,uint256)", address(VAULT), amount));
        uint256 got = IERC20Minimal(ASSET).balanceOf(address(VAULT)) - before;
        if (got != amount) revert TransferFailed(); // the router holds a standard balance; any shortfall is fatal
        r = _apply(facilityId, msg.sender, settlementId, amount, got);
        emit AllocationApplied(settlementId, facilityId, amount, r.applied, r.excess);
    }

    /// @dev Same accounting for every path: split what arrived, report the same split to the vault.
    function _apply(GpuTypes.FacilityId facilityId, address payer, bytes32 ref, uint256 requested, uint256 got)
        internal
        returns (GpuTypes.RepayResult memory r)
    {
        r = LEDGER.allocate(facilityId, got);
        r.requested = requested;
        VAULT.onRepayment(facilityId, r);
        if (address(FACILITIES) != address(0)) {
            address recovery = FACILITIES.recoveryManager();
            if (recovery != address(0)) IRecoveryObserver(recovery).observeAllocation(facilityId, r.applied);
            if (r.newDebt == 0) FACILITIES.syncRepaid(facilityId);
        }
        emit Repaid(
            facilityId,
            payer,
            ref,
            requested,
            r.received,
            r.applied,
            r.feePaid,
            r.interestPaid,
            r.principalPaid,
            r.excess,
            r.newDebt
        );
    }

    function _pullToVault(address from, uint256 amount) internal returns (uint256 got) {
        uint256 before = IERC20Minimal(ASSET).balanceOf(address(VAULT));
        _call(abi.encodeWithSignature("transferFrom(address,address,uint256)", from, address(VAULT), amount));
        got = IERC20Minimal(ASSET).balanceOf(address(VAULT)) - before;
        if (got == 0) revert TransferFailed();
    }

    /// @dev Non-returning (USDT-style) and bool-returning tokens are both accepted; `false` or revert fails.
    function _call(bytes memory data) internal {
        (bool ok, bytes memory ret) = ASSET.call(data);
        if (!ok || (ret.length != 0 && !abi.decode(ret, (bool)))) revert TransferFailed();
        if (ret.length == 0 && ASSET.code.length == 0) revert TransferFailed();
    }

    function _wallet(GpuTypes.FacilityId facilityId) internal view returns (address wallet) {
        if (address(FACILITIES) == address(0)) revert UnknownFacility(facilityId);
        IFacilityWallets.Facility memory f = FACILITIES.facilityInfo(facilityId);
        if (!f.exists || f.wallet == address(0)) revert UnknownFacility(facilityId);
        wallet = f.wallet;
    }
}
