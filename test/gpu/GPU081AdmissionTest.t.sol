// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import { GPU036Fixture } from "./GPU036DrawTest.t.sol";
import { GpuTypes } from "../../contracts/gpu/types/GpuTypes.sol";
import { ReceivableBook } from "../../contracts/gpu/ReceivableBook.sol";
import { IReceivableBook } from "../../contracts/gpu/interfaces/IReceivableBook.sol";
import { IExposureController } from "../../contracts/gpu/interfaces/IExposureController.sol";
import { ICreditFacilityManager } from "../../contracts/gpu/interfaces/ICreditFacilityManager.sol";
import { CreditFacilityManager } from "../../contracts/gpu/CreditFacilityManager.sol";

contract GPU081AdmissionTest is GPU036Fixture {
    function test_revokedProviderAdmissionOrReleasedWalletCannotUseOldProofs() public {
        _readyA();
        vm.prank(guardian);
        providers.setAdmission(MOCK, false, "incident");
        assertEq(mgr.evaluateDraw(FA, 0).availableDraw, 0);
        vm.prank(guardian);
        providers.setAdmission(MOCK, true, "resolved");
        vm.prank(borrowerWallet);
        accounts.releaseWallet(borrowerWallet);
        vm.prank(borrowerWallet);
        vm.expectRevert(
            abi.encodeWithSelector(CreditFacilityManager.WalletNotLinked.selector, BORROWER_A, borrowerWallet)
        );
        mgr.borrow(FA, 1e6, 0);
    }

    function test_selfAssertedNativeLogCannotCreateCollateral() public {
        _openFacility(FA, 50_000e6);
        _anchor(_auth(FA, 50_000e6));
        _activate(FA);
        vm.prank(admin);
        evidence.setSelfAssertedEmitter(MOCK, ESCROW, true);
        vm.expectRevert(ReceivableBook.UntrustedEvidence.selector);
        _recognizeFixture();
        assertEq(ledger.legalDebtAt(FA, uint64(block.timestamp)), 0);
    }

    function test_unregisteredIssuerCannotCreateCollateralDespiteRegisteredEmitter() public {
        _openFacility(FA, 50_000e6);
        vm.prank(registrar);
        providers.setIssuer(MOCK, ISSUER, false);
        vm.expectRevert(ReceivableBook.UntrustedEvidence.selector);
        _recognizeFixture();
    }

    function test_oldCheckpointSubmissionCannotRefreshProtectedSourceState() public {
        _readyA();
        vm.warp(block.timestamp + 16 minutes);
        bytes memory data = abi.encode(uint64(2), uint32(3), uint256(21_000e6), uint256(0), T0, T0 + 15 minutes);
        _ingestOne(T_CHECKPOINT, _log(T_CHECKPOINT, ACCOUNT_A, 0, 0, 2, data), _claim(0, ACCOUNT_A, 0, 0, data));
        assertEq(book.checkpoint(MOCK, ACCOUNT_A).provenAt, block.timestamp);
        assertEq(book.checkpoint(MOCK, ACCOUNT_A).observedAt, T0);
        assertEq(mgr.evaluateDraw(FA, 0).availableDraw, 0);
        vm.prank(borrowerWallet);
        vm.expectRevert(abi.encodeWithSelector(ICreditFacilityManager.NativeEvidenceRequired.selector, FA));
        mgr.borrow(FA, 1, 0);
    }

    function test_expiredSourceProtectionRejectsPreviouslyReservedDraw() public {
        _readyA();
        vm.prank(borrowerWallet);
        bytes32 id = mgr.reserveDraw(FA, 1000e6, 1 hours);
        vm.warp(block.timestamp + 15 minutes);
        vm.prank(borrowerWallet);
        vm.expectRevert(abi.encodeWithSelector(IExposureController.InsufficientHeadroom.selector, 1000e6, 0));
        mgr.executeReservedDraw(id, 0);
        assertEq(ledger.legalDebtAt(FA, uint64(block.timestamp)), 0);
        assertEq(uint8(ctl.reservation(id).state), uint8(IExposureController.ReservationState.ACTIVE));
    }

    function test_signerRevocationAndEpochRotationInvalidateOutstandingAnchor() public {
        _readyA();
        vm.startPrank(admin);
        roles.rotateKeyEpoch(roles.UNDERWRITER(), 0);
        vm.stopPrank();
        vm.warp(block.timestamp + 1);
        vm.prank(borrowerWallet);
        vm.expectRevert(abi.encodeWithSelector(ICreditFacilityManager.AuthorizationMissingOrExpired.selector, FA));
        mgr.borrow(FA, 1, 0);
        assertEq(ledger.legalDebtAt(FA, uint64(block.timestamp)), 0);
    }

    function test_guardianCannotResumeDrawsWithoutUnderwriterConsent() public {
        _readyA();
        vm.prank(guardian);
        mgr.pauseDraws(true);
        vm.prank(guardian);
        vm.expectRevert(CreditFacilityManager.ResumeNotApproved.selector);
        mgr.pauseDraws(false);
        vm.prank(underwriter);
        mgr.approveDrawResume();
        vm.prank(guardian);
        mgr.pauseDraws(false);
        _borrow(1e6);
        assertEq(ledger.view_(FA).principal, 1e6);
    }

    function test_evidencePauseNeverBlocksActualDestinationRepayment() public {
        _readyA();
        _borrow(1000e6);
        vm.prank(guardian);
        evidence.pauseEvidenceIntake(true);
        prover.setRevert(true);
        loan.mint(borrowerWallet, 1000e6);
        vm.startPrank(borrowerWallet);
        loan.approve(address(mgr), 1000e6);
        GpuTypes.RepayResult memory result = mgr.repayFor(FA, 1000e6);
        vm.stopPrank();
        assertEq(result.applied, 1000e6);
        assertEq(result.newDebt, 0);
    }
}
