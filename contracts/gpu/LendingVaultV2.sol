// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import { GpuTypes } from "./types/GpuTypes.sol";
import { ILendingVaultV2 } from "./interfaces/ILendingVaultV2.sol";
import { IDebtLedger } from "./interfaces/IDebtLedger.sol";
import { IProtocolRoles } from "./interfaces/IProtocolRoles.sol";
import { Math } from "../../lib/openzeppelin-contracts/contracts/utils/math/Math.sol";

interface IERC20Minimal {
    function balanceOf(address) external view returns (uint256);
    function transfer(address to, uint256 amount) external returns (bool);
    function transferFrom(address from, address to, uint256 amount) external returns (bool);
}

/**
 * @title LendingVaultV2
 * @notice LP book of the GPU receivables facility (GPU-034; docs/gpu/accounting.md §4–§6). Holds LP-owned cash,
 *         values performing loan receivables from the single debt ledger, records impairment/write-off/recovery on
 *         its own book, and issues virtual-offset shares.
 * @dev Accounting boundaries (AC-06/09/10/13, AR-02/08, R2-D07):
 *      - NAV = LP cash + Σ performing legal debt (ledger `legalDebtAt`, principal + fees + unpaid interest)
 *              − Σ impairment of performing facilities. Written-off facilities leave the book (their legal debt
 *              persists in the ledger; recovery belongs to current holders or the facility's closed epoch).
 *      - LP cash = token balance − borrower-owned balances − funded withdrawal claims − closed-epoch recovery.
 *        Borrower money is never NAV and can
 *        never be withdrawn by LPs; direct token transfers are LP cash (`DonationAbsorbed`), never a repayment.
 *      - The vault never computes interest: it reads the ledger. It has no rate parameter.
 *      - Shares: `shares = assets × (S + 1000) / (NAV + 1)`, `assets = shares × (NAV + 1) / (S + 1000)`, floor both
 *        ways; the first-depositor donation attack is unprofitable (AC-10). Residual rounding favours the vault.
 *      - GPU-042: FIFO requests lock shares, not a fixed NAV claim. Fills burn shares at current NAV and reserve
 *        real cash. Pending requests block direct withdrawals and new lending; funded claims are off-NAV.
 *      - Total loss requires an explicit guardian epoch rollover before new deposits. Closed balances/allowances
 *        cannot migrate into new shares; tagged late recovery remains a pro-rata claim of closed-epoch holders.
 *      Roles / wiring: `MANAGER` (allow-listed by ADMIN; the CreditFacilityManager of GPU-036 / router of GPU-039)
 *      is the single ledger writer and moves cash through `lend` / `onRepayment` / `refundExcess` / `recordRecovery`.
 *      Ordering contract: the manager records the draw in the ledger and calls `lend` in the same transaction; the
 *      manager calls `ledger.allocate` and passes the result to `onRepayment` after the tokens arrived (the vault
 *      measures the arrival). GUARDIAN/UNDERWRITER recognise impairment; GUARDIAN writes off (credit committee +
 *      treasury decision recorded off-chain, docs/gpu/permissions-and-states.md); nothing writes off automatically.
 *      GUARDIAN may pause deposits; repayments, impairment and withdrawals are never paused here (GPU-043 wiring).
 *      ERC-4626: NOT implemented. Conformant parts: `asset()`, `totalAssets()`, `convertToShares/Assets` semantics
 *      with virtual offset, ERC-20 share token. Non-conformant on purpose: `deposit(assets, minShares)` and
 *      `withdraw(shares, minAssets)` carry slippage guards and act on `msg.sender` only; no `mint`/`redeem`/receiver
 *      /owner variants; `maxWithdraw` is cash-limited.
 */
contract LendingVaultV2 is ILendingVaultV2 {
    // ------------------------------------------------------------------ ERC-20 share token (minimal)

    string public constant name = "Rackline GPU Facility LP Share";
    string public constant symbol = "rkLP";
    uint8 public constant decimals = 18;
    uint256 public override totalShares;
    uint64 public override currentEpoch = 1;
    mapping(uint64 => mapping(address => uint256)) private _shares;
    mapping(uint64 => mapping(address => mapping(address => uint256))) private _allowances;
    mapping(uint64 => mapping(address => uint256)) private _lockedShares;

    // Filled withdrawal cash and closed-epoch recoveries are liabilities, not current LP NAV/liquidity.
    uint256 public totalWithdrawalReserved;
    uint256 public totalRecoveryReserved;
    uint256 public pendingWithdrawalShares;
    uint256 public nextWithdrawalId = 1;
    uint256 public withdrawalHead = 1;
    uint64 public constant WITHDRAWAL_TTL = 7 days;
    uint256 public constant MAX_PROCESS_REQUESTS = 50;
    mapping(uint256 => WithdrawalRequest) private _withdrawals;
    mapping(uint64 => uint256) public closedEpochShares;
    mapping(uint64 => uint256) public epochRecoveryReceived;
    mapping(uint64 => mapping(address => uint256)) public epochRecoveryClaimed;
    mapping(GpuTypes.FacilityId => uint64) public writeOffEpoch;
    bool public epochRolloverRequired;

    event Transfer(address indexed from, address indexed to, uint256 value);
    event Approval(address indexed owner, address indexed spender, uint256 value);

    // ------------------------------------------------------------------ config / state

    uint256 public constant VIRTUAL_SHARES = 1000;
    uint256 public constant VIRTUAL_ASSETS = 1;
    bytes32 public constant ADMIN_ROLE = keccak256("ADMIN");

    IProtocolRoles public immutable ROLES;
    IDebtLedger public immutable LEDGER;
    address private immutable _ASSET;

    mapping(address => bool) public isManager;
    bool public wiringFinalized;
    address public recoveryManager;
    bool public depositsPaused;

    mapping(GpuTypes.FacilityId => uint256) public impairmentOf; // performing facilities only
    uint256 public totalImpairment;
    mapping(GpuTypes.FacilityId => bool) public isWrittenOff;
    GpuTypes.FacilityId[] private _writtenOff;
    mapping(GpuTypes.FacilityId => uint256) public refundableOf; // borrower-owned excess repayments
    uint256 public totalBorrowerOwned;
    uint256 private _trackedBalance; // last observed token balance, to detect donations vs. repayments

    uint256 private _lock = 1;

    event ManagerSet(address indexed manager, bool enabled);
    event DepositsPaused(bool paused);
    event ExcessRefunded(GpuTypes.FacilityId indexed facilityId, address indexed to, uint256 amount);
    event ImpairmentReversed(GpuTypes.FacilityId indexed facilityId, uint256 amount);

    error NotAdmin(address caller);
    error NotGuardianOrUnderwriter(address caller);
    error NotGuardian(address caller);
    error Paused();
    error ZeroAddress();
    error ZeroAmount();
    error TransferFailed();
    error Reentrancy();
    error CashNotReceived(uint256 expected, uint256 measured);
    error FacilityWrittenOff(GpuTypes.FacilityId facilityId);
    error FacilityNotWrittenOff(GpuTypes.FacilityId facilityId);
    error RefundExceedsBalance(uint256 requested, uint256 available);
    error WithdrawalQueueActive();
    error UnknownWithdrawal(uint256 requestId);
    error NotWithdrawalOwner(address caller);
    error NoPendingWithdrawal(uint256 requestId);
    error NoClaimableAssets();
    error LockedShares(uint256 requested, uint256 unlocked);
    error InvalidProcessLimit();
    error EpochRecapitalizationRequired();
    error EpochNotFullyWrittenOff();
    error EpochNotClosed(uint64 epoch);
    error WiringFinalized();
    event WiringSealed();
    event RecoveryManagerBound(address indexed manager);
    error OnlyRecoveryManager();

    constructor(IProtocolRoles roles, IDebtLedger ledger, address asset_) {
        if (address(roles) == address(0) || address(ledger) == address(0) || asset_ == address(0)) {
            revert ZeroAddress();
        }
        ROLES = roles;
        LEDGER = ledger;
        _ASSET = asset_;
    }

    modifier nonReentrant() {
        if (_lock != 1) revert Reentrancy();
        _lock = 2;
        _;
        _lock = 1;
    }

    modifier onlyAdmin() {
        if (!ROLES.hasRole(ADMIN_ROLE, msg.sender)) revert NotAdmin(msg.sender);
        _;
    }

    modifier onlyManager() {
        if (!isManager[msg.sender]) revert OnlyManager(msg.sender);
        _;
    }

    modifier onlyGuardianOrUnderwriter() {
        if (recoveryManager != address(0) && msg.sender != recoveryManager) revert OnlyRecoveryManager();
        if (!ROLES.hasRole(ROLES.GUARDIAN(), msg.sender) && !ROLES.hasRole(ROLES.UNDERWRITER(), msg.sender)) {
            revert NotGuardianOrUnderwriter(msg.sender);
        }
        _;
    }

    modifier onlyGuardian() {
        if (!ROLES.hasRole(ROLES.GUARDIAN(), msg.sender)) revert NotGuardian(msg.sender);
        _;
    }

    // ------------------------------------------------------------------ admin / guardian

    function setManager(address manager, bool enabled) external onlyAdmin {
        if (wiringFinalized) revert WiringFinalized();
        if (manager == address(0)) revert ZeroAddress();
        isManager[manager] = enabled;
        emit ManagerSet(manager, enabled);
    }

    function finalizeWiring() external onlyAdmin {
        if (wiringFinalized) revert WiringFinalized();
        wiringFinalized = true;
        emit WiringSealed();
    }

    function bindRecoveryManager(address manager) external onlyAdmin {
        if (wiringFinalized || recoveryManager != address(0)) revert WiringFinalized();
        if (manager.code.length == 0) revert ZeroAddress();
        recoveryManager = manager;
        emit RecoveryManagerBound(manager);
    }

    /// @notice Deposit pause only. Withdrawals, repayments, impairment and recovery are never paused here.
    function setDepositsPaused(bool paused) external onlyGuardian {
        depositsPaused = paused;
        emit DepositsPaused(paused);
    }

    // ------------------------------------------------------------------ views

    function asset() external view override returns (address) {
        return _ASSET;
    }

    /// @notice Unreserved LP cash. Queue priority also blocks new loans/immediate withdrawals.
    function availableCash() public view override returns (uint256) {
        if (pendingWithdrawalShares != 0 || epochRolloverRequired) return 0;
        return _lpCash();
    }

    /// @notice Liquid current LP assets, even while waiting to service a FIFO request. Not all are free to lend.
    function liquidLpCash() external view returns (uint256) {
        return _lpCash();
    }

    function _lpCash() internal view returns (uint256) {
        uint256 bal = IERC20Minimal(_ASSET).balanceOf(address(this));
        uint256 liabilities = totalBorrowerOwned + totalWithdrawalReserved + totalRecoveryReserved;
        return bal > liabilities ? bal - liabilities : 0;
    }

    /// @notice Σ legal debt of performing facilities as of now, straight from the ledger (no interest math here).
    function performingReceivables() public view returns (uint256) {
        uint64 nowTs = uint64(block.timestamp);
        uint256 total = LEDGER.totalLegalDebtAt(nowTs);
        for (uint256 i = 0; i < _writtenOff.length; i++) {
            total -= LEDGER.legalDebtAt(_writtenOff[i], nowTs);
        }
        return total;
    }

    function nav() public view override returns (uint256) {
        uint256 gross = _lpCash() + performingReceivables();
        return gross > totalImpairment ? gross - totalImpairment : 0;
    }

    /// @notice ERC-4626-style alias of `nav()`.
    function totalAssets() external view returns (uint256) {
        return nav();
    }

    function convertToShares(uint256 assets) public view returns (uint256) {
        return Math.mulDiv(assets, totalShares + VIRTUAL_SHARES, nav() + VIRTUAL_ASSETS);
    }

    function convertToAssets(uint256 shares) public view returns (uint256) {
        return Math.mulDiv(shares, nav() + VIRTUAL_ASSETS, totalShares + VIRTUAL_SHARES);
    }

    function previewDeposit(uint256 assets) public view override returns (uint256 shares) {
        return convertToShares(assets);
    }

    function previewWithdraw(uint256 shares) public view override returns (uint256 assets) {
        return convertToAssets(shares);
    }

    /// @notice Assets `lp` could withdraw now: min(redeemable, cash). The rest waits for cash (queue = GPU-042).
    function maxWithdraw(address lp) external view returns (uint256) {
        uint256 redeemable = convertToAssets(balanceOf(lp) - _lockedShares[currentEpoch][lp]);
        uint256 cash = availableCash();
        return redeemable < cash ? redeemable : cash;
    }

    function writtenOffCount() external view returns (uint256) {
        return _writtenOff.length;
    }

    function balanceOf(address lp) public view returns (uint256) {
        return _shares[currentEpoch][lp];
    }

    function allowance(address owner, address spender) external view returns (uint256) {
        return _allowances[currentEpoch][owner][spender];
    }

    function sharesOfEpoch(uint64 epoch, address lp) external view override returns (uint256) {
        return _shares[epoch][lp];
    }

    function lockedShares(uint64 epoch, address lp) external view returns (uint256) {
        return _lockedShares[epoch][lp];
    }

    // ------------------------------------------------------------------ LP actions

    function deposit(uint256 assets, uint256 minShares) external override nonReentrant returns (uint256 shares) {
        if (depositsPaused) revert Paused();
        if (assets == 0) revert ZeroAmount();
        _absorbDonation();
        if (epochRolloverRequired || (totalShares != 0 && nav() == 0)) revert EpochRecapitalizationRequired();
        shares = convertToShares(assets);
        if (shares == 0) revert ZeroShares();
        if (shares < minShares) revert SlippageExceeded(shares, minShares);
        uint256 received = _pull(msg.sender, assets);
        if (received != assets) revert CashNotReceived(assets, received);
        _mint(msg.sender, shares);
        _trackedBalance = IERC20Minimal(_ASSET).balanceOf(address(this));
        emit Deposited(msg.sender, assets, shares);
    }

    function withdraw(uint256 shares, uint256 minAssets) external override nonReentrant returns (uint256 assets) {
        if (shares == 0) revert ZeroShares();
        if (epochRolloverRequired) revert EpochRecapitalizationRequired();
        if (pendingWithdrawalShares != 0) revert WithdrawalQueueActive();
        _absorbDonation();
        assets = convertToAssets(shares);
        if (assets == 0) revert ZeroAmount();
        if (assets < minAssets) revert SlippageExceeded(assets, minAssets);
        uint256 cash = availableCash();
        if (assets > cash) revert InsufficientCash(assets, cash);
        _burn(msg.sender, shares);
        _push(msg.sender, assets);
        _trackedBalance = IERC20Minimal(_ASSET).balanceOf(address(this));
        emit Withdrawn(msg.sender, assets, shares);
    }

    // ------------------------------------------------------------------ FIFO withdrawals (GPU-042)

    function withdrawalRequest(uint256 id) external view override returns (WithdrawalRequest memory) {
        if (_withdrawals[id].owner == address(0)) revert UnknownWithdrawal(id);
        return _withdrawals[id];
    }

    function requestWithdrawal(uint256 shares, uint256 minAssets) external override nonReentrant returns (uint256 id) {
        if (shares == 0) revert ZeroShares();
        if (epochRolloverRequired) revert EpochRecapitalizationRequired();
        uint256 unlocked = balanceOf(msg.sender) - _lockedShares[currentEpoch][msg.sender];
        if (shares > unlocked) revert LockedShares(shares, unlocked);
        uint256 quoted = convertToAssets(shares);
        if (quoted == 0) revert ZeroAmount();
        if (minAssets > quoted) revert SlippageExceeded(quoted, minAssets);
        id = nextWithdrawalId++;
        uint64 expiresAt = uint64(block.timestamp + WITHDRAWAL_TTL);
        _withdrawals[id] = WithdrawalRequest({
            owner: msg.sender,
            epoch: currentEpoch,
            expiresAt: expiresAt,
            sharesRequested: shares,
            sharesRemaining: shares,
            minAssets: minAssets,
            assetsReserved: 0,
            assetsClaimed: 0,
            cancelled: false
        });
        _lockedShares[currentEpoch][msg.sender] += shares;
        pendingWithdrawalShares += shares;
        emit WithdrawalRequested(id, msg.sender, currentEpoch, shares, minAssets, expiresAt);
    }

    /// @notice Cancel only the unfilled shares. Funded cash stays claimable; no fixed-price refund is invented.
    function cancelWithdrawal(uint256 id) external override nonReentrant {
        WithdrawalRequest storage r = _withdrawals[id];
        if (r.owner == address(0)) revert UnknownWithdrawal(id);
        if (msg.sender != r.owner) revert NotWithdrawalOwner(msg.sender);
        if (r.sharesRemaining == 0) revert NoPendingWithdrawal(id);
        _cancelWithdrawal(id, r);
    }

    function _cancelWithdrawal(uint256 id, WithdrawalRequest storage r) internal {
        uint256 shares = r.sharesRemaining;
        _lockedShares[r.epoch][r.owner] -= shares;
        if (r.epoch == currentEpoch) pendingWithdrawalShares -= shares;
        r.sharesRemaining = 0;
        r.cancelled = true;
        emit WithdrawalCancelled(id, shares);
    }

    /// @notice Permissionless bounded FIFO service. Slippage-blocked head waits for cancellation/7-day expiry.
    ///         Each partial fill is priced at current NAV; only its measured available cash becomes fixed debt.
    function processWithdrawals(uint256 maxRequests)
        external
        override
        nonReentrant
        returns (uint256 filledRequests, uint256 assetsReserved)
    {
        if (maxRequests == 0 || maxRequests > MAX_PROCESS_REQUESTS) revert InvalidProcessLimit();
        if (epochRolloverRequired) revert EpochRecapitalizationRequired();
        _absorbDonation();
        for (uint256 visited; visited < maxRequests && withdrawalHead < nextWithdrawalId; visited++) {
            uint256 id = withdrawalHead;
            WithdrawalRequest storage r = _withdrawals[id];
            if (r.sharesRemaining == 0 || r.epoch != currentEpoch) {
                withdrawalHead++;
                continue;
            }
            if (block.timestamp >= r.expiresAt) {
                _cancelWithdrawal(id, r);
                withdrawalHead++;
                continue;
            }
            uint256 cash = _lpCash();
            if (cash == 0 || nav() == 0) break;
            uint256 shares = r.sharesRemaining;
            uint256 assets = convertToAssets(shares);
            if (assets > cash) {
                shares = Math.mulDiv(cash, totalShares + VIRTUAL_SHARES, nav() + VIRTUAL_ASSETS);
                if (shares == 0) break;
                assets = convertToAssets(shares);
            }
            if (assets == 0) break;
            // A rate floor, not an initial fixed-price promise. Ceil keeps partial fills above consented minimum.
            uint256 minimum = Math.mulDiv(r.minAssets, shares, r.sharesRequested, Math.Rounding.Ceil);
            if (assets < minimum) break;
            r.sharesRemaining -= shares;
            r.assetsReserved += assets;
            _lockedShares[currentEpoch][r.owner] -= shares;
            pendingWithdrawalShares -= shares;
            _burn(r.owner, shares);
            totalWithdrawalReserved += assets;
            assetsReserved += assets;
            filledRequests++;
            emit WithdrawalFilled(id, shares, assets);
            if (r.sharesRemaining == 0) withdrawalHead++;
            else break;
        }
    }

    function claimWithdrawal(uint256 id) external override nonReentrant returns (uint256 assets) {
        WithdrawalRequest storage r = _withdrawals[id];
        if (r.owner == address(0)) revert UnknownWithdrawal(id);
        if (msg.sender != r.owner) revert NotWithdrawalOwner(msg.sender);
        assets = r.assetsReserved - r.assetsClaimed;
        if (assets == 0) revert NoClaimableAssets();
        r.assetsClaimed += assets;
        totalWithdrawalReserved -= assets;
        _push(r.owner, assets);
        _trackedBalance = IERC20Minimal(_ASSET).balanceOf(address(this));
        emit WithdrawalClaimed(id, r.owner, assets);
    }

    // ------------------------------------------------------------------ fully lost epoch / preserved recovery rights

    /// @notice Guardian may isolate an epoch latched at full write-off/zero NAV, not a partially valuable pool.
    ///         Frozen old shares (including queued shares) retain recovery rights; no balance is silently reminted.
    function rollLossEpoch() external override onlyGuardian nonReentrant {
        if (!epochRolloverRequired || totalShares == 0 || performingReceivables() != 0 || totalImpairment != 0) {
            revert EpochNotFullyWrittenOff();
        }
        // Donations/recoveries after the zero-NAV checkpoint cannot reopen deposits or block recapitalization.
        // They belong to the existing holders; earmarking them does not settle any borrower's legal debt.
        _absorbDonation();
        uint256 residual = _lpCash();
        if (residual != 0) {
            epochRecoveryReceived[currentEpoch] += residual;
            totalRecoveryReserved += residual;
            emit EpochResidualReserved(currentEpoch, residual);
        }
        closedEpochShares[currentEpoch] = totalShares;
        emit LossEpochClosed(currentEpoch, totalShares);
        currentEpoch++;
        epochRolloverRequired = false;
        totalShares = 0;
        pendingWithdrawalShares = 0;
        // Old unfilled requests remain cancellable, but their immutable old balances are recovery-only rights.
        withdrawalHead = nextWithdrawalId;
        emit EpochStarted(currentEpoch);
    }

    function recoveryClaimable(uint64 epoch, address lp) public view override returns (uint256) {
        uint256 supply = closedEpochShares[epoch];
        if (epoch >= currentEpoch || supply == 0) return 0;
        uint256 earned = Math.mulDiv(epochRecoveryReceived[epoch], _shares[epoch][lp], supply);
        return earned - epochRecoveryClaimed[epoch][lp];
    }

    function claimEpochRecovery(uint64 epoch) external override nonReentrant returns (uint256 assets) {
        if (epoch >= currentEpoch || closedEpochShares[epoch] == 0) revert EpochNotClosed(epoch);
        assets = recoveryClaimable(epoch, msg.sender);
        if (assets == 0) revert NoClaimableAssets();
        epochRecoveryClaimed[epoch][msg.sender] += assets;
        totalRecoveryReserved -= assets;
        _push(msg.sender, assets);
        _trackedBalance = IERC20Minimal(_ASSET).balanceOf(address(this));
        emit EpochRecoveryClaimed(epoch, msg.sender, assets);
    }

    function _reserveOldEpochRecovery(GpuTypes.FacilityId facilityId, uint256 amount) internal {
        uint64 epoch = writeOffEpoch[facilityId];
        if (!isWrittenOff[facilityId] || epoch == 0 || epoch >= currentEpoch || amount == 0) return;
        epochRecoveryReceived[epoch] += amount;
        totalRecoveryReserved += amount;
        emit EpochRecoveryReserved(epoch, facilityId, amount);
    }

    // ------------------------------------------------------------------ manager (ledger writer) actions

    /// @inheritdoc ILendingVaultV2
    function lend(GpuTypes.FacilityId facilityId, address to, uint256 amount)
        external
        override
        onlyManager
        nonReentrant
    {
        if (amount == 0) revert ZeroAmount();
        if (to == address(0)) revert ZeroAddress();
        if (isWrittenOff[facilityId]) revert FacilityWrittenOff(facilityId);
        if (epochRolloverRequired) revert EpochRecapitalizationRequired();
        if (pendingWithdrawalShares != 0) revert WithdrawalQueueActive();
        _absorbDonation();
        uint256 cash = availableCash();
        if (amount > cash) revert InsufficientCash(amount, cash);
        _push(to, amount);
        _trackedBalance = IERC20Minimal(_ASSET).balanceOf(address(this));
        emit Lent(facilityId, amount);
    }

    /// @inheritdoc ILendingVaultV2
    /// @dev The manager transfers `result.received` to the vault and allocates it in the ledger before calling.
    ///      The vault measures the arrival: the balance must have grown by at least `received` since the last
    ///      observation; anything beyond it is a donation (LP cash), never a repayment. `excess` becomes
    ///      borrower-owned refundable cash (AC-06) and leaves NAV immediately.
    function onRepayment(GpuTypes.FacilityId facilityId, GpuTypes.RepayResult calldata result)
        external
        override
        onlyManager
        nonReentrant
    {
        if (result.received == 0) revert ZeroAmount();
        if (result.applied + result.excess != result.received) revert CashNotReceived(result.received, result.applied);
        uint256 bal = IERC20Minimal(_ASSET).balanceOf(address(this));
        uint256 delta = bal > _trackedBalance ? bal - _trackedBalance : 0;
        if (delta < result.received) revert CashNotReceived(result.received, delta);
        if (delta > result.received) emit DonationAbsorbed(delta - result.received);
        if (result.excess != 0) {
            refundableOf[facilityId] += result.excess;
            totalBorrowerOwned += result.excess;
        }
        // Repayment realizes value previously estimated as impaired. Keep any remaining allowance capped by
        // the remaining legal claim; a repaid facility cannot continue reducing unrelated LP assets.
        uint256 impairment = impairmentOf[facilityId];
        if (impairment > result.newDebt) {
            uint256 released = impairment - result.newDebt;
            impairmentOf[facilityId] = result.newDebt;
            totalImpairment -= released;
            emit ImpairmentReversed(facilityId, released);
        }
        _reserveOldEpochRecovery(facilityId, result.applied);
        _trackedBalance = bal;
        emit RepaymentReceived(facilityId, result.received, result.applied, result.excess);
    }

    /// @notice Pay borrower-owned excess back out. Manager-only; never touches LP cash.
    function refundExcess(GpuTypes.FacilityId facilityId, address to, uint256 amount)
        external
        onlyManager
        nonReentrant
    {
        if (amount == 0) revert ZeroAmount();
        if (to == address(0)) revert ZeroAddress();
        uint256 avail = refundableOf[facilityId];
        if (amount > avail) revert RefundExceedsBalance(amount, avail);
        refundableOf[facilityId] = avail - amount;
        totalBorrowerOwned -= amount;
        _push(to, amount);
        _trackedBalance = IERC20Minimal(_ASSET).balanceOf(address(this));
        emit ExcessRefunded(facilityId, to, amount);
    }

    /// @inheritdoc ILendingVaultV2
    /// @dev Manager first transfers cash. Current-epoch recovery increases NAV; closed-epoch cash is reserved for
    ///      frozen holders and never increases the new epoch's NAV. Legal allocation remains a ledger operation.
    function recordRecovery(GpuTypes.FacilityId facilityId, uint256 amount) external override onlyManager nonReentrant {
        if (amount == 0) revert ZeroAmount();
        if (!isWrittenOff[facilityId]) revert FacilityNotWrittenOff(facilityId);
        uint256 bal = IERC20Minimal(_ASSET).balanceOf(address(this));
        uint256 delta = bal > _trackedBalance ? bal - _trackedBalance : 0;
        if (delta < amount) revert CashNotReceived(amount, delta);
        if (delta > amount) emit DonationAbsorbed(delta - amount);
        _reserveOldEpochRecovery(facilityId, amount);
        _trackedBalance = bal;
        emit RecoveryRecorded(facilityId, amount);
    }

    // ------------------------------------------------------------------ losses (GUARDIAN / UNDERWRITER)

    /// @inheritdoc ILendingVaultV2
    /// @dev Book-only: lowers NAV per share immediately; the ledger's legal debt is untouched (AC-13).
    function recognizeImpairment(GpuTypes.FacilityId facilityId, uint256 amount)
        external
        override
        onlyGuardianOrUnderwriter
    {
        if (amount == 0) revert ZeroAmount();
        if (isWrittenOff[facilityId]) revert FacilityWrittenOff(facilityId);
        uint256 exposure = LEDGER.legalDebtAt(facilityId, uint64(block.timestamp));
        uint256 after_ = impairmentOf[facilityId] + amount;
        if (after_ > exposure) revert ImpairmentExceedsExposure(after_, exposure);
        impairmentOf[facilityId] = after_;
        totalImpairment += amount;
        emit ImpairmentRecognized(facilityId, amount);
    }

    function reverseImpairment(GpuTypes.FacilityId facilityId, uint256 amount) external onlyGuardianOrUnderwriter {
        if (amount == 0) revert ZeroAmount();
        uint256 cur = impairmentOf[facilityId];
        if (amount > cur) revert ImpairmentExceedsExposure(amount, cur);
        impairmentOf[facilityId] = cur - amount;
        totalImpairment -= amount;
        emit ImpairmentReversed(facilityId, amount);
    }

    /// @inheritdoc ILendingVaultV2
    /// @dev The facility leaves the performing book; its impairment is released (no double count); the ledger's
    ///      legal debt persists (write-off is not forgiveness, AC-08). Reserve application and accrual freeze are
    ///      the manager's ledger actions (GPU-041) and are not performed here.
    function writeOff(GpuTypes.FacilityId facilityId) external override onlyGuardian {
        if (recoveryManager != address(0) && msg.sender != recoveryManager) revert OnlyRecoveryManager();
        if (isWrittenOff[facilityId]) revert FacilityWrittenOff(facilityId);
        uint64 nowTs = uint64(block.timestamp);
        GpuTypes.FacilityLedgerView memory v = LEDGER.view_(facilityId);
        uint256 interest = LEDGER.unpaidInterestAt(facilityId, nowTs);
        uint256 released = impairmentOf[facilityId];
        impairmentOf[facilityId] = 0;
        totalImpairment -= released;
        isWrittenOff[facilityId] = true;
        writeOffEpoch[facilityId] = currentEpoch;
        _writtenOff.push(facilityId);
        if (totalShares != 0 && nav() == 0 && performingReceivables() == 0 && totalImpairment == 0) {
            epochRolloverRequired = true;
        }
        emit WrittenOff(facilityId, v.principal, interest, 0);
    }

    // ------------------------------------------------------------------ internals

    /// @dev Any balance growth not attributed to a repayment/recovery/deposit is LP cash (AC-10 donation rule).
    function _absorbDonation() internal {
        uint256 bal = IERC20Minimal(_ASSET).balanceOf(address(this));
        if (bal > _trackedBalance) {
            emit DonationAbsorbed(bal - _trackedBalance);
            _trackedBalance = bal;
        }
    }

    function _pull(address from, uint256 amount) internal returns (uint256 received) {
        uint256 before = IERC20Minimal(_ASSET).balanceOf(address(this));
        _call(abi.encodeCall(IERC20Minimal.transferFrom, (from, address(this), amount)));
        received = IERC20Minimal(_ASSET).balanceOf(address(this)) - before;
    }

    function _push(address to, uint256 amount) internal {
        uint256 before = IERC20Minimal(_ASSET).balanceOf(address(this));
        uint256 receivedBefore = IERC20Minimal(_ASSET).balanceOf(to);
        _call(abi.encodeCall(IERC20Minimal.transfer, (to, amount)));
        uint256 after_ = IERC20Minimal(_ASSET).balanceOf(address(this));
        uint256 receivedAfter = IERC20Minimal(_ASSET).balanceOf(to);
        if (
            after_ > before || before - after_ != amount || receivedAfter < receivedBefore
                || receivedAfter - receivedBefore != amount
        ) {
            revert CashNotReceived(amount, receivedAfter > receivedBefore ? receivedAfter - receivedBefore : 0);
        }
    }

    /// @dev Non-returning (USDT-style) and bool-returning tokens are both accepted; `false` or revert fails.
    function _call(bytes memory data) internal {
        (bool ok, bytes memory ret) = _ASSET.call(data);
        if (!ok || (ret.length != 0 && !abi.decode(ret, (bool)))) revert TransferFailed();
        if (ret.length == 0 && _ASSET.code.length == 0) revert TransferFailed();
    }

    function _mint(address to, uint256 shares) internal {
        totalShares += shares;
        _shares[currentEpoch][to] += shares;
        emit Transfer(address(0), to, shares);
    }

    function _burn(address from, uint256 shares) internal {
        uint256 bal = balanceOf(from);
        if (shares > bal) revert ZeroShares();
        uint256 unlocked = bal - _lockedShares[currentEpoch][from];
        if (shares > unlocked) revert LockedShares(shares, unlocked);
        _shares[currentEpoch][from] = bal - shares;
        totalShares -= shares;
        emit Transfer(from, address(0), shares);
    }

    // ------------------------------------------------------------------ ERC-20 share transfers

    function approve(address spender, uint256 amount) external returns (bool) {
        _allowances[currentEpoch][msg.sender][spender] = amount;
        emit Approval(msg.sender, spender, amount);
        return true;
    }

    function transfer(address to, uint256 amount) external returns (bool) {
        _transferShares(msg.sender, to, amount);
        return true;
    }

    function transferFrom(address from, address to, uint256 amount) external returns (bool) {
        uint256 allowed = _allowances[currentEpoch][from][msg.sender];
        if (allowed != type(uint256).max) {
            if (amount > allowed) revert ZeroShares();
            _allowances[currentEpoch][from][msg.sender] = allowed - amount;
        }
        _transferShares(from, to, amount);
        return true;
    }

    function _transferShares(address from, address to, uint256 amount) internal {
        if (to == address(0)) revert ZeroAddress();
        uint256 bal = balanceOf(from);
        if (amount > bal) revert ZeroShares();
        uint256 unlocked = bal - _lockedShares[currentEpoch][from];
        if (amount > unlocked) revert LockedShares(amount, unlocked);
        _shares[currentEpoch][from] = bal - amount;
        _shares[currentEpoch][to] += amount;
        emit Transfer(from, to, amount);
    }
}
