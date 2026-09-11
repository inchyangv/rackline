// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test, console2} from "forge-std/Test.sol";
import {BtcSpvVerifier} from "../contracts/BtcSpvVerifier.sol";
import {CheckpointManager} from "../contracts/CheckpointManager.sol";
import {ICheckpointManager} from "../contracts/interfaces/ICheckpointManager.sol";
import {IVerifierAdapter, PayoutEvidence} from "../contracts/interfaces/IVerifierAdapter.sol";
import {BitcoinLib} from "../contracts/lib/BitcoinLib.sol";

contract BitcoinLibTest is Test {
    using BitcoinLib for bytes;

    // ============ sha256d Tests ============

    function test_sha256d_emptyBytes() public view {
        bytes memory empty = "";
        bytes32 result = BitcoinLib.sha256d(empty);
        // sha256d("") = sha256(sha256(""))
        // sha256("") = 0xe3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
        // sha256(above) = 0x5df6e0e2761359d30a8275058e299fcc0381534545f55cf43e41983f5d4c9456
        assertEq(result, 0x5df6e0e2761359d30a8275058e299fcc0381534545f55cf43e41983f5d4c9456);
    }

    // ============ bitsToTarget Tests ============

    function test_bitsToTarget_mainnetGenesis() public pure {
        // Genesis block bits: 0x1d00ffff
        uint32 bits = 0x1d00ffff;
        uint256 target = BitcoinLib.bitsToTarget(bits);
        // Expected: 0x00000000ffff0000000000000000000000000000000000000000000000000000
        assertEq(target, 0x00000000ffff0000000000000000000000000000000000000000000000000000);
    }

    function test_bitsToTarget_block800000() public pure {
        // Block 800000 bits: 0x17053894
        uint32 bits = 0x17053894;
        uint256 target = BitcoinLib.bitsToTarget(bits);
        // Expected target is much lower (higher difficulty)
        assertTrue(target < 0x00000000ffff0000000000000000000000000000000000000000000000000000);
        assertTrue(target > 0);
    }

    // ============ parseHeader Tests ============

    function test_parseHeader_rejectsInvalidSize() public {
        bytes memory shortHeader = new bytes(79);
        try this.parseHeaderExternal(shortHeader) {
            fail("Should have reverted");
        } catch (bytes memory reason) {
            bytes4 selector = bytes4(reason);
            assertEq(selector, BitcoinLib.InvalidHeaderSize.selector);
        }
    }

    // Helper function to test library reverts
    function parseHeaderExternal(bytes memory header) external pure returns (BitcoinLib.BlockHeader memory) {
        return BitcoinLib.parseHeader(header);
    }

    function test_parseHeader_validHeader() public pure {
        // Construct a valid 80-byte header (mock data)
        bytes memory header = new bytes(80);

        // Version: 1 (little-endian)
        header[0] = 0x01;
        header[1] = 0x00;
        header[2] = 0x00;
        header[3] = 0x00;

        // PrevBlockHash: 32 bytes of 0xAA
        for (uint i = 4; i < 36; i++) {
            header[i] = 0xAA;
        }

        // MerkleRoot: 32 bytes of 0xBB
        for (uint i = 36; i < 68; i++) {
            header[i] = 0xBB;
        }

        // Timestamp: 0x12345678 (little-endian)
        header[68] = 0x78;
        header[69] = 0x56;
        header[70] = 0x34;
        header[71] = 0x12;

        // Bits: 0x1d00ffff (little-endian)
        header[72] = 0xff;
        header[73] = 0xff;
        header[74] = 0x00;
        header[75] = 0x1d;

        // Nonce: 0xDEADBEEF (little-endian)
        header[76] = 0xEF;
        header[77] = 0xBE;
        header[78] = 0xAD;
        header[79] = 0xDE;

        BitcoinLib.BlockHeader memory parsed = BitcoinLib.parseHeader(header);

        assertEq(parsed.version, 1);
        assertEq(parsed.timestamp, 0x12345678);
        assertEq(parsed.bits, 0x1d00ffff);
        assertEq(parsed.nonce, 0xDEADBEEF);
    }

    // ============ extractPubkeyHash Tests ============

    function test_extractPubkeyHash_P2WPKH() public pure {
        // P2WPKH script: 0x0014 + 20 bytes pubkey hash
        bytes memory script = hex"00141234567890abcdef1234567890abcdef12345678";

        (bytes20 pubkeyHash, uint8 scriptType) = BitcoinLib.extractPubkeyHash(script);

        assertEq(uint8(scriptType), 0); // P2WPKH
        assertEq(pubkeyHash, bytes20(hex"1234567890abcdef1234567890abcdef12345678"));
    }

    function test_extractPubkeyHash_P2PKH() public pure {
        // P2PKH script: 76a914 + 20 bytes + 88ac
        bytes memory script = hex"76a9141234567890abcdef1234567890abcdef1234567888ac";

        (bytes20 pubkeyHash, uint8 scriptType) = BitcoinLib.extractPubkeyHash(script);

        assertEq(uint8(scriptType), 1); // P2PKH
        assertEq(pubkeyHash, bytes20(hex"1234567890abcdef1234567890abcdef12345678"));
    }

    function test_extractPubkeyHash_unsupported() public pure {
        // Some random script
        bytes memory script = hex"deadbeef";

        (, uint8 scriptType) = BitcoinLib.extractPubkeyHash(script);

        assertEq(uint8(scriptType), 2); // Unsupported
    }

    // ============ readVarInt Tests ============

    function test_readVarInt_singleByte() public pure {
        bytes memory data = hex"42";
        (uint256 value, uint256 newOffset) = BitcoinLib.readVarInt(data, 0);
        assertEq(value, 0x42);
        assertEq(newOffset, 1);
    }

    function test_readVarInt_fd() public pure {
        bytes memory data = hex"fd0302"; // 0xfd followed by 0x0203 (little-endian = 515)
        (uint256 value, uint256 newOffset) = BitcoinLib.readVarInt(data, 0);
        assertEq(value, 515);
        assertEq(newOffset, 3);
    }

    // ============ verifyMerkleProof Tests ============

    function test_verifyMerkleProof_singleTx() public view {
        // When there's only one tx, txid = merkleRoot, proof is empty
        bytes32 txid = keccak256("test tx");
        bytes32 merkleRoot = txid;
        bytes32[] memory proof = new bytes32[](0);

        bool valid = BitcoinLib.verifyMerkleProof(txid, merkleRoot, proof, 0);
        assertTrue(valid);
    }

    function test_verifyMerkleProof_twoTxs_leftPosition() public view {
        // Two txs: txA (index 0) and txB (index 1)
        // merkleRoot = sha256d(txA || txB)
        bytes32 txA = keccak256("txA");
        bytes32 txB = keccak256("txB");

        bytes32 merkleRoot = BitcoinLib.sha256d(abi.encodePacked(txA, txB));

        bytes32[] memory proof = new bytes32[](1);
        proof[0] = txB;

        bool valid = BitcoinLib.verifyMerkleProof(txA, merkleRoot, proof, 0);
        assertTrue(valid);
    }

    function test_verifyMerkleProof_twoTxs_rightPosition() public view {
        bytes32 txA = keccak256("txA");
        bytes32 txB = keccak256("txB");

        bytes32 merkleRoot = BitcoinLib.sha256d(abi.encodePacked(txA, txB));

        bytes32[] memory proof = new bytes32[](1);
        proof[0] = txA;

        bool valid = BitcoinLib.verifyMerkleProof(txB, merkleRoot, proof, 1);
        assertTrue(valid);
    }

    function test_verifyMerkleProof_invalidProof() public view {
        bytes32 txA = keccak256("txA");
        bytes32 txB = keccak256("txB");
        bytes32 wrongRoot = keccak256("wrong");

        bytes32[] memory proof = new bytes32[](1);
        proof[0] = txB;

        bool valid = BitcoinLib.verifyMerkleProof(txA, wrongRoot, proof, 0);
        assertFalse(valid);
    }
}

contract BtcSpvVerifierTest is Test {
    BtcSpvVerifier public verifier;
    CheckpointManager public checkpointManager;
    address public owner;
    address public borrower;

    // Sample checkpoint data
    bytes32 constant CHECKPOINT_HASH = 0x00000000000000000002a7c4c1e48d76c5a37902165a270156b7a8d72728a054;
    uint32 constant CHECKPOINT_HEIGHT = 800000;
    uint32 constant CHECKPOINT_TIMESTAMP = 1690000000;

    // Sample borrower pubkey hash
    bytes20 constant BORROWER_PUBKEY_HASH = bytes20(hex"1234567890abcdef1234567890abcdef12345678");

    function setUp() public {
        owner = makeAddr("owner");
        borrower = makeAddr("borrower");

        vm.startPrank(owner);

        // Deploy CheckpointManager
        checkpointManager = new CheckpointManager(owner);

        // Deploy BtcSpvVerifier
        verifier = new BtcSpvVerifier(owner, address(checkpointManager));

        // Set checkpoint
        checkpointManager.setCheckpoint(
            CHECKPOINT_HEIGHT,
            CHECKPOINT_HASH,
            0, // chainWork
            CHECKPOINT_TIMESTAMP
        );

        // Register borrower's pubkey hash
        verifier.setBorrowerPubkeyHash(borrower, BORROWER_PUBKEY_HASH);

        vm.stopPrank();
    }

    // ============ Constructor Tests ============

    function test_constructor_setsOwner() public view {
        assertEq(verifier.owner(), owner);
    }

    function test_constructor_setsCheckpointManager() public view {
        assertEq(address(verifier.checkpointManager()), address(checkpointManager));
    }

    function test_constructor_revertsIfZeroOwner() public {
        vm.expectRevert(BtcSpvVerifier.InvalidAddress.selector);
        new BtcSpvVerifier(address(0), address(checkpointManager));
    }

    function test_constructor_revertsIfZeroCheckpointManager() public {
        vm.expectRevert(BtcSpvVerifier.InvalidAddress.selector);
        new BtcSpvVerifier(owner, address(0));
    }

    // ============ setBorrowerPubkeyHash Tests ============

    function test_setBorrowerPubkeyHash_success() public {
        address newBorrower = makeAddr("newBorrower");
        bytes20 newHash = bytes20(hex"deadbeefdeadbeefdeadbeefdeadbeefdeadbeef");

        vm.prank(owner);
        verifier.setBorrowerPubkeyHash(newBorrower, newHash);

        assertEq(verifier.getBorrowerPubkeyHash(newBorrower), newHash);
    }

    function test_setBorrowerPubkeyHash_revertsIfNotOwner() public {
        vm.prank(makeAddr("attacker"));
        vm.expectRevert(BtcSpvVerifier.Unauthorized.selector);
        verifier.setBorrowerPubkeyHash(borrower, bytes20(0));
    }

    function test_setBorrowerPubkeyHash_revertsIfZeroAddress() public {
        vm.prank(owner);
        vm.expectRevert(BtcSpvVerifier.InvalidAddress.selector);
        verifier.setBorrowerPubkeyHash(address(0), BORROWER_PUBKEY_HASH);
    }

    // ============ isPayoutProcessed Tests ============

    function test_isPayoutProcessed_returnsFalseInitially() public view {
        bytes32 txid = keccak256("some tx");
        assertFalse(verifier.isPayoutProcessed(txid, 0));
    }

    // ============ Ownership Tests ============

    function test_transferOwnership_success() public {
        address newOwner = makeAddr("newOwner");

        vm.prank(owner);
        verifier.transferOwnership(newOwner);

        assertEq(verifier.owner(), newOwner);
    }

    function test_transferOwnership_revertsIfNotOwner() public {
        vm.prank(makeAddr("attacker"));
        vm.expectRevert(BtcSpvVerifier.Unauthorized.selector);
        verifier.transferOwnership(makeAddr("newOwner"));
    }

    // ============ verifyPayout Tests (Structural) ============

    function test_verifyPayout_revertsIfHeaderChainTooLong() public {
        bytes[] memory headers = new bytes[](145); // > MAX_HEADER_CHAIN
        for (uint i = 0; i < 145; i++) {
            headers[i] = new bytes(80);
        }

        BtcSpvVerifier.SpvProof memory proof = BtcSpvVerifier.SpvProof({
            checkpointHeight: CHECKPOINT_HEIGHT,
            headers: headers,
            rawTx: hex"01000000",
            merkleProof: new bytes32[](0),
            txIndex: 0,
            outputIndex: 0,
            borrower: borrower
        });

        bytes memory encodedProof = abi.encode(proof);

        vm.expectRevert(BtcSpvVerifier.HeaderChainTooLong.selector);
        verifier.verifyPayout(encodedProof);
    }

    function test_verifyPayout_revertsIfMerkleProofTooLong() public {
        bytes[] memory headers = new bytes[](6);
        for (uint i = 0; i < 6; i++) {
            headers[i] = new bytes(80);
        }

        bytes32[] memory merkleProof = new bytes32[](21); // > MAX_MERKLE_DEPTH

        BtcSpvVerifier.SpvProof memory proof = BtcSpvVerifier.SpvProof({
            checkpointHeight: CHECKPOINT_HEIGHT,
            headers: headers,
            rawTx: hex"01000000",
            merkleProof: merkleProof,
            txIndex: 0,
            outputIndex: 0,
            borrower: borrower
        });

        bytes memory encodedProof = abi.encode(proof);

        vm.expectRevert(BtcSpvVerifier.MerkleProofTooLong.selector);
        verifier.verifyPayout(encodedProof);
    }

    function test_verifyPayout_revertsIfTxTooLarge() public {
        bytes[] memory headers = new bytes[](6);
        for (uint i = 0; i < 6; i++) {
            headers[i] = new bytes(80);
        }

        bytes memory largeTx = new bytes(4097); // > MAX_TX_SIZE

        BtcSpvVerifier.SpvProof memory proof = BtcSpvVerifier.SpvProof({
            checkpointHeight: CHECKPOINT_HEIGHT,
            headers: headers,
            rawTx: largeTx,
            merkleProof: new bytes32[](0),
            txIndex: 0,
            outputIndex: 0,
            borrower: borrower
        });

        bytes memory encodedProof = abi.encode(proof);

        vm.expectRevert(BtcSpvVerifier.TxTooLarge.selector);
        verifier.verifyPayout(encodedProof);
    }

    function test_verifyPayout_revertsIfInsufficientConfirmations() public {
        bytes[] memory headers = new bytes[](5); // < MIN_CONFIRMATIONS (6)
        for (uint i = 0; i < 5; i++) {
            headers[i] = new bytes(80);
        }

        BtcSpvVerifier.SpvProof memory proof = BtcSpvVerifier.SpvProof({
            checkpointHeight: CHECKPOINT_HEIGHT,
            headers: headers,
            rawTx: hex"01000000",
            merkleProof: new bytes32[](0),
            txIndex: 0,
            outputIndex: 0,
            borrower: borrower
        });

        bytes memory encodedProof = abi.encode(proof);

        vm.expectRevert(BtcSpvVerifier.InsufficientConfirmations.selector);
        verifier.verifyPayout(encodedProof);
    }

    function test_verifyPayout_revertsIfBorrowerNotRegistered() public {
        address unregisteredBorrower = makeAddr("unregistered");

        bytes[] memory headers = new bytes[](6);
        for (uint i = 0; i < 6; i++) {
            headers[i] = new bytes(80);
        }

        BtcSpvVerifier.SpvProof memory proof = BtcSpvVerifier.SpvProof({
            checkpointHeight: CHECKPOINT_HEIGHT,
            headers: headers,
            rawTx: hex"01000000",
            merkleProof: new bytes32[](0),
            txIndex: 0,
            outputIndex: 0,
            borrower: unregisteredBorrower
        });

        bytes memory encodedProof = abi.encode(proof);

        vm.expectRevert(BtcSpvVerifier.BorrowerNotRegistered.selector);
        verifier.verifyPayout(encodedProof);
    }

    function test_verifyPayout_revertsIfInvalidCheckpoint() public {
        bytes[] memory headers = new bytes[](6);
        for (uint i = 0; i < 6; i++) {
            headers[i] = new bytes(80);
        }

        BtcSpvVerifier.SpvProof memory proof = BtcSpvVerifier.SpvProof({
            checkpointHeight: 999999, // Non-existent checkpoint
            headers: headers,
            rawTx: hex"01000000",
            merkleProof: new bytes32[](0),
            txIndex: 0,
            outputIndex: 0,
            borrower: borrower
        });

        bytes memory encodedProof = abi.encode(proof);

        vm.expectRevert(BtcSpvVerifier.InvalidCheckpoint.selector);
        verifier.verifyPayout(encodedProof);
    }

    // ============ Constants Tests ============

    function test_constants() public view {
        assertEq(verifier.MAX_HEADER_CHAIN(), 144);
        assertEq(verifier.MAX_MERKLE_DEPTH(), 20);
        assertEq(verifier.MAX_TX_SIZE(), 4096);
        assertEq(verifier.MIN_CONFIRMATIONS(), 6);
    }
}
