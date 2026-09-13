// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import { GPU036Fixture } from "../GPU036DrawTest.t.sol";
import { GpuTypes } from "../../../contracts/gpu/types/GpuTypes.sol";
import { IReceivableBook } from "../../../contracts/gpu/interfaces/IReceivableBook.sol";

interface IGpuAdmissionBoundary {
    function exercise(uint8 action, uint64 seed) external;
}

/// @notice Every failed assertion becomes a persistent invariant failure; no caught failure is silently skipped.
contract GPU055AdmissionHandler {
    IGpuAdmissionBoundary public immutable FIXTURE;
    uint256 public failures;
    mapping(uint8 => uint256) public calls;

    constructor(IGpuAdmissionBoundary fixture) {
        FIXTURE = fixture;
    }

    function _run(uint8 action, uint64 seed) internal {
        calls[action]++;
        try FIXTURE.exercise(action, seed) { }
        catch {
            failures++;
        }
    }

    function invalidNative(uint64 seed) external {
        _run(0, seed);
    }

    function unsupportedNative(uint64 seed) external {
        _run(1, seed);
    }

    function proofDelay(uint64 seed) external {
        _run(2, seed);
    }

    function supplementarySignature(uint64 seed) external {
        _run(3, seed);
    }

    function verifierGovernance(uint64 seed) external {
        _run(4, seed);
    }

    function policyChange(uint64 seed) external {
        _run(5, seed);
    }

    function controlChange(uint64 seed) external {
        _run(6, seed);
    }

    function paidRepledge(uint64 seed) external {
        _run(7, seed);
    }
}

/// @notice LOCAL_MOCK adversarial companion to the stateful independent financial reference handler.
/// Each temporary fault is restored AFTER assertions, preserving repeated useful attempts instead of leaving
/// all later handlers behind one permanent pause. This is not a substitute for genuine native-testnet proofs.
contract GPU055AdmissionInvariantTest is GPU036Fixture, IGpuAdmissionBoundary {
    GPU055AdmissionHandler handler;

    function setUp() public override {
        super.setUp();
        _readyA();
        _borrow(1000e6);
        vm.startPrank(admin);
        ledger.finalizeWiring();
        vault.finalizeWiring();
        ctl.finalizeWiring();
        evidence.finalizeWiring();
        vm.stopPrank();
        handler = new GPU055AdmissionHandler(this);
        bytes4[] memory selectors = new bytes4[](8);
        selectors[0] = handler.invalidNative.selector;
        selectors[1] = handler.unsupportedNative.selector;
        selectors[2] = handler.proofDelay.selector;
        selectors[3] = handler.supplementarySignature.selector;
        selectors[4] = handler.verifierGovernance.selector;
        selectors[5] = handler.policyChange.selector;
        selectors[6] = handler.controlChange.selector;
        selectors[7] = handler.paidRepledge.selector;
        targetSelector(FuzzSelector({ addr: address(handler), selectors: selectors }));
        targetContract(address(handler));
    }

    function exercise(uint8 action, uint64 seed) external {
        require(msg.sender == address(handler), "handler only");
        uint256 snapshot = vm.snapshotState();
        if (action <= 1) {
            _rejectProof(action, seed);
        } else if (action == 4) {
            _rejectGovernance();
        } else {
            if (action == 2 || action == 3) {
                vm.warp(block.timestamp + 16 minutes + uint256(seed) % 1 days);
                if (action == 3) _anchor(_auth(FA, 50_000e6));
            } else if (action == 5) {
                _publishPolicy(keccak256(abi.encode("mutation", seed)), 100_000e6, 100_000e6, 100_000e6, 100_000e6);
            } else if (action == 6) {
                vm.prank(servicer);
                control.observe(AGR_A, GpuTypes.ControlGrade.E1, ESCROW);
            } else {
                vm.warp(block.timestamp + 16 minutes);
                bytes memory payout = abi.encode(PAYER, uint256(12_000e6), uint64(1));
                bytes32 tokenTopic = bytes32(uint256(uint160(USDC)));
                uint256 debt = ledger.legalDebtAt(FA, uint64(block.timestamp));
                uint256 nav = vault.nav();
                _ingestOne(
                    T_PAYOUT,
                    _log(T_PAYOUT, ACCOUNT_A, REF_A, tokenTopic, 4, payout),
                    _claim(0, ACCOUNT_A, REF_A, tokenTopic, payout)
                );
                _checkpoint(ACCOUNT_A, 2, 4, 9000e6, 12_000e6);
                assertEq(ledger.legalDebtAt(FA, uint64(block.timestamp)), debt);
                assertEq(vault.nav(), nav);
            }
            _drawMustFailAndCashRepayMustWork();
        }
        assertTrue(vm.revertToStateAndDelete(snapshot));
    }

    function _rejectProof(uint8 action, uint64 seed) internal {
        bytes32 ref = keccak256(abi.encode("invalid-proof", seed));
        bytes memory data = abi.encode(PAYER, ESCROW, USDC, uint256(1e6), DUE_AT, uint32(1));
        bytes32 issuer = bytes32(uint256(uint160(ISSUER)));
        Log[] memory logs = new Log[](1);
        logs[0] = _log(T_RECOGNIZED, ACCOUNT_A, ref, issuer, 4, data);
        GpuTypes.NativeProofEnvelope memory envelope = _envelope(_txBytes(1, logs), nextHeight++, 0);
        if (action == 0) prover.setResult(false);
        else envelope.chainKey = 2;
        IReceivableBook.ReceivableClaim[] memory claims = new IReceivableBook.ReceivableClaim[](1);
        claims[0] = _claim(0, ACCOUNT_A, ref, issuer, data);
        uint256 navBefore = vault.nav();
        vm.prank(relayer);
        (bool ok,) =
            address(book).call(abi.encodeCall(book.ingest, (MOCK, envelope, ESCROW, _topics(T_RECOGNIZED), claims)));
        assertFalse(ok);
        assertFalse(evidence.isConsumed(verifier.sourceEventId(envelope.height, 0, 0)));
        assertEq(vault.nav(), navBefore);
        assertEq(ledger.view_(FA).principal, 1000e6);
        // Native outage does not invalidate old policy-valid facts, but does not recognize new facts either.
        _cashRepay();
    }

    function _rejectGovernance() internal {
        vm.prank(admin);
        (bool verifierChanged,) = address(evidence).call(abi.encodeCall(evidence.bindVerifier, (MOCK, verifier)));
        assertFalse(verifierChanged);
        vm.prank(admin);
        (bool writerAdded,) = address(ledger).call(abi.encodeCall(ledger.setWriter, (mallory, true)));
        assertFalse(writerAdded);
        vm.prank(admin);
        (bool consumerAdded,) = address(evidence).call(abi.encodeCall(evidence.setConsumer, (mallory, true)));
        assertFalse(consumerAdded);
        vm.prank(mallory);
        (bool draw,) = address(mgr).call(abi.encodeCall(mgr.borrow, (FA, uint256(1), uint256(0))));
        assertFalse(draw);
        _cashRepay();
    }

    function _drawMustFailAndCashRepayMustWork() internal {
        uint256 principalBefore = ledger.view_(FA).principal;
        vm.prank(borrowerWallet);
        (bool ok,) = address(mgr).call(abi.encodeCall(mgr.borrow, (FA, uint256(1), uint256(0))));
        assertFalse(ok);
        assertEq(ledger.view_(FA).principal, principalBefore);
        _cashRepay();
    }

    function _cashRepay() internal {
        uint256 debtBefore = ledger.legalDebtAt(FA, uint64(block.timestamp));
        uint256 cashBefore = loan.balanceOf(address(vault));
        vm.startPrank(borrowerWallet);
        loan.approve(address(mgr), 1e6);
        GpuTypes.RepayResult memory result = mgr.repayFor(FA, 1e6);
        vm.stopPrank();
        assertEq(result.applied, 1e6);
        assertEq(result.newDebt, debtBefore - 1e6);
        assertEq(loan.balanceOf(address(vault)), cashBefore + 1e6);
        assertEq(result.interestPaid + result.principalPaid + result.feePaid, result.applied);
    }

    function invariant_allAdmissionBoundaryAttemptsStayFailClosed() public view {
        assertEq(handler.failures(), 0, "boundary assertion failed; no caught error may be hidden");
        assertEq(ledger.view_(FA).principal, 1000e6);
        assertEq(vault.nav(), LP_CASH);
        assertEq(loan.balanceOf(address(vault)), LP_CASH - 1000e6);
    }
}
