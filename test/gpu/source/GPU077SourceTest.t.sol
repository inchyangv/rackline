// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import { Test } from "forge-std/Test.sol";
import { MockERC20 } from "../../../contracts/mocks/MockERC20.sol";
import { ISourceEscrow } from "../../../contracts/gpu/source/ISourceEscrow.sol";
import { ISourceAdapter } from "../../../contracts/gpu/source/ISourceAdapter.sol";
import { SourceEscrow } from "../../../contracts/gpu/source/SourceEscrow.sol";
import { MockDePINPayout } from "../../../contracts/gpu/mocks/MockDePINPayout.sol";

/// @dev TEST_ONLY minimal token base for the two misbehaving tokens below (legacy MockERC20 is not virtual).
abstract contract MiniToken {
    uint256 public totalSupply;
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    function mint(address to, uint256 amount) external {
        totalSupply += amount;
        balanceOf[to] += amount;
    }

    function approve(address spender, uint256 amount) external returns (bool) {
        allowance[msg.sender][spender] = amount;
        return true;
    }

    function transfer(address to, uint256 amount) external returns (bool) {
        balanceOf[msg.sender] -= amount;
        balanceOf[to] += amount;
        return true;
    }
}

/// @dev TEST_ONLY fee-on-transfer token: the receiver gets `amount - fee`.
contract FeeOnTransferToken is MiniToken {
    uint256 public feeBps;

    constructor(uint256 feeBps_) {
        feeBps = feeBps_;
    }

    function transferFrom(address from, address to, uint256 amount) external returns (bool) {
        uint256 allowed = allowance[from][msg.sender];
        require(allowed >= amount, "allowance");
        allowance[from][msg.sender] = allowed - amount;
        uint256 fee = (amount * feeBps) / 10_000;
        balanceOf[from] -= amount;
        balanceOf[to] += amount - fee;
        totalSupply -= fee;
        return true;
    }
}

/// @dev TEST_ONLY token whose transferFrom re-enters the escrow with a second settle (same balance, new id).
contract ReenteringToken is MiniToken {
    SourceEscrow public escrow;
    bytes32 public accountKey;
    bool public armed;
    bytes public lastRevert;

    function arm(SourceEscrow e, bytes32 k) external {
        escrow = e;
        accountKey = k;
        armed = true;
    }

    function transferFrom(address from, address to, uint256 amount) external returns (bool) {
        balanceOf[from] -= amount;
        balanceOf[to] += amount;
        if (armed) {
            armed = false;
            try escrow.settle(accountKey, bytes32(0), address(this), amount, keccak256("reenter")) {
                lastRevert = "";
            } catch (bytes memory r) {
                lastRevert = r;
            }
        }
        return true;
    }
}

/**
 * @title GPU077SourceTest
 * @notice Source receipt / obligation module + TEST_ONLY MockDePIN payer. LOCAL only; the escrow is the emitter that
 *         GPU-078 verifies. partnerSourceBinding stays UNCONFIGURED.
 */
contract GPU077SourceTest is Test {
    SourceEscrow escrow;
    MockDePINPayout depin;
    MockERC20 usdc;

    address owner = address(0x0A);
    address upgradeAdmin = address(0x0B);
    address issuer = address(0x155);
    address controller = address(0xC0);
    address anchor = address(0xA1);
    address operator = address(0x0E);
    address borrower = address(0xB0);
    address mallory = address(0xBAD);
    address donor = address(0xD0);

    bytes32 constant ACCT = keccak256("mockdepin-testonly:acct-A");
    bytes32 constant ACCT_B = keccak256("mockdepin-testonly:acct-B");
    bytes32 constant REF_A = keccak256("inv-2026-08-A");
    bytes32 constant REF_B = keccak256("inv-2026-08-B");
    bytes32 constant FACILITY = keccak256("facility-1");
    uint64 constant DUE = 1_761_868_800;

    string abiJson;

    function setUp() public {
        abiJson = vm.readFile("test/fixtures/gpu/attestcoin/source-events-v1.abi.json");
        usdc = new MockERC20("USD Coin", "USDC", 6);
        escrow = new SourceEscrow(owner, upgradeAdmin);
        depin = new MockDePINPayout(escrow, operator);
        vm.startPrank(owner);
        escrow.setIssuer(issuer, true);
        escrow.setController(controller, true);
        escrow.setAnchor(anchor, true);
        escrow.setPayer(address(depin), true);
        escrow.registerAccount(ACCT, borrower);
        escrow.registerAccount(ACCT_B, address(0xB1));
        escrow.admitToken(address(usdc), 6, false);
        vm.stopPrank();
        usdc.mint(address(depin), 1_000_000e6);
        usdc.mint(borrower, 100_000e6);
        usdc.mint(donor, 100_000e6);
    }

    // ------------------------------------------------------------------ helpers

    function _recognize(bytes32 ref, uint256 amount) internal {
        vm.prank(issuer);
        escrow.recognizeObligation(ACCT, ref, address(depin), address(usdc), amount, DUE);
    }

    function _pay(bytes32 ref, uint256 amount, string memory id) internal returns (uint64 seq, uint256 measured) {
        vm.prank(operator);
        return depin.payout(ACCT, ref, address(usdc), amount, keccak256(bytes(id)));
    }

    function _topic0(string memory name) internal view returns (bytes32) {
        string[] memory names = new string[](6);
        names[0] = "ObligationRecognized";
        names[1] = "ObligationAssigned";
        names[2] = "ObligationCorrected";
        names[3] = "PayoutReceived";
        names[4] = "PayoutCancelled";
        names[5] = "SourceCheckpoint";
        for (uint256 i = 0; i < names.length; i++) {
            if (keccak256(bytes(names[i])) == keccak256(bytes(name))) {
                return vm.parseJsonBytes32(abiJson, string.concat(".events[", vm.toString(i), "].topic0"));
            }
        }
        revert("unknown");
    }

    // ------------------------------------------------------------------ ABI parity

    function test_eventTopicsMatchProposedSourceAbiFixture() public view {
        assertEq(vm.parseJsonString(abiJson, ".kind"), "PROPOSED_INTERNAL_SOURCE_EVENTS");
        assertEq(ISourceEscrow.ObligationRecognized.selector, _topic0("ObligationRecognized"));
        assertEq(ISourceEscrow.ObligationAssigned.selector, _topic0("ObligationAssigned"));
        assertEq(ISourceEscrow.ObligationCorrected.selector, _topic0("ObligationCorrected"));
        assertEq(ISourceEscrow.PayoutReceived.selector, _topic0("PayoutReceived"));
        assertEq(ISourceEscrow.PayoutCancelled.selector, _topic0("PayoutCancelled"));
        assertEq(ISourceEscrow.SourceCheckpoint.selector, _topic0("SourceCheckpoint"));
        // signatures from the fixture hash to the same selectors (guards against a renamed fixture entry)
        for (uint256 i = 0; i < 6; i++) {
            string memory sig = vm.parseJsonString(abiJson, string.concat(".events[", vm.toString(i), "].signature"));
            bytes32 t = vm.parseJsonBytes32(abiJson, string.concat(".events[", vm.toString(i), "].topic0"));
            assertEq(keccak256(bytes(sig)), t);
        }
    }

    function test_bindingIsUnconfiguredAndSimulated() public view {
        assertEq(uint8(escrow.partnerSourceBinding()), uint8(ISourceEscrow.PartnerSourceBinding.UNCONFIGURED));
        ISourceAdapter.Capabilities memory c = depin.capabilities();
        assertTrue(c.simulatedRevenue && c.measuredPayouts && c.provableObligation);
        assertEq(depin.sourceContract(), address(escrow));
    }

    // ------------------------------------------------------------------ obligations

    function test_recognize_emitsAndStoresState_thenAssignAndCheckpoint() public {
        vm.expectEmit(true, true, true, true, address(escrow));
        emit ISourceEscrow.ObligationRecognized(ACCT, REF_A, issuer, address(depin), address(escrow), 12_000e6, DUE, 1);
        _recognize(REF_A, 12_000e6);
        ISourceEscrow.Obligation memory o = escrow.obligation(ACCT, REF_A);
        assertEq(uint8(o.status), uint8(ISourceEscrow.ObligationStatus.OPEN));
        assertEq(o.net, 12_000e6);
        assertEq(o.revision, 1);
        assertEq(escrow.accountOpenAmount(ACCT), 12_000e6);

        vm.expectEmit(true, true, true, true, address(escrow));
        emit ISourceEscrow.ObligationAssigned(ACCT, REF_A, FACILITY, 2);
        vm.prank(controller);
        escrow.assignObligation(ACCT, REF_A, FACILITY);
        assertEq(escrow.obligation(ACCT, REF_A).assignedTo, FACILITY);

        vm.expectEmit(true, true, true, true, address(escrow));
        emit ISourceEscrow.SourceCheckpoint(ACCT, 1, 2, 12_000e6, 0);
        vm.prank(issuer);
        escrow.publishCheckpoint(ACCT);
    }

    function test_twoObligationsInOneTx_eachIsItsOwnEvent_andAccountRevisionCounts() public {
        vm.startPrank(issuer);
        escrow.recognizeObligation(ACCT, REF_A, address(depin), address(usdc), 12_000e6, DUE);
        escrow.recognizeObligation(ACCT, REF_B, address(depin), address(usdc), 9000e6, DUE);
        vm.stopPrank();
        assertEq(escrow.obligation(ACCT, REF_A).revision, 1);
        assertEq(escrow.obligation(ACCT, REF_B).revision, 1);
        assertEq(escrow.accountLatestRevision(ACCT), 2, "sum of obligation revisions");
        assertEq(escrow.accountOpenAmount(ACCT), 21_000e6);
    }

    function test_reject_fakeIssuerAndUnknownAccountAndUnadmittedToken() public {
        vm.expectRevert(abi.encodeWithSelector(ISourceEscrow.NotIssuer.selector, mallory));
        vm.prank(mallory);
        escrow.recognizeObligation(ACCT, REF_A, address(depin), address(usdc), 1e6, DUE);

        vm.expectRevert(abi.encodeWithSelector(ISourceEscrow.AccountUnknown.selector, keccak256("nobody")));
        vm.prank(issuer);
        escrow.recognizeObligation(keccak256("nobody"), REF_A, address(depin), address(usdc), 1e6, DUE);

        vm.expectRevert(abi.encodeWithSelector(ISourceEscrow.TokenNotAdmitted.selector, address(0x70)));
        vm.prank(issuer);
        escrow.recognizeObligation(ACCT, REF_A, address(depin), address(0x70), 1e6, DUE);
    }

    function test_reject_reRecognizeExistingRef_andReassignToOtherFacility() public {
        _recognize(REF_A, 12_000e6);
        vm.expectRevert(abi.encodeWithSelector(ISourceEscrow.ObligationExists.selector, ACCT, REF_A));
        _recognize(REF_A, 99_000e6);
        vm.prank(issuer);
        escrow.assignObligation(ACCT, REF_A, FACILITY);
        vm.expectRevert(abi.encodeWithSelector(ISourceEscrow.AlreadyAssigned.selector, REF_A, FACILITY));
        vm.prank(issuer);
        escrow.assignObligation(ACCT, REF_A, keccak256("facility-2"));
        vm.expectRevert(abi.encodeWithSelector(ISourceEscrow.NotIssuerOrController.selector, mallory));
        vm.prank(mallory);
        escrow.assignObligation(ACCT, REF_A, FACILITY);
    }

    function test_correction_revisionMonotonic_cannotGoBelowPaid_cancelZeroesOpen() public {
        _recognize(REF_A, 12_000e6);
        _pay(REF_A, 5000e6, "s1"); // revision 2
        vm.expectEmit(true, true, true, true, address(escrow));
        emit ISourceEscrow.ObligationCorrected(ACCT, REF_A, -2000e6, 3, uint8(ISourceEscrow.CorrectionReason.SLA));
        vm.prank(issuer);
        escrow.correctObligation(ACCT, REF_A, -2000e6, ISourceEscrow.CorrectionReason.SLA);
        assertEq(escrow.obligation(ACCT, REF_A).net, 10_000e6);
        assertEq(escrow.accountOpenAmount(ACCT), 5000e6);

        vm.expectRevert(abi.encodeWithSelector(ISourceEscrow.CorrectionBelowPaid.selector, 5000e6, -6000e6));
        vm.prank(issuer);
        escrow.correctObligation(ACCT, REF_A, -6000e6, ISourceEscrow.CorrectionReason.DISPUTE);

        vm.expectRevert(abi.encodeWithSelector(ISourceEscrow.CancelMustZeroOpenAmount.selector, 5000e6, -1000e6));
        vm.prank(issuer);
        escrow.correctObligation(ACCT, REF_A, -1000e6, ISourceEscrow.CorrectionReason.CANCEL);

        vm.prank(issuer);
        escrow.correctObligation(ACCT, REF_A, -5000e6, ISourceEscrow.CorrectionReason.CANCEL);
        ISourceEscrow.Obligation memory o = escrow.obligation(ACCT, REF_A);
        assertEq(uint8(o.status), uint8(ISourceEscrow.ObligationStatus.CANCELLED));
        assertEq(o.revision, 4);
        assertEq(escrow.accountOpenAmount(ACCT), 0);
        // a cancelled ref is single-use: no re-recognition, no further corrections, no payouts
        vm.expectRevert(abi.encodeWithSelector(ISourceEscrow.ObligationExists.selector, ACCT, REF_A));
        _recognize(REF_A, 1e6);
        vm.expectRevert(
            abi.encodeWithSelector(
                ISourceEscrow.ObligationNotOpen.selector, ACCT, REF_A, ISourceEscrow.ObligationStatus.CANCELLED
            )
        );
        vm.prank(issuer);
        escrow.correctObligation(ACCT, REF_A, 1, ISourceEscrow.CorrectionReason.OTHER);
    }

    function test_paidObligation_cannotBeReRecognizedOrPaidAgain() public {
        _recognize(REF_A, 12_000e6);
        _pay(REF_A, 12_000e6, "full");
        ISourceEscrow.Obligation memory o = escrow.obligation(ACCT, REF_A);
        assertEq(uint8(o.status), uint8(ISourceEscrow.ObligationStatus.PAID));
        assertEq(escrow.accountOpenAmount(ACCT), 0);
        vm.expectRevert(abi.encodeWithSelector(ISourceEscrow.ObligationExists.selector, ACCT, REF_A));
        _recognize(REF_A, 12_000e6);
        vm.expectRevert(
            abi.encodeWithSelector(
                ISourceEscrow.ObligationNotOpen.selector, ACCT, REF_A, ISourceEscrow.ObligationStatus.PAID
            )
        );
        _pay(REF_A, 1e6, "again");
    }

    // ------------------------------------------------------------------ receipts

    function test_payout_amountIsMeasuredDelta_andEmitsOnce() public {
        _recognize(REF_A, 12_000e6);
        uint256 before = usdc.balanceOf(address(escrow));
        vm.expectEmit(true, true, true, true, address(escrow));
        emit ISourceEscrow.PayoutReceived(ACCT, REF_A, address(usdc), address(depin), 12_000e6, 1);
        (uint64 seq, uint256 measured) = _pay(REF_A, 12_000e6, "s1");
        assertEq(seq, 1);
        assertEq(measured, 12_000e6);
        assertEq(usdc.balanceOf(address(escrow)) - before, 12_000e6);
        assertEq(escrow.trackedBalance(address(usdc)), 12_000e6);
        assertEq(escrow.accountPaidCumulative(ACCT), 12_000e6);
        ISourceEscrow.Payout memory p = escrow.payout(1);
        assertEq(p.amount, 12_000e6);
        assertEq(p.payer, address(depin));
    }

    function test_reject_sameSettlementIdTwice_andOverpayment() public {
        _recognize(REF_A, 12_000e6);
        _pay(REF_A, 5000e6, "dup");
        vm.expectRevert(
            abi.encodeWithSelector(ISourceEscrow.SettlementIdUsed.selector, address(depin), keccak256("dup"))
        );
        _pay(REF_A, 5000e6, "dup");
        vm.expectRevert(abi.encodeWithSelector(ISourceEscrow.Overpayment.selector, 7000e6, 8000e6));
        _pay(REF_A, 8000e6, "over");
    }

    function test_sweepThenReNotify_needsFreshTransfer_noPayoutFromExistingBalance() public {
        _recognize(REF_A, 12_000e6);
        _pay(REF_A, 5000e6, "s1");
        vm.prank(owner);
        escrow.withdraw(address(usdc), address(0xDEAD), 5000e6);
        assertEq(escrow.trackedBalance(address(usdc)), 0);
        // balance is now 0; a "re-notify" with a new id and no allowance cannot produce a payout
        vm.prank(address(depin));
        vm.expectRevert(ISourceEscrow.TransferFailed.selector);
        escrow.settle(ACCT, REF_A, address(usdc), 5000e6, keccak256("s2"));
        // and a direct transfer into the escrow is not a payout either
        vm.prank(donor);
        usdc.transfer(address(escrow), 5000e6);
        vm.prank(address(depin));
        vm.expectRevert(ISourceEscrow.TransferFailed.selector);
        escrow.settle(ACCT, REF_A, address(usdc), 5000e6, keccak256("s3"));
        assertEq(escrow.obligation(ACCT, REF_A).paid, 5000e6, "unchanged");
    }

    function test_reject_unregisteredPayer_borrowerWallet_wrongTokenOrRecipient() public {
        _recognize(REF_A, 12_000e6);
        vm.prank(borrower);
        usdc.approve(address(escrow), 1000e6);
        vm.expectRevert(abi.encodeWithSelector(ISourceEscrow.NotRegisteredPayer.selector, borrower));
        vm.prank(borrower);
        escrow.settle(ACCT, REF_A, address(usdc), 1000e6, keccak256("self"));
        // borrower wallet can never be registered as a payer, nor a payer as a borrower wallet
        vm.expectRevert(abi.encodeWithSelector(ISourceEscrow.PayerIsBorrowerWallet.selector, borrower));
        vm.prank(owner);
        escrow.setPayer(borrower, true);
        vm.expectRevert(abi.encodeWithSelector(ISourceEscrow.PayerIsBorrowerWallet.selector, address(depin)));
        vm.prank(owner);
        escrow.registerAccount(keccak256("x"), address(depin));
        // wrong token for the obligation
        MockERC20 other = new MockERC20("Other", "OTH", 6);
        other.mint(address(depin), 1e6);
        vm.prank(owner);
        escrow.admitToken(address(other), 6, false);
        vm.expectRevert(
            abi.encodeWithSelector(ISourceEscrow.ObligationTokenMismatch.selector, address(usdc), address(other))
        );
        vm.prank(operator);
        depin.payout(ACCT, REF_A, address(other), 1e6, keccak256("wrongtoken"));
        // wrong account for the obligation ref
        vm.expectRevert(
            abi.encodeWithSelector(
                ISourceEscrow.ObligationNotOpen.selector, ACCT_B, REF_A, ISourceEscrow.ObligationStatus.NONE
            )
        );
        vm.prank(operator);
        depin.payout(ACCT_B, REF_A, address(usdc), 1e6, keccak256("wrongacct"));
    }

    function test_unattributed_selfTransferAndDonation_neverPayout() public {
        vm.startPrank(borrower);
        usdc.approve(address(escrow), 1000e6);
        vm.expectEmit(true, true, true, true, address(escrow));
        emit ISourceEscrow.UnattributedDeposit(
            address(usdc), borrower, 1000e6, 1, ISourceEscrow.UnattributedOrigin.SELF_TRANSFER
        );
        escrow.depositUnattributed(address(usdc), 1000e6);
        vm.stopPrank();

        vm.startPrank(donor);
        usdc.approve(address(escrow), 500e6);
        vm.expectEmit(true, true, true, true, address(escrow));
        emit ISourceEscrow.UnattributedDeposit(
            address(usdc), donor, 500e6, 2, ISourceEscrow.UnattributedOrigin.THIRD_PARTY_UNKNOWN
        );
        escrow.depositUnattributed(address(usdc), 500e6);
        usdc.transfer(address(escrow), 250e6); // raw direct transfer
        vm.stopPrank();

        vm.expectEmit(true, true, true, true, address(escrow));
        emit ISourceEscrow.UnattributedDeposit(
            address(usdc), address(0), 250e6, 3, ISourceEscrow.UnattributedOrigin.THIRD_PARTY_UNKNOWN
        );
        escrow.recordDirectDeposit(address(usdc));
        assertEq(escrow.unattributedBalance(address(usdc)), 1750e6);
        assertEq(escrow.trackedBalance(address(usdc)), 1750e6);
        assertEq(escrow.accountPaidCumulative(ACCT), 0, "no payout credited");
        assertEq(escrow.settlementSeq(), 0, "no PayoutReceived");
        vm.expectRevert(abi.encodeWithSelector(ISourceEscrow.NoUnattributedBalance.selector, address(usdc)));
        escrow.recordDirectDeposit(address(usdc));
    }

    function test_feeOnTransfer_rejectedByDefault_creditedOnlyMeasuredWhenAllowed() public {
        FeeOnTransferToken fee = new FeeOnTransferToken(100); // 1%
        fee.mint(address(depin), 10_000e6);
        vm.prank(owner);
        escrow.admitToken(address(fee), 6, false);
        vm.prank(issuer);
        escrow.recognizeObligation(ACCT, REF_B, address(depin), address(fee), 10_000e6, DUE);
        vm.expectRevert(abi.encodeWithSelector(ISourceEscrow.MeasuredDeltaMismatch.selector, 1000e6, 990e6));
        vm.prank(operator);
        depin.payout(ACCT, REF_B, address(fee), 1000e6, keccak256("fee1"));

        vm.prank(owner);
        escrow.admitToken(address(fee), 6, true); // explicit policy
        vm.prank(operator);
        (, uint256 measured) = depin.payout(ACCT, REF_B, address(fee), 1000e6, keccak256("fee2"));
        assertEq(measured, 990e6);
        assertEq(escrow.obligation(ACCT, REF_B).paid, 990e6);
    }

    function test_reentrancy_duringPull_isRejected() public {
        ReenteringToken rt = new ReenteringToken();
        rt.mint(address(depin), 10e6);
        vm.prank(owner);
        escrow.admitToken(address(rt), 6, false);
        rt.arm(escrow, ACCT);
        vm.prank(operator);
        (uint64 seq, uint256 measured) = depin.payout(ACCT, bytes32(0), address(rt), 5e6, keccak256("r1"));
        assertEq(seq, 1);
        assertEq(measured, 5e6);
        assertEq(bytes4(rt.lastRevert()), ISourceEscrow.Reentrancy.selector);
        assertEq(escrow.settlementSeq(), 1, "the re-entered settle did not record a second payout");
    }

    function test_cancelPayout_movesTokensBack_reopensObligation_once() public {
        _recognize(REF_A, 12_000e6);
        (uint64 seq,) = _pay(REF_A, 12_000e6, "full");
        assertEq(uint8(escrow.obligation(ACCT, REF_A).status), uint8(ISourceEscrow.ObligationStatus.PAID));
        uint256 payerBefore = usdc.balanceOf(address(depin));
        vm.expectEmit(true, true, true, true, address(escrow));
        emit ISourceEscrow.PayoutCancelled(ACCT, REF_A, seq, 12_000e6);
        vm.prank(issuer);
        escrow.cancelPayout(seq);
        assertEq(usdc.balanceOf(address(depin)) - payerBefore, 12_000e6);
        ISourceEscrow.Obligation memory o = escrow.obligation(ACCT, REF_A);
        assertEq(uint8(o.status), uint8(ISourceEscrow.ObligationStatus.OPEN));
        assertEq(o.paid, 0);
        assertEq(o.revision, 3);
        assertEq(escrow.accountOpenAmount(ACCT), 12_000e6);
        assertEq(escrow.accountPaidCumulative(ACCT), 0);
        vm.expectRevert(abi.encodeWithSelector(ISourceEscrow.PayoutAlreadyCancelled.selector, seq));
        vm.prank(issuer);
        escrow.cancelPayout(seq);
        vm.expectRevert(abi.encodeWithSelector(ISourceEscrow.NotIssuer.selector, mallory));
        vm.prank(mallory);
        escrow.cancelPayout(seq);
    }

    function test_checkpoint_reflectsRevisionsOpenAndPaid_afterMixedEvents() public {
        _recognize(REF_A, 12_000e6); // acct rev 1
        _recognize(REF_B, 9000e6); // 2
        _pay(REF_A, 4000e6, "p1"); // 3
        vm.prank(issuer);
        escrow.correctObligation(ACCT, REF_B, -1000e6, ISourceEscrow.CorrectionReason.REFUND); // 4
        vm.expectEmit(true, true, true, true, address(escrow));
        emit ISourceEscrow.SourceCheckpoint(ACCT, 1, 4, 16_000e6, 4000e6);
        vm.prank(issuer);
        escrow.publishCheckpoint(ACCT);
        assertEq(
            uint256(escrow.obligation(ACCT, REF_A).revision) + escrow.obligation(ACCT, REF_B).revision,
            escrow.accountLatestRevision(ACCT),
            "sum-of-revisions invariant"
        );
        vm.expectRevert(abi.encodeWithSelector(ISourceEscrow.NotIssuer.selector, mallory));
        vm.prank(mallory);
        escrow.publishCheckpoint(ACCT);
    }

    // ------------------------------------------------------------------ assertions and roles

    function test_statementAnchor_isAssertionOnly_noObligationState() public {
        vm.expectEmit(true, true, true, true, address(escrow));
        emit ISourceEscrow.StatementAnchored(ACCT, keccak256("statement"), anchor);
        vm.prank(anchor);
        escrow.anchorStatement(ACCT, keccak256("statement"));
        assertEq(escrow.accountOpenAmount(ACCT), 0);
        assertEq(escrow.accountLatestRevision(ACCT), 0);
        vm.expectRevert(abi.encodeWithSelector(ISourceEscrow.NotAnchor.selector, issuer));
        vm.prank(issuer);
        escrow.anchorStatement(ACCT, keccak256("statement"));
    }

    function test_roleChanges_emitHistory_andUnauthorizedRevert() public {
        vm.expectEmit(true, true, true, true, address(escrow));
        emit ISourceEscrow.RoleChanged(escrow.ROLE_ISSUER(), issuer, false, owner);
        vm.prank(owner);
        escrow.setIssuer(issuer, false);
        vm.expectRevert(abi.encodeWithSelector(ISourceEscrow.NotIssuer.selector, issuer));
        _recognize(REF_A, 1e6);

        vm.expectRevert(abi.encodeWithSelector(ISourceEscrow.NotOwner.selector, mallory));
        vm.prank(mallory);
        escrow.setIssuer(mallory, true);
        vm.expectRevert(abi.encodeWithSelector(ISourceEscrow.NotOwner.selector, mallory));
        vm.prank(mallory);
        escrow.setUpgradeAdmin(mallory);
        vm.expectRevert(abi.encodeWithSelector(ISourceEscrow.NotOwner.selector, mallory));
        vm.prank(mallory);
        escrow.withdraw(address(usdc), mallory, 1);

        vm.expectEmit(true, true, true, true, address(escrow));
        emit ISourceEscrow.RoleChanged(escrow.ROLE_UPGRADE_ADMIN(), upgradeAdmin, false, owner);
        vm.expectEmit(true, true, true, true, address(escrow));
        emit ISourceEscrow.RoleChanged(escrow.ROLE_UPGRADE_ADMIN(), address(0x0C), true, owner);
        vm.prank(owner);
        escrow.setUpgradeAdmin(address(0x0C));
        assertEq(escrow.upgradeAdmin(), address(0x0C));
    }

    function test_mockOperatorOnly() public {
        vm.expectRevert(abi.encodeWithSelector(MockDePINPayout.NotOperator.selector, mallory));
        vm.prank(mallory);
        depin.payout(ACCT, bytes32(0), address(usdc), 1e6, keccak256("m"));
    }
}
