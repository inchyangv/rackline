// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import { GPU036Fixture } from "./GPU036DrawTest.t.sol";
import { GpuTypes } from "../../contracts/gpu/types/GpuTypes.sol";
import { RepaymentRouter, IFacilityWallets } from "../../contracts/gpu/RepaymentRouter.sol";
import { RecoveryManager } from "../../contracts/gpu/RecoveryManager.sol";
import { LendingVaultV2 } from "../../contracts/gpu/LendingVaultV2.sol";

/// @notice Financial lifecycle using actual manager, native adapter with explicit LOCAL_MOCK prover, ledger,
/// vault and repayment router. Inherited draw regressions stay active under the same fixture.
contract GPU041RecoveryTest is GPU036Fixture {
    RecoveryManager recovery;
    RepaymentRouter router;

    function _setupRecovery() internal {
        router = new RepaymentRouter(roles, ledger, vault, IFacilityWallets(address(mgr)));
        recovery = new RecoveryManager(roles, ledger, mgr, vault, router);
        vm.startPrank(admin);
        ledger.setWriter(address(router), true);
        ledger.setWriter(address(recovery), true);
        vault.setManager(address(router), true);
        roles.grantRole(roles.GUARDIAN(), address(recovery));
        mgr.bindRecoveryManager(address(recovery));
        vault.bindRecoveryManager(address(recovery));
        vm.stopPrank();
        _readyA();
        _borrow(5000e6);
        vm.prank(underwriter);
        recovery.setSchedule(FA, uint64(block.timestamp + 1 days), 1 days, 12 hours, 1000e6);
    }

    function _delinquent() internal {
        vm.warp(block.timestamp + 2 days + 1);
        recovery.markDelinquent(FA);
    }

    function _defaultAndRecover() internal {
        _delinquent();
        vm.prank(underwriter);
        recovery.approveDefault(FA, keccak256("contractual_nonpayment"));
        vm.prank(guardian);
        recovery.declareDefault(FA);
        vm.prank(servicer);
        recovery.beginRecovery(FA);
    }

    function _cashRepay(uint256 amount) internal returns (GpuTypes.RepayResult memory result) {
        loan.mint(borrowerWallet, amount);
        vm.startPrank(borrowerWallet);
        loan.approve(address(router), amount);
        result = router.repayExact(FA, amount);
        vm.stopPrank();
    }

    function test_installmentCureCountsOnlyDestinationAllocations() public {
        _setupRecovery();
        _delinquent();
        assertEq(uint8(mgr.state(FA)), uint8(GpuTypes.FacilityState.DELINQUENT));
        vm.expectRevert(RecoveryManager.NotDue.selector);
        recovery.cure(FA);
        _cashRepay(1000e6);
        recovery.cure(FA);
        assertEq(uint8(mgr.state(FA)), uint8(GpuTypes.FacilityState.ACTIVE));
        assertEq(recovery.totalAllocated(FA), 1000e6);
        assertGt(ledger.legalDebtAt(FA, uint64(block.timestamp)), 4000e6);
    }

    function test_defaultNeedsGraceDisputeResolutionAndTwoRoles() public {
        _setupRecovery();
        vm.prank(underwriter);
        vm.expectRevert(RecoveryManager.NotDue.selector);
        recovery.approveDefault(FA, bytes32("early"));
        _delinquent();
        vm.prank(servicer);
        recovery.setDispute(FA, true);
        vm.prank(underwriter);
        vm.expectRevert(RecoveryManager.DisputeOpen.selector);
        recovery.approveDefault(FA, bytes32("disputed"));
        vm.prank(servicer);
        recovery.setDispute(FA, false);
        vm.prank(guardian);
        vm.expectRevert(RecoveryManager.NotApproved.selector);
        recovery.declareDefault(FA);
        vm.prank(underwriter);
        recovery.approveDefault(FA, bytes32("nonpayment"));
        vm.prank(guardian);
        recovery.declareDefault(FA);
        uint256 debt = ledger.legalDebtAt(FA, uint64(block.timestamp));
        vm.warp(block.timestamp + 365 days);
        assertEq(ledger.legalDebtAt(FA, uint64(block.timestamp)), debt, "non-accrual does not forgive debt");
        _cashRepay(100e6);
        assertEq(ledger.legalDebtAt(FA, uint64(block.timestamp)), debt - 100e6);
    }

    function test_partialImpairmentClearsAsRemainingDebtIsRepaid() public {
        _setupRecovery();
        vm.prank(underwriter);
        recovery.impair(FA, bytes32("impairment-1"), 4000e6);
        assertEq(vault.nav(), LP_CASH - 4000e6);
        _cashRepay(3000e6);
        assertEq(vault.impairmentOf(FA), 2000e6);
        assertEq(vault.nav(), LP_CASH - 2000e6);
        _cashRepay(2000e6);
        assertEq(vault.impairmentOf(FA), 0);
        assertEq(vault.nav(), LP_CASH);
        vm.prank(underwriter);
        vm.expectRevert(RecoveryManager.DuplicateLoss.selector);
        recovery.impair(FA, bytes32("impairment-1"), 1);
    }

    function test_pledgedReserveWriteoffAndLateRecoveryKeepLegalClaim() public {
        _setupRecovery();
        loan.mint(borrowerWallet, 250e6);
        vm.startPrank(borrowerWallet);
        loan.approve(address(recovery), 250e6);
        recovery.fundReserve(FA, 250e6);
        vm.expectRevert(RecoveryManager.OutstandingDebt.selector);
        recovery.returnReserve(FA);
        vm.stopPrank();
        _defaultAndRecover();
        uint256 beforeDebt = ledger.legalDebtAt(FA, uint64(block.timestamp));
        vm.prank(underwriter);
        recovery.approveWriteOff(FA, bytes32("loss-1"));
        vm.prank(treasury);
        recovery.writeOff(FA, bytes32("loss-1"));
        assertEq(ledger.legalDebtAt(FA, uint64(block.timestamp)), beforeDebt - 250e6);
        assertEq(recovery.schedule(FA).pledgedReserve, 0);
        assertTrue(vault.isWrittenOff(FA));
        uint256 beforeNav = vault.nav();
        _cashRepay(400e6);
        assertEq(vault.nav(), beforeNav + 400e6);
        assertEq(ledger.legalDebtAt(FA, uint64(block.timestamp)), beforeDebt - 650e6);
        vm.prank(treasury);
        vm.expectRevert(RecoveryManager.DuplicateLoss.selector);
        recovery.writeOff(FA, bytes32("loss-1"));
    }

    function test_wrongRolesCannotUseRefundsOrManufactureRecoveryCash() public {
        _setupRecovery();
        vm.prank(guardian);
        vm.expectRevert(LendingVaultV2.OnlyRecoveryManager.selector);
        vault.writeOff(FA);
        vm.prank(mallory);
        vm.expectRevert(RecoveryManager.NotRole.selector);
        recovery.observeAllocation(FA, 5000e6);
        vm.prank(mallory);
        vm.expectRevert(RecoveryManager.NotRole.selector);
        recovery.impair(FA, bytes32("fake"), 5000e6);
        assertEq(recovery.totalAllocated(FA), 0);
        assertEq(vault.nav(), LP_CASH);
    }
}
