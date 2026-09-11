// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import { Test, console } from "forge-std/Test.sol";
import { RelayerSigVerifier } from "../contracts/RelayerSigVerifier.sol";
import { PayoutEvidence } from "../contracts/interfaces/IVerifierAdapter.sol";

/**
 * @title RelayerSigVerifierTest
 * @notice Tests for RelayerSigVerifier EIP-712 implementation
 */
contract RelayerSigVerifierTest is Test {
    RelayerSigVerifier public verifier;

    // Relayer private key and address (for testing)
    uint256 public constant RELAYER_PRIVATE_KEY = 0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef;
    address public relayerSigner;

    address public owner = address(this);
    address public alice = address(0xA11CE);

    function setUp() public {
        // Derive relayer address from private key
        relayerSigner = vm.addr(RELAYER_PRIVATE_KEY);

        // Deploy verifier
        verifier = new RelayerSigVerifier(relayerSigner);
    }

    // ============================================
    // Deployment Tests
    // ============================================

    function test_deployment() public view {
        assertEq(verifier.owner(), owner);
        assertEq(verifier.relayerSigner(), relayerSigner);
        assertTrue(verifier.DOMAIN_SEPARATOR() != bytes32(0));
    }

    function test_revert_zeroSigner() public {
        vm.expectRevert(RelayerSigVerifier.InvalidAddress.selector);
        new RelayerSigVerifier(address(0));
    }

    // ============================================
    // Signature Verification Tests
    // ============================================

    function test_verifyPayout() public {
        // Create payout claim
        address borrower = alice;
        bytes32 txid = bytes32(uint256(1));
        uint32 vout = 0;
        uint64 amountSats = 100_000_000; // 1 BTC
        uint32 blockHeight = 800_000;
        uint32 blockTimestamp = uint32(block.timestamp);
        uint256 deadline = block.timestamp + 1 hours;

        // Get digest
        bytes32 digest =
            verifier.getPayoutClaimDigest(borrower, txid, vout, amountSats, blockHeight, blockTimestamp, deadline);

        // Sign with relayer key
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(RELAYER_PRIVATE_KEY, digest);
        bytes memory signature = abi.encodePacked(r, s, v);

        // Encode proof
        bytes memory proof =
            abi.encode(borrower, txid, vout, amountSats, blockHeight, blockTimestamp, deadline, signature);

        // Verify
        PayoutEvidence memory evidence = verifier.verifyPayout(proof);

        assertEq(evidence.borrower, borrower);
        assertEq(evidence.txid, txid);
        assertEq(evidence.vout, vout);
        assertEq(evidence.amountSats, amountSats);
        assertEq(evidence.blockHeight, blockHeight);
        assertEq(evidence.blockTimestamp, blockTimestamp);
    }

    function test_verifyPayout_multiplePayouts() public {
        // First payout
        bytes memory proof1 = _createSignedProof(alice, bytes32(uint256(1)), 0, 100_000_000);
        verifier.verifyPayout(proof1);

        // Second payout (different txid)
        bytes memory proof2 = _createSignedProof(alice, bytes32(uint256(2)), 0, 200_000_000);
        PayoutEvidence memory evidence2 = verifier.verifyPayout(proof2);

        assertEq(evidence2.amountSats, 200_000_000);
    }

    function test_verifyPayout_revert_invalidSignature() public {
        // Create proof with wrong signer
        uint256 wrongKey = 0xdeadbeef;
        address borrower = alice;
        bytes32 txid = bytes32(uint256(1));
        uint32 vout = 0;
        uint64 amountSats = 100_000_000;
        uint32 blockHeight = 800_000;
        uint32 blockTimestamp = uint32(block.timestamp);
        uint256 deadline = block.timestamp + 1 hours;

        bytes32 digest =
            verifier.getPayoutClaimDigest(borrower, txid, vout, amountSats, blockHeight, blockTimestamp, deadline);

        (uint8 v, bytes32 r, bytes32 s) = vm.sign(wrongKey, digest);
        bytes memory signature = abi.encodePacked(r, s, v);

        bytes memory proof =
            abi.encode(borrower, txid, vout, amountSats, blockHeight, blockTimestamp, deadline, signature);

        vm.expectRevert(RelayerSigVerifier.InvalidSignature.selector);
        verifier.verifyPayout(proof);
    }

    function test_verifyPayout_revert_deadlineExpired() public {
        uint256 pastDeadline = block.timestamp - 1;
        bytes memory proof = _createSignedProofWithDeadline(alice, bytes32(uint256(1)), 0, 100_000_000, pastDeadline);

        vm.expectRevert(RelayerSigVerifier.DeadlineExpired.selector);
        verifier.verifyPayout(proof);
    }

    function test_verifyPayout_noReplayCheckInVerifier() public {
        bytes memory proof = _createSignedProof(alice, bytes32(uint256(1)), 0, 100_000_000);

        // First verification succeeds
        verifier.verifyPayout(proof);

        // Second verification also succeeds - verifier is stateless
        // Replay protection is handled by HashCreditManager, not verifier
        // This prevents griefing attacks where attacker calls verifier directly
        verifier.verifyPayout(proof);
    }

    function test_verifyPayout_sameVoutDifferentTxid() public {
        // Same vout, different txids should work
        bytes memory proof1 = _createSignedProof(alice, bytes32(uint256(1)), 0, 100_000_000);
        bytes memory proof2 = _createSignedProof(alice, bytes32(uint256(2)), 0, 100_000_000);

        verifier.verifyPayout(proof1);
        verifier.verifyPayout(proof2); // Should succeed

        // Verifier always returns false - it's stateless
        assertFalse(verifier.isPayoutProcessed(bytes32(uint256(1)), 0));
        assertFalse(verifier.isPayoutProcessed(bytes32(uint256(2)), 0));
    }

    function test_griefingPrevention() public {
        bytes memory proof = _createSignedProof(alice, bytes32(uint256(1)), 0, 100_000_000);

        // Attacker calls verifier directly
        address attacker = makeAddr("attacker");
        vm.prank(attacker);
        verifier.verifyPayout(proof);

        // Legitimate call still works because verifier is stateless
        // In real scenario, HashCreditManager.submitPayout would handle replay protection
        verifier.verifyPayout(proof);
    }

    // ============================================
    // Admin Tests
    // ============================================

    function test_setRelayerSigner() public {
        address newSigner = address(0x9999);
        verifier.setRelayerSigner(newSigner);
        assertEq(verifier.relayerSigner(), newSigner);
    }

    function test_setRelayerSigner_revert_notOwner() public {
        vm.prank(alice);
        vm.expectRevert(RelayerSigVerifier.Unauthorized.selector);
        verifier.setRelayerSigner(address(0x9999));
    }

    function test_setRelayerSigner_revert_zeroAddress() public {
        vm.expectRevert(RelayerSigVerifier.InvalidAddress.selector);
        verifier.setRelayerSigner(address(0));
    }

    function test_transferOwnership() public {
        address newOwner = address(0x8888);
        verifier.transferOwnership(newOwner);
        assertEq(verifier.owner(), newOwner);
    }

    // ============================================
    // View Function Tests
    // ============================================

    function test_isPayoutProcessed_alwaysFalse() public {
        bytes32 txid = bytes32(uint256(1));
        uint32 vout = 0;

        // Verifier is stateless - always returns false
        assertFalse(verifier.isPayoutProcessed(txid, vout));

        bytes memory proof = _createSignedProof(alice, txid, vout, 100_000_000);
        verifier.verifyPayout(proof);

        // Still returns false - replay protection is in HashCreditManager
        assertFalse(verifier.isPayoutProcessed(txid, vout));
    }

    function test_getPayoutClaimDigest() public view {
        bytes32 digest = verifier.getPayoutClaimDigest(
            alice, bytes32(uint256(1)), 0, 100_000_000, 800_000, uint32(block.timestamp), block.timestamp + 1 hours
        );

        // Digest should be deterministic
        bytes32 digest2 = verifier.getPayoutClaimDigest(
            alice, bytes32(uint256(1)), 0, 100_000_000, 800_000, uint32(block.timestamp), block.timestamp + 1 hours
        );

        assertEq(digest, digest2);
    }

    // ============================================
    // Helper Functions
    // ============================================

    function _createSignedProof(address borrower, bytes32 txid, uint32 vout, uint64 amountSats)
        internal
        view
        returns (bytes memory)
    {
        return _createSignedProofWithDeadline(borrower, txid, vout, amountSats, block.timestamp + 1 hours);
    }

    function _createSignedProofWithDeadline(
        address borrower,
        bytes32 txid,
        uint32 vout,
        uint64 amountSats,
        uint256 deadline
    ) internal view returns (bytes memory) {
        uint32 blockHeight = 800_000;
        uint32 blockTimestamp = uint32(block.timestamp);

        bytes32 digest =
            verifier.getPayoutClaimDigest(borrower, txid, vout, amountSats, blockHeight, blockTimestamp, deadline);

        (uint8 v, bytes32 r, bytes32 s) = vm.sign(RELAYER_PRIVATE_KEY, digest);
        bytes memory signature = abi.encodePacked(r, s, v);

        return abi.encode(borrower, txid, vout, amountSats, blockHeight, blockTimestamp, deadline, signature);
    }
}
