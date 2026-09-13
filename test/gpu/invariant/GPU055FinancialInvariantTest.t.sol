// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import { Test } from "forge-std/Test.sol";
import { GPU036Fixture, ShortfallToken } from "../GPU036DrawTest.t.sol";
import { GpuTypes } from "../../../contracts/gpu/types/GpuTypes.sol";
import { CreditFacilityManager } from "../../../contracts/gpu/CreditFacilityManager.sol";
import { DebtLedger } from "../../../contracts/gpu/DebtLedger.sol";
import { LendingVaultV2 } from "../../../contracts/gpu/LendingVaultV2.sol";
import { ExposureController } from "../../../contracts/gpu/ExposureController.sol";

/// @notice Independent integer ACT/365 reference: numerator is principal × bps × seconds; no InterestMath calls.
contract GPU055Handler is Test {
    CreditFacilityManager public manager;
    DebtLedger public ledger;
    LendingVaultV2 public vault;
    ShortfallToken public token;
    GpuTypes.FacilityId public facility;
    address public borrower;
    address public lp;
    address public guardian;
    uint256 public modelPrincipal;
    uint256 public modelInterestNumerator;
    uint256 public modelLastTime;
    uint256 public constant DENOMINATOR = 365 days * 10_000;
    bool public frozen;
    mapping(bytes32 => uint256) public calls;

    constructor(
        CreditFacilityManager manager_,
        GpuTypes.FacilityId id,
        address borrower_,
        address lp_,
        address guardian_
    ) {
        manager = manager_;
        ledger = DebtLedger(address(manager_.LEDGER()));
        vault = LendingVaultV2(address(manager_.VAULT()));
        token = ShortfallToken(vault.asset());
        facility = id;
        borrower = borrower_;
        lp = lp_;
        guardian = guardian_;
        modelPrincipal = ledger.view_(id).principal;
        modelLastTime = block.timestamp;
    }

    function _accrueModel() internal {
        if (!frozen) modelInterestNumerator += modelPrincipal * 1000 * (block.timestamp - modelLastTime);
        modelLastTime = block.timestamp;
    }

    function advanceTime(uint16 seconds_) external {
        calls["time"]++;
        vm.warp(block.timestamp + bound(seconds_, 0, 30));
        _accrueModel();
    }

    function draw(uint64 requested) external {
        calls["draw"]++;
        _accrueModel();
        if (manager.state(facility) != GpuTypes.FacilityState.ACTIVE || manager.drawsPaused() || frozen) return;
        uint256 room = manager.evaluateDraw(facility, 0).availableDraw;
        if (room == 0) return;
        uint256 amount = bound(requested, 1, room < 100e6 ? room : 100e6);
        vm.prank(borrower);
        try manager.borrow(facility, amount, amount) {
            modelPrincipal += amount;
            calls["drawSuccess"]++;
        } catch { }
    }

    function repay(uint64 requested) external {
        calls["repay"]++;
        _accrueModel();
        uint256 debt = modelPrincipal + modelInterestNumerator / DENOMINATOR;
        if (debt == 0) return;
        uint256 amount = bound(requested, 1, debt < 100e6 ? debt : 100e6);
        token.mint(borrower, amount);
        vm.startPrank(borrower);
        token.approve(address(manager), amount);
        GpuTypes.RepayResult memory result = manager.repayFor(facility, amount);
        vm.stopPrank();
        uint256 interest = modelInterestNumerator / DENOMINATOR;
        uint256 interestPaid = amount < interest ? amount : interest;
        uint256 principalPaid = amount - interestPaid;
        modelInterestNumerator -= interestPaid * DENOMINATOR;
        modelPrincipal -= principalPaid;
        assertEq(result.interestPaid, interestPaid);
        assertEq(result.principalPaid, principalPaid);
        assertEq(result.received, result.applied + result.excess);
        calls["repaySuccess"]++;
    }

    function withdraw(uint64 requested) external {
        calls["withdraw"]++;
        uint256 shares = vault.balanceOf(lp);
        uint256 locked = vault.lockedShares(vault.currentEpoch(), lp);
        if (shares <= locked) return;
        uint256 amount = bound(requested, 1, (shares - locked) / 100 + 1);
        vm.prank(lp);
        try vault.withdraw(amount, 0) {
            calls["withdrawSuccess"]++;
        } catch { }
    }

    function queue(uint64 requested) external {
        calls["queue"]++;
        uint256 free = vault.balanceOf(lp) - vault.lockedShares(vault.currentEpoch(), lp);
        if (free == 0) return;
        vm.prank(lp);
        try vault.requestWithdrawal(bound(requested, 1, free / 100 + 1), 0) returns (uint256 id) {
            vault.processWithdrawals(5);
            vm.prank(lp);
            try vault.claimWithdrawal(id) { } catch { }
            vm.prank(lp);
            try vault.cancelWithdrawal(id) { } catch { }
            calls["queueSuccess"]++;
        } catch { }
    }

    function impairment(uint64 requested) external {
        calls["impairment"]++;
        _accrueModel();
        if (vault.isWrittenOff(facility)) return;
        uint256 debt = ledger.legalDebtAt(facility, uint64(block.timestamp));
        uint256 prior = vault.impairmentOf(facility);
        if (debt <= prior) return;
        vm.prank(guardian);
        vault.recognizeImpairment(facility, bound(requested, 1, debt - prior));
    }

    function lossAndRecoveryBoundary() external {
        calls["loss"]++;
        _accrueModel();
        if (vault.isWrittenOff(facility) || modelPrincipal == 0) return;
        // The handler's sole special writer use is non-accrual. It cannot add model principal without actual draw.
        ledger.freezeAccrual(facility);
        frozen = true;
        vm.prank(guardian);
        vault.writeOff(facility);
        calls["lossSuccess"]++;
    }

    function guardianPause(bool pause_) external {
        calls["pause"]++;
        vm.prank(guardian);
        try manager.pauseDraws(pause_) { } catch { }
    }

    function reservations(uint64 requested) external {
        calls["reservation"]++;
        _accrueModel();
        if (manager.state(facility) != GpuTypes.FacilityState.ACTIVE || frozen || manager.drawsPaused()) return;
        uint256 room = manager.evaluateDraw(facility, 0).availableDraw;
        if (room == 0) return;
        vm.prank(borrower);
        try manager.reserveDraw(facility, bound(requested, 1, room), 60) returns (bytes32 id) {
            vm.warp(block.timestamp + 60);
            _accrueModel();
            ExposureController(address(manager.EXPOSURE())).expireReservation(id);
            calls["reservationSuccess"]++;
        } catch { }
    }

    function expectedDebt() external view returns (uint256) {
        uint256 interest = modelInterestNumerator;
        if (!frozen) interest += modelPrincipal * 1000 * (block.timestamp - modelLastTime);
        return modelPrincipal + interest / DENOMINATOR;
    }
}

contract GPU055FinancialInvariantTest is GPU036Fixture {
    GPU055Handler handler;

    function setUp() public override {
        super.setUp();
        _readyA();
        _borrow(1000e6);
        handler = new GPU055Handler(mgr, FA, borrowerWallet, lp, guardian);
        vm.prank(admin);
        ledger.setWriter(address(handler), true);
        bytes4[] memory selectors = new bytes4[](9);
        selectors[0] = handler.advanceTime.selector;
        selectors[1] = handler.draw.selector;
        selectors[2] = handler.repay.selector;
        selectors[3] = handler.withdraw.selector;
        selectors[4] = handler.queue.selector;
        selectors[5] = handler.impairment.selector;
        selectors[6] = handler.lossAndRecoveryBoundary.selector;
        selectors[7] = handler.guardianPause.selector;
        selectors[8] = handler.reservations.selector;
        targetSelector(FuzzSelector({ addr: address(handler), selectors: selectors }));
        targetContract(address(handler));
    }

    function invariant_singleLedgerMatchesIndependentReference() public view {
        assertEq(ledger.legalDebtAt(FA, uint64(block.timestamp)), handler.expectedDebt());
        assertEq(ledger.view_(FA).principal, handler.modelPrincipal());
    }

    function invariant_cashLiabilitiesAndNavAreConserved() public view {
        uint256 liabilities =
            vault.totalBorrowerOwned() + vault.totalWithdrawalReserved() + vault.totalRecoveryReserved();
        assertGe(loan.balanceOf(address(vault)), liabilities);
        uint256 expected = loan.balanceOf(address(vault)) - liabilities + vault.performingReceivables();
        expected = expected > vault.totalImpairment() ? expected - vault.totalImpairment() : 0;
        assertEq(vault.nav(), expected);
        assertLe(vault.impairmentOf(FA), ledger.legalDebtAt(FA, uint64(block.timestamp)));
    }
}
