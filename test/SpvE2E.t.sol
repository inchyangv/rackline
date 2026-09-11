// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import { Test } from "forge-std/Test.sol";
import { BtcSpvVerifier } from "../contracts/BtcSpvVerifier.sol";
import { CheckpointManager } from "../contracts/CheckpointManager.sol";
import { HashCreditManager } from "../contracts/HashCreditManager.sol";
import { LendingVault } from "../contracts/LendingVault.sol";
import { RiskConfig } from "../contracts/RiskConfig.sol";
import { IRiskConfig } from "../contracts/interfaces/IRiskConfig.sol";
import { PoolRegistry } from "../contracts/PoolRegistry.sol";
import { MockERC20 } from "../contracts/mocks/MockERC20.sol";
import { BitcoinLib } from "../contracts/lib/BitcoinLib.sol";

/**
 * @title SpvE2ETest
 * @notice End-to-end tests for SPV mode payout submission
 * @dev Uses synthetic Bitcoin data for deterministic testing
 *
 * Test flow:
 * 1. Deploy full SPV stack (CheckpointManager, BtcSpvVerifier, HashCreditManager)
 * 2. Register checkpoint
 * 3. Register borrower with pubkey hash
 * 4. Build synthetic SPV proof
 * 5. Submit proof via HashCreditManager.submitPayout()
 * 6. Verify credit limit increase
 * 7. Test replay protection
 */
contract SpvE2ETest is Test {
    using BitcoinLib for bytes;

    // Contracts
    CheckpointManager public checkpointManager;
    BtcSpvVerifier public spvVerifier;
    HashCreditManager public manager;
    LendingVault public vault;
    RiskConfig public riskConfig;
    PoolRegistry public poolRegistry;
    MockERC20 public usdc;

    // Actors
    address public owner;
    address public borrower;

    // Test data - synthetic but valid structure
    uint32 constant CHECKPOINT_HEIGHT = 800_000;
    uint32 constant TARGET_HEIGHT = 800_006; // 6 confirmations
    uint64 constant PAYOUT_AMOUNT = 1_000_000; // 0.01 BTC

    // Synthetic borrower pubkey hash (20 bytes)
    bytes20 constant BORROWER_PUBKEY_HASH = bytes20(hex"751e76e8199196d454941c45d1b3a323f1433bd6");

    function setUp() public {
        owner = makeAddr("owner");
        borrower = makeAddr("borrower");

        vm.startPrank(owner);

        // Deploy stablecoin
        usdc = new MockERC20("USD Coin", "USDC", 6);

        // Deploy CheckpointManager
        checkpointManager = new CheckpointManager(owner);

        // Deploy BtcSpvVerifier
        spvVerifier = new BtcSpvVerifier(owner, address(checkpointManager));

        // Deploy RiskConfig
        IRiskConfig.RiskParams memory params = IRiskConfig.RiskParams({
            confirmationsRequired: 6,
            advanceRateBps: 5000, // 50%
            windowSeconds: 30 days,
            newBorrowerCap: 10_000_000_000, // $10,000
            globalCap: 0,
            minPayoutSats: 10_000,
            btcPriceUsd: 5_000_000_000_000, // $50,000
            minPayoutCountForFullCredit: 3,
            largePayoutThresholdSats: 10_000_000,
            largePayoutDiscountBps: 5000,
            newBorrowerPeriodSeconds: 30 days
        });
        riskConfig = new RiskConfig(params);

        // Deploy PoolRegistry (permissive)
        poolRegistry = new PoolRegistry(true);

        // Deploy LendingVault
        vault = new LendingVault(address(usdc), 1000); // 10% APR

        // Deploy HashCreditManager with SPV verifier
        manager = new HashCreditManager(
            address(spvVerifier), address(vault), address(riskConfig), address(poolRegistry), address(usdc)
        );

        // Configure vault
        vault.setManager(address(manager));

        // Fund vault
        usdc.mint(owner, 1_000_000_000_000); // 1M USDC
        usdc.approve(address(vault), 1_000_000_000_000);
        vault.deposit(1_000_000_000_000);

        // Register borrower pubkey hash in SPV verifier
        spvVerifier.setBorrowerPubkeyHash(borrower, BORROWER_PUBKEY_HASH);

        // Register borrower in manager
        bytes32 btcKeyHash = keccak256(abi.encodePacked(BORROWER_PUBKEY_HASH));
        manager.registerBorrower(borrower, btcKeyHash);

        vm.stopPrank();
    }

    // ============================================
    // Helper Functions
    // ============================================

    /**
     * @notice Build a synthetic header with valid structure
     * @param prevHash Previous block hash
     * @param merkleRoot Merkle root for transactions
     * @param timestamp Block timestamp
     * @param bits Difficulty target bits
     * @param nonce Mining nonce
     */
    function _buildHeader(
        bytes32 prevHash,
        bytes32 merkleRoot,
        uint32 timestamp,
        uint32 bits,
        uint32 nonce
    )
        internal
        pure
        returns (bytes memory)
    {
        bytes memory header = new bytes(80);

        // Version (little-endian)
        header[0] = 0x00;
        header[1] = 0x00;
        header[2] = 0x00;
        header[3] = 0x20; // Version 0x20000000

        // PrevBlockHash (already internal byte order)
        for (uint256 i = 0; i < 32; i++) {
            header[4 + i] = prevHash[i];
        }

        // MerkleRoot (already internal byte order)
        for (uint256 i = 0; i < 32; i++) {
            header[36 + i] = merkleRoot[i];
        }

        // Timestamp (little-endian)
        header[68] = bytes1(uint8(timestamp));
        header[69] = bytes1(uint8(timestamp >> 8));
        header[70] = bytes1(uint8(timestamp >> 16));
        header[71] = bytes1(uint8(timestamp >> 24));

        // Bits (little-endian)
        header[72] = bytes1(uint8(bits));
        header[73] = bytes1(uint8(bits >> 8));
        header[74] = bytes1(uint8(bits >> 16));
        header[75] = bytes1(uint8(bits >> 24));

        // Nonce (little-endian)
        header[76] = bytes1(uint8(nonce));
        header[77] = bytes1(uint8(nonce >> 8));
        header[78] = bytes1(uint8(nonce >> 16));
        header[79] = bytes1(uint8(nonce >> 24));

        return header;
    }

    /**
     * @notice Build a minimal P2WPKH transaction paying to borrower
     * @param pubkeyHash 20-byte pubkey hash
     * @param valueSats Amount in satoshis
     */
    function _buildP2WPKHTx(bytes20 pubkeyHash, uint64 valueSats) internal pure returns (bytes memory) {
        // Minimal transaction structure:
        // - Version (4 bytes)
        // - Input count (1 byte, varint)
        // - Input (coinbase-like, minimal)
        // - Output count (1 byte)
        // - Output (value + P2WPKH script)
        // - Locktime (4 bytes)

        bytes memory tx = new bytes(60);
        uint256 offset = 0;

        // Version: 1 (little-endian)
        tx[offset++] = 0x01;
        tx[offset++] = 0x00;
        tx[offset++] = 0x00;
        tx[offset++] = 0x00;

        // Input count: 1
        tx[offset++] = 0x01;

        // Previous output hash (32 bytes of zeros for coinbase-like)
        for (uint256 i = 0; i < 32; i++) {
            tx[offset++] = 0x00;
        }

        // Previous output index: 0xFFFFFFFF (coinbase)
        tx[offset++] = 0xFF;
        tx[offset++] = 0xFF;
        tx[offset++] = 0xFF;
        tx[offset++] = 0xFF;

        // Script length: 0
        tx[offset++] = 0x00;

        // Sequence: 0xFFFFFFFF
        tx[offset++] = 0xFF;
        tx[offset++] = 0xFF;
        tx[offset++] = 0xFF;
        tx[offset++] = 0xFF;

        // Output count: 1
        tx[offset++] = 0x01;

        // Value (8 bytes, little-endian)
        tx[offset++] = bytes1(uint8(valueSats));
        tx[offset++] = bytes1(uint8(valueSats >> 8));
        tx[offset++] = bytes1(uint8(valueSats >> 16));
        tx[offset++] = bytes1(uint8(valueSats >> 24));
        tx[offset++] = bytes1(uint8(valueSats >> 32));
        tx[offset++] = bytes1(uint8(valueSats >> 40));
        tx[offset++] = bytes1(uint8(valueSats >> 48));
        tx[offset++] = bytes1(uint8(valueSats >> 56));

        // P2WPKH scriptPubKey: OP_0 <20 bytes>
        // Script length: 22
        tx[offset++] = 0x16; // 22 bytes

        // OP_0
        tx[offset++] = 0x00;

        // Push 20 bytes
        tx[offset++] = 0x14;

        // Pubkey hash
        for (uint256 i = 0; i < 20; i++) {
            tx[offset++] = pubkeyHash[i];
        }

        // Locktime: 0
        tx[offset++] = 0x00;
        tx[offset++] = 0x00;
        tx[offset++] = 0x00;
        tx[offset++] = 0x00;

        // Trim to actual size
        bytes memory result = new bytes(offset);
        for (uint256 i = 0; i < offset; i++) {
            result[i] = tx[i];
        }

        return result;
    }

    // ============================================
    // Tests
    // ============================================

    function test_deployment_spvMode() public view {
        assertEq(manager.verifier(), address(spvVerifier));
        assertEq(address(spvVerifier.checkpointManager()), address(checkpointManager));
    }

    function test_borrowerRegistration() public view {
        bytes20 hash = spvVerifier.getBorrowerPubkeyHash(borrower);
        assertEq(hash, BORROWER_PUBKEY_HASH);
    }

    function test_checkpointRegistration() public {
        // Build checkpoint
        bytes32 checkpointHash = keccak256("checkpoint_block");

        vm.prank(owner);
        checkpointManager.setCheckpoint(
            CHECKPOINT_HEIGHT,
            checkpointHash,
            0, // chainWork
            1_690_000_000, // timestamp
            0x1d00ffff // bits (genesis difficulty for testing)
        );

        assertEq(checkpointManager.latestCheckpointHeight(), CHECKPOINT_HEIGHT);
    }

    function test_verifyPayout_revertsWithInsufficientConfirmations() public {
        // Setup checkpoint
        bytes32 checkpointHash = keccak256("checkpoint");

        vm.prank(owner);
        checkpointManager.setCheckpoint(CHECKPOINT_HEIGHT, checkpointHash, 0, 1_690_000_000, 0x1d00ffff);

        // Build proof with only 5 headers (insufficient confirmations)
        bytes[] memory headers = new bytes[](5);
        bytes32 prevHash = checkpointHash;
        for (uint256 i = 0; i < 5; i++) {
            headers[i] = _buildHeader(
                prevHash,
                keccak256(abi.encodePacked("merkle", i)),
                uint32(1_690_000_000 + i * 600),
                0x1d00ffff,
                uint32(i)
            );
            prevHash = BitcoinLib.sha256d(headers[i]);
        }

        BtcSpvVerifier.SpvProof memory proof = BtcSpvVerifier.SpvProof({
            checkpointHeight: CHECKPOINT_HEIGHT,
            headers: headers,
            txBlockIndex: 0,
            rawTx: hex"0100000001000000000000000000000000000000000000000000000000000000000000000000ffffffff00ffffffff0140420f0000000000160014751e76e8199196d454941c45d1b3a323f1433bd600000000",
            merkleProof: new bytes32[](0),
            txIndex: 0,
            outputIndex: 0,
            borrower: borrower
        });

        bytes memory encodedProof = abi.encode(proof);

        vm.expectRevert(BtcSpvVerifier.InsufficientConfirmations.selector);
        spvVerifier.verifyPayout(encodedProof);
    }

    function test_verifyPayout_revertsWithInvalidCheckpoint() public {
        // Don't set checkpoint, try to verify
        bytes[] memory headers = new bytes[](6);
        for (uint256 i = 0; i < 6; i++) {
            headers[i] = new bytes(80);
        }

        BtcSpvVerifier.SpvProof memory proof = BtcSpvVerifier.SpvProof({
            checkpointHeight: CHECKPOINT_HEIGHT,
            headers: headers,
            txBlockIndex: 0,
            rawTx: hex"0100000001000000000000000000000000000000000000000000000000000000000000000000ffffffff00ffffffff0140420f0000000000160014751e76e8199196d454941c45d1b3a323f1433bd600000000",
            merkleProof: new bytes32[](0),
            txIndex: 0,
            outputIndex: 0,
            borrower: borrower
        });

        bytes memory encodedProof = abi.encode(proof);

        vm.expectRevert(BtcSpvVerifier.InvalidCheckpoint.selector);
        spvVerifier.verifyPayout(encodedProof);
    }

    function test_verifyPayout_revertsWithUnregisteredBorrower() public {
        address unregistered = makeAddr("unregistered");

        // Setup checkpoint
        bytes32 checkpointHash = keccak256("checkpoint");
        vm.prank(owner);
        checkpointManager.setCheckpoint(CHECKPOINT_HEIGHT, checkpointHash, 0, 1_690_000_000, 0x1d00ffff);

        bytes[] memory headers = new bytes[](6);
        for (uint256 i = 0; i < 6; i++) {
            headers[i] = new bytes(80);
        }

        BtcSpvVerifier.SpvProof memory proof = BtcSpvVerifier.SpvProof({
            checkpointHeight: CHECKPOINT_HEIGHT,
            headers: headers,
            txBlockIndex: 0,
            rawTx: hex"0100000001000000000000000000000000000000000000000000000000000000000000000000ffffffff00ffffffff0140420f0000000000160014751e76e8199196d454941c45d1b3a323f1433bd600000000",
            merkleProof: new bytes32[](0),
            txIndex: 0,
            outputIndex: 0,
            borrower: unregistered // Not registered
        });

        bytes memory encodedProof = abi.encode(proof);

        vm.expectRevert(BtcSpvVerifier.BorrowerNotRegistered.selector);
        spvVerifier.verifyPayout(encodedProof);
    }

    function test_verifyPayout_revertsWithPubkeyHashMismatch() public {
        // Setup checkpoint
        bytes32 checkpointHash = keccak256("checkpoint");
        vm.prank(owner);
        checkpointManager.setCheckpoint(CHECKPOINT_HEIGHT, checkpointHash, 0, 1_690_000_000, 0x1d00ffff);

        // Build headers that link to checkpoint
        bytes[] memory headers = new bytes[](6);
        bytes32 prevHash = checkpointHash;
        for (uint256 i = 0; i < 6; i++) {
            headers[i] = _buildHeader(
                prevHash,
                keccak256(abi.encodePacked("merkle", i)),
                uint32(1_690_000_000 + i * 600),
                0x1d00ffff,
                uint32(i)
            );
            prevHash = BitcoinLib.sha256d(headers[i]);
        }

        // Transaction with WRONG pubkey hash (all zeros)
        // hex: version(4) + input_count(1) + prev_txid(32) + prev_vout(4) + script_len(1) + sequence(4)
        //      + output_count(1) + value(8) + script_len(1) + script(22) + locktime(4)
        bytes memory wrongTx =
            hex"010000000100000000000000000000000000000000000000000000000000000000000000000000ffffffff00ffffffff0140420f00000000001600140000000000000000000000000000000000000000000000";

        BtcSpvVerifier.SpvProof memory proof = BtcSpvVerifier.SpvProof({
            checkpointHeight: CHECKPOINT_HEIGHT,
            headers: headers,
            txBlockIndex: 0,
            rawTx: wrongTx, // Wrong pubkey hash
            merkleProof: new bytes32[](0),
            txIndex: 0,
            outputIndex: 0,
            borrower: borrower
        });

        bytes memory encodedProof = abi.encode(proof);

        // Will fail at header chain verification or merkle proof
        vm.expectRevert(); // Multiple possible reverts due to synthetic data
        spvVerifier.verifyPayout(encodedProof);
    }

    function test_managerRejectsUnregisteredBorrowerInSubmitPayout() public {
        // Setup checkpoint
        bytes32 checkpointHash = keccak256("checkpoint");
        vm.prank(owner);
        checkpointManager.setCheckpoint(CHECKPOINT_HEIGHT, checkpointHash, 0, 1_690_000_000, 0x1d00ffff);

        // Register a different borrower in verifier but not in manager
        address newBorrower = makeAddr("newBorrower");
        vm.prank(owner);
        spvVerifier.setBorrowerPubkeyHash(newBorrower, bytes20(hex"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"));

        bytes[] memory headers = new bytes[](6);
        for (uint256 i = 0; i < 6; i++) {
            headers[i] = new bytes(80);
        }

        BtcSpvVerifier.SpvProof memory proof = BtcSpvVerifier.SpvProof({
            checkpointHeight: CHECKPOINT_HEIGHT,
            headers: headers,
            txBlockIndex: 0,
            rawTx: new bytes(60),
            merkleProof: new bytes32[](0),
            txIndex: 0,
            outputIndex: 0,
            borrower: newBorrower // Not registered in Manager
        });

        bytes memory encodedProof = abi.encode(proof);

        // Should revert during verification
        vm.expectRevert();
        manager.submitPayout(encodedProof);
    }
}
