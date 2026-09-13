// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import { GPU036Fixture } from "./GPU036DrawTest.t.sol";
import { GpuTypes } from "../../contracts/gpu/types/GpuTypes.sol";
import { IReceivableBook } from "../../contracts/gpu/interfaces/IReceivableBook.sol";
import { IEvidenceBook } from "../../contracts/gpu/interfaces/IEvidenceBook.sol";
import { ReceivableBook } from "../../contracts/gpu/ReceivableBook.sol";

/// @notice LOCAL_MOCK adversarial integration with the pinned official decoder. Not a G-ASC/network claim.
contract GPU082ConformanceTest is GPU036Fixture {
    function _oneClaim(bytes32 ref, uint256 amount)
        internal
        view
        returns (IReceivableBook.ReceivableClaim[] memory cs)
    {
        cs = new IReceivableBook.ReceivableClaim[](1);
        cs[0] = _claim(
            0,
            ACCOUNT_A,
            ref,
            bytes32(uint256(uint160(ISSUER))),
            abi.encode(PAYER, ESCROW, USDC, amount, DUE_AT, uint32(1))
        );
    }

    function test_queryCacheIsSeparateFromConsumptionAndBusinessRevertCanRetry() public {
        bytes32 ref = keccak256("retry-invoice");
        Log[] memory logs = new Log[](1);
        logs[0] = _log(
            T_RECOGNIZED,
            ACCOUNT_A,
            ref,
            bytes32(uint256(uint160(ISSUER))),
            4,
            abi.encode(PAYER, ESCROW, USDC, uint256(100e6), DUE_AT, uint32(1))
        );
        GpuTypes.NativeProofEnvelope memory envelope = _envelope(_txBytes(1, logs), nextHeight++, 0);
        GpuTypes.SourceEventId eventId = verifier.sourceEventId(envelope.height, 0, 0);
        // Anyone can verify first. This does not consume another user's economic event.
        vm.prank(mallory);
        verifier.verifyAndExtract(envelope, ESCROW, _topics(T_RECOGNIZED));
        assertFalse(evidence.isConsumed(eventId));
        vm.prank(relayer);
        (bool ok,) = address(book)
            .call(abi.encodeCall(book.ingest, (MOCK, envelope, ESCROW, _topics(T_RECOGNIZED), _oneClaim(ref, 99e6))));
        assertFalse(ok, "tampered business claim must roll back native consumption too");
        assertFalse(evidence.isConsumed(eventId));
        vm.prank(relayer);
        book.ingest(MOCK, envelope, ESCROW, _topics(T_RECOGNIZED), _oneClaim(ref, 100e6));
        assertTrue(evidence.isConsumed(eventId));
        assertEq(book.receivable(book.receivableId(MOCK, ACCOUNT_A, ref)).net, 100e6);
    }

    function test_sameEconomicRevisionAtDifferentSourceLocationCannotCreateSecondAsset() public {
        _readyA();
        uint256 navBefore = vault.nav();
        bytes32 economic = keccak256(
            abi.encode(
                book.ECONOMIC_KEY_DOMAIN(), MOCK, ACCOUNT_A, uint8(ReceivableBook.Kind.RECOGNIZED), REF_A, uint256(1)
            )
        );
        GpuTypes.SourceEventId first = verifier.sourceEventId(HEIGHT, 17, 0);
        Log[] memory logs = new Log[](1);
        logs[0] = _log(
            T_RECOGNIZED,
            ACCOUNT_A,
            REF_A,
            bytes32(uint256(uint160(ISSUER))),
            4,
            abi.encode(PAYER, ESCROW, USDC, uint256(12_000e6), DUE_AT, uint32(1))
        );
        GpuTypes.NativeProofEnvelope memory envelope = _envelope(_txBytes(1, logs), nextHeight++, 2);
        vm.prank(relayer);
        vm.expectRevert(abi.encodeWithSelector(IEvidenceBook.EconomicEventAlreadyRecorded.selector, economic, first));
        book.ingest(MOCK, envelope, ESCROW, _topics(T_RECOGNIZED), _oneClaim(REF_A, 12_000e6));
        assertFalse(evidence.isConsumed(verifier.sourceEventId(envelope.height, 2, 0)));
        assertEq(book.accountStats(MOCK, ACCOUNT_A).openAmount, 21_000e6);
        assertEq(vault.nav(), navBefore);
    }

    function test_sourcePaidAndFreshCheckpointRemoveCollateralWithoutRepayingDestinationDebt() public {
        _readyA();
        _borrow(1000e6);
        vm.warp(block.timestamp + 16 minutes); // original source reservation has elapsed before a source payment
        uint256 debtBefore = ledger.legalDebtAt(FA, uint64(block.timestamp));
        uint256 navBefore = vault.nav();
        uint256 cashBefore = loan.balanceOf(address(vault));
        bytes memory payout = abi.encode(PAYER, uint256(12_000e6), uint64(1));
        bytes32 tokenTopic = bytes32(uint256(uint160(USDC)));
        _ingestOne(
            T_PAYOUT,
            _log(T_PAYOUT, ACCOUNT_A, REF_A, tokenTopic, 4, payout),
            _claim(0, ACCOUNT_A, REF_A, tokenTopic, payout)
        );
        _checkpoint(ACCOUNT_A, 2, 4, 9000e6, 12_000e6);
        assertEq(mgr.evaluateDraw(FA, 0).eligibleReceivables, 0, "fully paid receivable cannot be repledged");
        assertEq(ledger.legalDebtAt(FA, uint64(block.timestamp)), debtBefore);
        assertEq(vault.nav(), navBefore);
        assertEq(loan.balanceOf(address(vault)), cashBefore);
    }

    function test_sourceReorgDisputeAfterActualRepaymentCannotRollBackDestinationMoney() public {
        _readyA();
        _borrow(1000e6);
        vm.startPrank(borrowerWallet);
        loan.approve(address(mgr), 100e6);
        mgr.repayFor(FA, 100e6);
        vm.stopPrank();
        uint256 cashBefore = loan.balanceOf(address(vault));
        uint256 navBefore = vault.nav();
        bytes32 receivable = book.receivableId(MOCK, ACCOUNT_A, REF_A);
        vm.prank(guardian);
        book.setDisputed(receivable, true, "source_reorg_reconciliation");
        assertEq(mgr.evaluateDraw(FA, 0).availableDraw, 0);
        assertEq(ledger.legalDebtAt(FA, uint64(block.timestamp)), 900e6);
        assertEq(loan.balanceOf(address(vault)), cashBefore);
        assertEq(vault.nav(), navBefore);
        assertEq(
            uint8(mgr.state(FA)), uint8(GpuTypes.FacilityState.ACTIVE), "evidence dispute is not automatic default"
        );
    }
}
