// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import { GPU039RepaymentTest } from "./GPU039RepaymentTest.t.sol";
import { SettlementReceiver } from "../../contracts/gpu/SettlementReceiver.sol";
import { GpuTypes } from "../../contracts/gpu/types/GpuTypes.sol";

contract GPU040SettlementTest is GPU039RepaymentTest {
    bytes32 constant ROUTE = keccak256("LOCAL_APPROVED_DESTINATION_DELIVERY");
    SettlementReceiver receiver;

    function _setupReceiver() internal {
        receiver = new SettlementReceiver(roles, router, address(usd));
        vm.startPrank(admin);
        roles.grantRole(roles.RELAYER(), address(receiver));
        receiver.registerRoute(ROUTE, treasury, 11_155_111, address(usd), 100_000e6);
        receiver.finalizeWiring();
        vm.stopPrank();
        vm.prank(treasury);
        usd.approve(address(receiver), type(uint256).max);
    }

    function test_actualDeliveryAllocatesOnceAndProtectsMinOut() public {
        _setupReceiver();
        vm.prank(treasury);
        GpuTypes.RepayResult memory result = receiver.receiveSettlement(
            ROUTE, bytes32("arrival-1"), FA, block.chainid, address(usd), 250e6, 250e6, uint64(block.timestamp + 60)
        );
        assertEq(result.received, 250e6);
        assertEq(result.applied, 250e6);
        assertEq(_debt(FA), PRINCIPAL - 250e6);
        vm.prank(treasury);
        vm.expectRevert(SettlementReceiver.DuplicateSettlement.selector);
        receiver.receiveSettlement(
            ROUTE, bytes32("arrival-1"), FA, block.chainid, address(usd), 250e6, 250e6, uint64(block.timestamp + 60)
        );
        assertEq(_debt(FA), PRINCIPAL - 250e6);
    }

    function test_wrongChainTokenExpiredQuoteAndUnknownRailNeverChangeDebt() public {
        _setupReceiver();
        vm.startPrank(treasury);
        vm.expectRevert(SettlementReceiver.InvalidQuote.selector);
        receiver.receiveSettlement(
            ROUTE, bytes32("a"), FA, block.chainid + 1, address(usd), 1e6, 1e6, uint64(block.timestamp + 60)
        );
        vm.expectRevert(SettlementReceiver.InvalidQuote.selector);
        receiver.receiveSettlement(
            ROUTE, bytes32("a"), FA, block.chainid, address(0xBAD), 1e6, 1e6, uint64(block.timestamp + 60)
        );
        vm.expectRevert(SettlementReceiver.InvalidQuote.selector);
        receiver.receiveSettlement(
            ROUTE, bytes32("a"), FA, block.chainid, address(usd), 1e6, 1e6, uint64(block.timestamp)
        );
        vm.stopPrank();
        vm.prank(mallory);
        vm.expectRevert(SettlementReceiver.UnsupportedRoute.selector);
        receiver.receiveSettlement(
            ROUTE, bytes32("a"), FA, block.chainid, address(usd), 1e6, 1e6, uint64(block.timestamp + 60)
        );
        assertEq(_debt(FA), PRINCIPAL);
    }

    function test_lateSettlementAfterDirectPayoffBecomesBorrowerRefund() public {
        _setupReceiver();
        vm.prank(borrowerA);
        router.repayExact(FA, PRINCIPAL);
        vm.prank(treasury);
        GpuTypes.RepayResult memory result = receiver.receiveSettlement(
            ROUTE, bytes32("late"), FA, block.chainid, address(usd), 100e6, 100e6, uint64(block.timestamp + 60)
        );
        assertEq(result.applied, 0);
        assertEq(result.excess, 100e6);
        assertEq(vault.refundableOf(FA), 100e6);
        vm.prank(borrowerA);
        router.refundExcess(FA, borrowerA);
        assertEq(vault.refundableOf(FA), 0);
    }
}
