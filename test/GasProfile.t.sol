// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test, console2} from "forge-std/Test.sol";
import {BtcSpvVerifier} from "../contracts/BtcSpvVerifier.sol";
import {CheckpointManager} from "../contracts/CheckpointManager.sol";
import {BitcoinLib} from "../contracts/lib/BitcoinLib.sol";
import {HashCreditManager} from "../contracts/HashCreditManager.sol";
import {LendingVault} from "../contracts/LendingVault.sol";
import {RiskConfig} from "../contracts/RiskConfig.sol";
import {PoolRegistry} from "../contracts/PoolRegistry.sol";
import {RelayerSigVerifier} from "../contracts/RelayerSigVerifier.sol";
import {MockERC20} from "../contracts/mocks/MockERC20.sol";
import {IVerifierAdapter, PayoutEvidence} from "../contracts/interfaces/IVerifierAdapter.sol";
import {IRiskConfig} from "../contracts/interfaces/IRiskConfig.sol";

/**
 * @title GasProfileTest
 * @notice Gas profiling tests for HashCredit protocol
 * @dev These tests measure gas consumption for various operations at different scales
 *
 * Key limits enforced by the protocol:
 * - MAX_HEADER_CHAIN: 144 blocks (~1 day of Bitcoin blocks)
 * - MAX_MERKLE_DEPTH: 20 levels (supports up to 2^20 = ~1M transactions per block)
 * - MAX_TX_SIZE: 4096 bytes
 * - MIN_CONFIRMATIONS: 6 blocks
 */
contract GasProfileTest is Test {
    // ============ Test Contracts ============

    BtcSpvVerifier public spvVerifier;
    CheckpointManager public checkpointManager;
    RelayerSigVerifier public relayerVerifier;
    HashCreditManager public manager;
    LendingVault public vault;
    RiskConfig public riskConfig;
    PoolRegistry public poolRegistry;
    MockERC20 public stablecoin;

    address public owner;
    address public borrower;
    address public lp;
    uint256 public relayerPrivateKey;
    address public relayerSigner;

    // ============ Constants ============

    bytes32 constant CHECKPOINT_HASH = 0x00000000000000000002a7c4c1e48d76c5a37902165a270156b7a8d72728a054;
    uint32 constant CHECKPOINT_HEIGHT = 800000;
    uint32 constant CHECKPOINT_TIMESTAMP = 1690000000;
    uint32 constant CHECKPOINT_BITS = 0x17053894; // Block 800000 difficulty
    bytes20 constant BORROWER_PUBKEY_HASH = bytes20(hex"1234567890abcdef1234567890abcdef12345678");

    function setUp() public {
        owner = makeAddr("owner");
        borrower = makeAddr("borrower");
        lp = makeAddr("lp");
        relayerPrivateKey = 0xA11CE;
        relayerSigner = vm.addr(relayerPrivateKey);

        vm.startPrank(owner);

        // Deploy infrastructure
        stablecoin = new MockERC20("USD Coin", "USDC", 6);
        checkpointManager = new CheckpointManager(owner);

        // Deploy RiskConfig with default params
        IRiskConfig.RiskParams memory riskParams = IRiskConfig.RiskParams({
            confirmationsRequired: 6,
            advanceRateBps: 5000, // 50%
            windowSeconds: 30 days,
            newBorrowerCap: 10000e6, // $10,000
            globalCap: 1000000e6, // $1,000,000
            minPayoutSats: 100000, // 0.001 BTC
            btcPriceUsd: 50000_00000000, // $50,000
            minPayoutCountForFullCredit: 3,
            largePayoutThresholdSats: 100_00000000, // 100 BTC
            largePayoutDiscountBps: 5000, // 50%
            newBorrowerPeriodSeconds: 30 days
        });
        riskConfig = new RiskConfig(riskParams);

        poolRegistry = new PoolRegistry(true); // Permissive mode

        // Deploy verifiers
        spvVerifier = new BtcSpvVerifier(owner, address(checkpointManager));
        relayerVerifier = new RelayerSigVerifier(relayerSigner);

        // Deploy core
        vault = new LendingVault(address(stablecoin), 1000); // 10% APR
        manager = new HashCreditManager(
            address(relayerVerifier),
            address(vault),
            address(riskConfig),
            address(poolRegistry),
            address(stablecoin)
        );

        // Configure
        vault.setManager(address(manager));
        checkpointManager.setCheckpoint(CHECKPOINT_HEIGHT, CHECKPOINT_HASH, 0, CHECKPOINT_TIMESTAMP, CHECKPOINT_BITS);
        spvVerifier.setBorrowerPubkeyHash(borrower, BORROWER_PUBKEY_HASH);
        manager.registerBorrower(borrower, bytes32(BORROWER_PUBKEY_HASH));

        vm.stopPrank();

        // Fund LP and deposit
        stablecoin.mint(lp, 1_000_000e6);
        vm.startPrank(lp);
        stablecoin.approve(address(vault), type(uint256).max);
        vault.deposit(1_000_000e6);
        vm.stopPrank();
    }

    // ============ Header Chain Verification Gas Tests ============

    /**
     * @notice Measure gas for header parsing at various chain lengths
     * @dev These are isolated tests for BitcoinLib operations
     */
    function test_gas_parseHeader_single() public view {
        bytes memory header = _createMockHeader();
        uint256 gasBefore = gasleft();
        BitcoinLib.parseHeader(header);
        uint256 gasUsed = gasBefore - gasleft();
        console2.log("parseHeader (single header): %d gas", gasUsed);
    }

    function test_gas_sha256d() public view {
        bytes memory data = new bytes(80);
        uint256 gasBefore = gasleft();
        BitcoinLib.sha256d(data);
        uint256 gasUsed = gasBefore - gasleft();
        console2.log("sha256d (80 bytes): %d gas", gasUsed);
    }

    function test_gas_bitsToTarget() public view {
        uint256 gasBefore = gasleft();
        BitcoinLib.bitsToTarget(0x1d00ffff);
        uint256 gasUsed = gasBefore - gasleft();
        console2.log("bitsToTarget: %d gas", gasUsed);
    }

    // ============ Merkle Proof Verification Gas Tests ============

    function test_gas_merkleProof_depth1() public {
        _measureMerkleProofGas(1);
    }

    function test_gas_merkleProof_depth5() public {
        _measureMerkleProofGas(5);
    }

    function test_gas_merkleProof_depth10() public {
        _measureMerkleProofGas(10);
    }

    function test_gas_merkleProof_depth15() public {
        _measureMerkleProofGas(15);
    }

    function test_gas_merkleProof_depth20_max() public {
        _measureMerkleProofGas(20);
    }

    function _measureMerkleProofGas(uint256 depth) internal {
        // Build a valid merkle proof
        bytes32 txid = keccak256("test transaction");
        bytes32[] memory proof = new bytes32[](depth);
        bytes32 current = txid;

        // Build proof from leaf to root
        for (uint256 i = 0; i < depth; i++) {
            proof[i] = keccak256(abi.encodePacked("sibling", i));
            current = BitcoinLib.sha256d(abi.encodePacked(current, proof[i]));
        }
        bytes32 merkleRoot = current;

        uint256 gasBefore = gasleft();
        bool valid = BitcoinLib.verifyMerkleProof(txid, merkleRoot, proof, 0);
        uint256 gasUsed = gasBefore - gasleft();

        assertTrue(valid, "Merkle proof should be valid");
        console2.log("verifyMerkleProof depth %d: %d gas", depth, gasUsed);
    }

    // ============ Transaction Parsing Gas Tests ============

    function test_gas_parseTxOutput_minimal() public {
        // Valid P2WPKH transaction with proper structure
        // version (4) + input_count (1) + coinbase input (41) + output_count (1) + output (31) + locktime (4)
        bytes memory rawTx = _createValidMinimalTx();
        uint256 gasBefore = gasleft();
        BitcoinLib.parseTxOutput(rawTx, 0);
        uint256 gasUsed = gasBefore - gasleft();
        console2.log("parseTxOutput (minimal tx): %d gas", gasUsed);
    }

    function test_gas_parseTxOutput_multiOutput() public {
        // Transaction with multiple outputs
        bytes memory rawTx = _createMultiOutputTx();
        uint256 gasBefore = gasleft();
        BitcoinLib.parseTxOutput(rawTx, 1); // Get second output
        uint256 gasUsed = gasBefore - gasleft();
        console2.log("parseTxOutput (multi-output, idx=1): %d gas", gasUsed);
    }

    function test_gas_extractPubkeyHash_P2WPKH() public view {
        bytes memory script = hex"00141234567890abcdef1234567890abcdef12345678";
        uint256 gasBefore = gasleft();
        BitcoinLib.extractPubkeyHash(script);
        uint256 gasUsed = gasBefore - gasleft();
        console2.log("extractPubkeyHash (P2WPKH): %d gas", gasUsed);
    }

    function test_gas_extractPubkeyHash_P2PKH() public view {
        bytes memory script = hex"76a9141234567890abcdef1234567890abcdef1234567888ac";
        uint256 gasBefore = gasleft();
        BitcoinLib.extractPubkeyHash(script);
        uint256 gasUsed = gasBefore - gasleft();
        console2.log("extractPubkeyHash (P2PKH): %d gas", gasUsed);
    }

    // ============ RelayerSigVerifier Gas Tests ============

    function test_gas_relayerVerifier_verifyPayout() public {
        // Prepare signed payload
        bytes32 txid = keccak256("test_tx");
        uint32 vout = 0;
        uint64 amountSats = 100000000; // 1 BTC
        uint32 blockHeight = 800010;
        uint32 blockTimestamp = 1690001000;
        uint64 deadline = uint64(block.timestamp + 1 hours);

        bytes32 digest = relayerVerifier.getPayoutClaimDigest(
            borrower, txid, vout, amountSats, blockHeight, blockTimestamp, deadline
        );
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(relayerPrivateKey, digest);
        bytes memory signature = abi.encodePacked(r, s, v);

        bytes memory payload = abi.encode(
            borrower, txid, vout, amountSats, blockHeight, blockTimestamp, deadline, signature
        );

        uint256 gasBefore = gasleft();
        relayerVerifier.verifyPayout(payload);
        uint256 gasUsed = gasBefore - gasleft();
        console2.log("RelayerSigVerifier.verifyPayout: %d gas", gasUsed);
    }

    // ============ HashCreditManager Gas Tests ============

    function test_gas_registerBorrower() public {
        address newBorrower = makeAddr("newBorrower");
        bytes32 pubkeyHash = keccak256("newPubkey");

        vm.prank(owner);
        uint256 gasBefore = gasleft();
        manager.registerBorrower(newBorrower, pubkeyHash);
        uint256 gasUsed = gasBefore - gasleft();
        console2.log("registerBorrower: %d gas", gasUsed);
    }

    function test_gas_submitPayout() public {
        bytes32 txid = keccak256("payout_tx");
        uint32 vout = 0;
        uint64 amountSats = 100000000;
        uint32 blockHeight = 800010;
        uint32 blockTimestamp = 1690001000;
        uint64 deadline = uint64(block.timestamp + 1 hours);

        bytes32 digest = relayerVerifier.getPayoutClaimDigest(
            borrower, txid, vout, amountSats, blockHeight, blockTimestamp, deadline
        );
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(relayerPrivateKey, digest);
        bytes memory signature = abi.encodePacked(r, s, v);

        bytes memory payload = abi.encode(
            borrower, txid, vout, amountSats, blockHeight, blockTimestamp, deadline, signature
        );

        uint256 gasBefore = gasleft();
        manager.submitPayout(payload);
        uint256 gasUsed = gasBefore - gasleft();
        console2.log("submitPayout: %d gas", gasUsed);
    }

    function test_gas_borrow() public {
        // First submit payout to get credit
        _submitPayoutForBorrower(borrower, 100000000);

        uint256 creditLimit = manager.getBorrowerInfo(borrower).creditLimit;
        uint256 borrowAmount = creditLimit / 2;

        vm.prank(borrower);
        uint256 gasBefore = gasleft();
        manager.borrow(borrowAmount);
        uint256 gasUsed = gasBefore - gasleft();
        console2.log("borrow: %d gas", gasUsed);
    }

    function test_gas_repay() public {
        // Setup: submit payout and borrow
        _submitPayoutForBorrower(borrower, 100000000);
        uint256 creditLimit = manager.getBorrowerInfo(borrower).creditLimit;
        uint256 borrowAmount = creditLimit / 2;

        vm.prank(borrower);
        manager.borrow(borrowAmount);

        // Get stablecoins for repay
        stablecoin.mint(borrower, borrowAmount);
        vm.startPrank(borrower);
        stablecoin.approve(address(manager), borrowAmount);

        uint256 gasBefore = gasleft();
        manager.repay(borrowAmount / 2);
        uint256 gasUsed = gasBefore - gasleft();
        vm.stopPrank();

        console2.log("repay: %d gas", gasUsed);
    }

    // ============ LendingVault Gas Tests ============

    function test_gas_vault_deposit() public {
        address depositor = makeAddr("depositor");
        stablecoin.mint(depositor, 100000e6);

        vm.startPrank(depositor);
        stablecoin.approve(address(vault), 100000e6);

        uint256 gasBefore = gasleft();
        vault.deposit(100000e6);
        uint256 gasUsed = gasBefore - gasleft();
        vm.stopPrank();

        console2.log("vault.deposit: %d gas", gasUsed);
    }

    function test_gas_vault_withdraw() public {
        address depositor = makeAddr("depositor");
        stablecoin.mint(depositor, 100000e6);

        vm.startPrank(depositor);
        stablecoin.approve(address(vault), 100000e6);
        vault.deposit(100000e6);

        uint256 shares = vault.sharesOf(depositor);
        uint256 gasBefore = gasleft();
        vault.withdraw(shares / 2);
        uint256 gasUsed = gasBefore - gasleft();
        vm.stopPrank();

        console2.log("vault.withdraw: %d gas", gasUsed);
    }

    // ============ CheckpointManager Gas Tests ============

    function test_gas_setCheckpoint() public {
        vm.prank(owner);
        uint256 gasBefore = gasleft();
        checkpointManager.setCheckpoint(
            CHECKPOINT_HEIGHT + 2016,
            keccak256("new_block"),
            1000000,
            CHECKPOINT_TIMESTAMP + 2016 * 600,
            CHECKPOINT_BITS
        );
        uint256 gasUsed = gasBefore - gasleft();
        console2.log("setCheckpoint: %d gas", gasUsed);
    }

    function test_gas_getCheckpoint() public view {
        uint256 gasBefore = gasleft();
        checkpointManager.getCheckpoint(CHECKPOINT_HEIGHT);
        uint256 gasUsed = gasBefore - gasleft();
        console2.log("getCheckpoint: %d gas", gasUsed);
    }

    // ============ Batch Operations Gas Tests ============

    function test_gas_multiplePayouts_5() public {
        _measureMultiplePayouts(5);
    }

    function test_gas_multiplePayouts_10() public {
        _measureMultiplePayouts(10);
    }

    function _measureMultiplePayouts(uint256 count) internal {
        uint256 totalGas = 0;

        for (uint256 i = 0; i < count; i++) {
            bytes32 txid = keccak256(abi.encodePacked("batch_tx_", i));
            uint32 vout = 0;
            uint64 amountSats = 10000000; // 0.1 BTC
            uint32 blockHeight = 800010 + uint32(i);
            uint32 blockTimestamp = 1690001000 + uint32(i * 600);
            uint64 deadline = uint64(block.timestamp + 1 hours);

            bytes32 digest = relayerVerifier.getPayoutClaimDigest(
                borrower, txid, vout, amountSats, blockHeight, blockTimestamp, deadline
            );
            (uint8 v, bytes32 r, bytes32 s) = vm.sign(relayerPrivateKey, digest);
            bytes memory signature = abi.encodePacked(r, s, v);

            bytes memory payload = abi.encode(
                borrower, txid, vout, amountSats, blockHeight, blockTimestamp, deadline, signature
            );

            uint256 gasBefore = gasleft();
            manager.submitPayout(payload);
            totalGas += gasBefore - gasleft();
        }

        console2.log("submitPayout x%d total: %d gas", count, totalGas);
        console2.log("submitPayout x%d avg: %d gas", count, totalGas / count);
    }

    // ============ Helper Functions ============

    function _createMockHeader() internal pure returns (bytes memory) {
        bytes memory header = new bytes(80);
        // Version: 1
        header[0] = 0x01;
        // Rest is zeros (prevBlockHash, merkleRoot, timestamp, bits, nonce)
        return header;
    }

    function _createValidMinimalTx() internal pure returns (bytes memory) {
        // Non-segwit transaction structure:
        // version (4 bytes) + input_count (1) + inputs + output_count (1) + outputs + locktime (4)
        // Coinbase-like input: prev_txid (32 zeros) + prev_vout (0xffffffff) + script_len (1) + script + sequence
        bytes memory rawTx = new bytes(82);

        // Version: 2 (little-endian)
        rawTx[0] = 0x02;
        rawTx[1] = 0x00;
        rawTx[2] = 0x00;
        rawTx[3] = 0x00;

        // Input count: 1
        rawTx[4] = 0x01;

        // Previous txid: 32 zeros (already initialized)
        // Offset 5-36

        // Previous vout: 0xffffffff (coinbase)
        rawTx[37] = 0xff;
        rawTx[38] = 0xff;
        rawTx[39] = 0xff;
        rawTx[40] = 0xff;

        // Script length: 1
        rawTx[41] = 0x01;

        // Script: 0x00
        rawTx[42] = 0x00;

        // Sequence: 0xffffffff
        rawTx[43] = 0xff;
        rawTx[44] = 0xff;
        rawTx[45] = 0xff;
        rawTx[46] = 0xff;

        // Output count: 1
        rawTx[47] = 0x01;

        // Output value: 1 BTC (100000000 sats) little-endian
        rawTx[48] = 0x00;
        rawTx[49] = 0xe1;
        rawTx[50] = 0xf5;
        rawTx[51] = 0x05;
        rawTx[52] = 0x00;
        rawTx[53] = 0x00;
        rawTx[54] = 0x00;
        rawTx[55] = 0x00;

        // Script length: 22 (P2WPKH)
        rawTx[56] = 0x16;

        // P2WPKH script: 0x0014 + 20 bytes pubkey hash
        rawTx[57] = 0x00;
        rawTx[58] = 0x14;
        // pubkey hash (20 bytes): 0x12, 0x34, ... (already initialized to zeros, set some values)
        rawTx[59] = 0x12;
        rawTx[60] = 0x34;
        rawTx[61] = 0x56;
        rawTx[62] = 0x78;
        rawTx[63] = 0x90;
        rawTx[64] = 0xab;
        rawTx[65] = 0xcd;
        rawTx[66] = 0xef;
        rawTx[67] = 0x12;
        rawTx[68] = 0x34;
        rawTx[69] = 0x56;
        rawTx[70] = 0x78;
        rawTx[71] = 0x90;
        rawTx[72] = 0xab;
        rawTx[73] = 0xcd;
        rawTx[74] = 0xef;
        rawTx[75] = 0x12;
        rawTx[76] = 0x34;
        rawTx[77] = 0x56;
        rawTx[78] = 0x78;

        // Locktime: 0 (4 bytes, already initialized)
        // Offset 79-82

        return rawTx;
    }

    function _createMultiOutputTx() internal pure returns (bytes memory) {
        // Transaction with 2 outputs
        bytes memory rawTx = new bytes(113);

        // Version: 2
        rawTx[0] = 0x02;

        // Input count: 1
        rawTx[4] = 0x01;

        // Previous txid: 32 zeros (offset 5-36)

        // Previous vout: 0xffffffff
        rawTx[37] = 0xff;
        rawTx[38] = 0xff;
        rawTx[39] = 0xff;
        rawTx[40] = 0xff;

        // Script length: 1
        rawTx[41] = 0x01;
        rawTx[42] = 0x00;

        // Sequence: 0xffffffff
        rawTx[43] = 0xff;
        rawTx[44] = 0xff;
        rawTx[45] = 0xff;
        rawTx[46] = 0xff;

        // Output count: 2
        rawTx[47] = 0x02;

        // Output 0: 0.5 BTC
        rawTx[48] = 0x80;
        rawTx[49] = 0xf0;
        rawTx[50] = 0xfa;
        rawTx[51] = 0x02;
        // Script length: 22 (P2WPKH)
        rawTx[56] = 0x16;
        rawTx[57] = 0x00;
        rawTx[58] = 0x14;
        rawTx[59] = 0xaa;

        // Output 1: 0.5 BTC (offset 79)
        rawTx[79] = 0x80;
        rawTx[80] = 0xf0;
        rawTx[81] = 0xfa;
        rawTx[82] = 0x02;
        // Script length: 22 (P2WPKH)
        rawTx[87] = 0x16;
        rawTx[88] = 0x00;
        rawTx[89] = 0x14;
        rawTx[90] = 0xbb;

        // Locktime at end

        return rawTx;
    }

    function _submitPayoutForBorrower(address _borrower, uint64 amountSats) internal {
        bytes32 txid = keccak256(abi.encodePacked("payout_", _borrower, block.timestamp));
        uint32 vout = 0;
        uint32 blockHeight = 800010;
        uint32 blockTimestamp = 1690001000;
        uint64 deadline = uint64(block.timestamp + 1 hours);

        bytes32 digest = relayerVerifier.getPayoutClaimDigest(
            _borrower, txid, vout, amountSats, blockHeight, blockTimestamp, deadline
        );
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(relayerPrivateKey, digest);
        bytes memory signature = abi.encodePacked(r, s, v);

        bytes memory payload = abi.encode(
            _borrower, txid, vout, amountSats, blockHeight, blockTimestamp, deadline, signature
        );

        manager.submitPayout(payload);
    }
}
