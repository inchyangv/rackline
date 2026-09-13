// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import { GpuTypes } from "../types/GpuTypes.sol";

/**
 * @title ILendingVaultV2
 * @notice LP book (docs/gpu/accounting.md §5–§6): LP-owned cash, performing loan receivables from the debt ledger,
 *         impairment, virtual-offset shares, withdrawals limited to cash. Borrower reserve, refundable excess, source
 *         escrow and in-flight funds are never vault assets. No fixed yield exists.
 * @dev Whether ERC-4626 is implemented (and which optional parts) is stated by the implementation (GPU-034).
 */
interface ILendingVaultV2 {
    /// @notice Shares remain exposed to NAV until filled. Only funded fills become fixed cash claims.
    struct WithdrawalRequest {
        address owner;
        uint64 epoch;
        uint64 expiresAt;
        uint256 sharesRequested;
        uint256 sharesRemaining;
        uint256 minAssets;
        uint256 assetsReserved;
        uint256 assetsClaimed;
        bool cancelled;
    }

    event WithdrawalRequested(
        uint256 indexed requestId,
        address indexed owner,
        uint64 indexed epoch,
        uint256 shares,
        uint256 minAssets,
        uint64 expiresAt
    );
    event WithdrawalFilled(uint256 indexed requestId, uint256 shares, uint256 assets);
    event WithdrawalCancelled(uint256 indexed requestId, uint256 unlockedShares);
    event WithdrawalClaimed(uint256 indexed requestId, address indexed owner, uint256 assets);
    event LossEpochClosed(uint64 indexed epoch, uint256 frozenShares);
    event EpochStarted(uint64 indexed epoch);
    event EpochRecoveryReserved(uint64 indexed epoch, GpuTypes.FacilityId indexed facilityId, uint256 assets);
    event EpochResidualReserved(uint64 indexed epoch, uint256 assets);
    event EpochRecoveryClaimed(uint64 indexed epoch, address indexed owner, uint256 assets);
    event Deposited(address indexed lp, uint256 assets, uint256 shares);
    event Withdrawn(address indexed lp, uint256 assets, uint256 shares);
    event Lent(GpuTypes.FacilityId indexed facilityId, uint256 amount);
    event RepaymentReceived(GpuTypes.FacilityId indexed facilityId, uint256 received, uint256 applied, uint256 excess);
    event ImpairmentRecognized(GpuTypes.FacilityId indexed facilityId, uint256 amount);
    event WrittenOff(GpuTypes.FacilityId indexed facilityId, uint256 principal, uint256 interest, uint256 reserveUsed);
    event RecoveryRecorded(GpuTypes.FacilityId indexed facilityId, uint256 amount);
    event DonationAbsorbed(uint256 amount);

    error InsufficientCash(uint256 requested, uint256 available);
    error ZeroShares();
    error SlippageExceeded(uint256 got, uint256 min);
    error OnlyManager(address caller);
    error ImpairmentExceedsExposure(uint256 amount, uint256 exposure);

    function asset() external view returns (address);
    function availableCash() external view returns (uint256);
    function nav() external view returns (uint256);
    function totalShares() external view returns (uint256);
    function previewDeposit(uint256 assets) external view returns (uint256 shares);
    function previewWithdraw(uint256 shares) external view returns (uint256 assets);
    function deposit(uint256 assets, uint256 minShares) external returns (uint256 shares);
    function withdraw(uint256 shares, uint256 minAssets) external returns (uint256 assets);
    function requestWithdrawal(uint256 shares, uint256 minAssets) external returns (uint256 requestId);
    function cancelWithdrawal(uint256 requestId) external;
    function processWithdrawals(uint256 maxRequests) external returns (uint256 filledRequests, uint256 assetsReserved);
    function claimWithdrawal(uint256 requestId) external returns (uint256 assets);
    function withdrawalRequest(uint256 requestId) external view returns (WithdrawalRequest memory);
    function currentEpoch() external view returns (uint64);
    function sharesOfEpoch(uint64 epoch, address lp) external view returns (uint256);
    function rollLossEpoch() external;
    function recoveryClaimable(uint64 epoch, address lp) external view returns (uint256);
    function claimEpochRecovery(uint64 epoch) external returns (uint256 assets);
    /// @notice Manager-only: move cash to the borrower for a draw recorded in the debt ledger.
    function lend(GpuTypes.FacilityId facilityId, address to, uint256 amount) external;
    /// @notice Manager-only: vault received `received` loan asset for `facilityId`; ledger allocation result recorded.
    function onRepayment(GpuTypes.FacilityId facilityId, GpuTypes.RepayResult calldata result) external;
    function recognizeImpairment(GpuTypes.FacilityId facilityId, uint256 amount) external;
    function writeOff(GpuTypes.FacilityId facilityId) external;
    function recordRecovery(GpuTypes.FacilityId facilityId, uint256 amount) external;
}
