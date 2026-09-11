// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test, console2} from "forge-std/Test.sol";
import {CheckpointManager} from "../contracts/CheckpointManager.sol";
import {ICheckpointManager} from "../contracts/interfaces/ICheckpointManager.sol";

contract CheckpointManagerTest is Test {
    CheckpointManager public manager;
    address public owner;
    address public attacker;

    // Sample Bitcoin block data (mainnet block 800000)
    bytes32 constant BLOCK_HASH_800000 = 0x00000000000000000002a7c4c1e48d76c5a37902165a270156b7a8d72728a054;
    uint32 constant BLOCK_HEIGHT_800000 = 800000;
    uint256 constant CHAIN_WORK_800000 = 0x000000000000000000000000000000000000000053c6f31f13e6e3f1b5a0bfff;
    uint32 constant TIMESTAMP_800000 = 1690000000;
    uint32 constant BITS_800000 = 0x17053894; // Block 800000 difficulty

    // Another sample block (800100)
    bytes32 constant BLOCK_HASH_800100 = 0x00000000000000000001a2b3c4d5e6f7890abcdef1234567890abcdef1234567;
    uint32 constant BLOCK_HEIGHT_800100 = 800100;
    uint256 constant CHAIN_WORK_800100 = 0x000000000000000000000000000000000000000053c7f31f13e6e3f1b5a0bfff;
    uint32 constant TIMESTAMP_800100 = 1690060000;
    uint32 constant BITS_800100 = 0x17053894; // Same epoch, same bits

    function setUp() public {
        owner = makeAddr("owner");
        attacker = makeAddr("attacker");

        vm.prank(owner);
        manager = new CheckpointManager(owner);
    }

    // ============ setCheckpoint Tests ============

    function test_setCheckpoint_success() public {
        vm.prank(owner);
        manager.setCheckpoint(
            BLOCK_HEIGHT_800000,
            BLOCK_HASH_800000,
            CHAIN_WORK_800000,
            TIMESTAMP_800000,
            BITS_800000
        );

        ICheckpointManager.Checkpoint memory cp = manager.getCheckpoint(BLOCK_HEIGHT_800000);
        assertEq(cp.height, BLOCK_HEIGHT_800000);
        assertEq(cp.blockHash, BLOCK_HASH_800000);
        assertEq(cp.chainWork, CHAIN_WORK_800000);
        assertEq(cp.timestamp, TIMESTAMP_800000);
        assertEq(cp.bits, BITS_800000);
    }

    function test_setCheckpoint_emitsEvent() public {
        vm.expectEmit(true, true, false, true);
        emit ICheckpointManager.CheckpointSet(
            BLOCK_HEIGHT_800000,
            BLOCK_HASH_800000,
            CHAIN_WORK_800000,
            TIMESTAMP_800000,
            BITS_800000
        );

        vm.prank(owner);
        manager.setCheckpoint(
            BLOCK_HEIGHT_800000,
            BLOCK_HASH_800000,
            CHAIN_WORK_800000,
            TIMESTAMP_800000,
            BITS_800000
        );
    }

    function test_setCheckpoint_revertsIfNotOwner() public {
        vm.prank(attacker);
        vm.expectRevert(CheckpointManager.Unauthorized.selector);
        manager.setCheckpoint(
            BLOCK_HEIGHT_800000,
            BLOCK_HASH_800000,
            CHAIN_WORK_800000,
            TIMESTAMP_800000,
            BITS_800000
        );
    }

    function test_setCheckpoint_revertsIfHeightNotIncreasing() public {
        // Set first checkpoint
        vm.prank(owner);
        manager.setCheckpoint(
            BLOCK_HEIGHT_800000,
            BLOCK_HASH_800000,
            CHAIN_WORK_800000,
            TIMESTAMP_800000,
            BITS_800000
        );

        // Try to set checkpoint with same height
        vm.prank(owner);
        vm.expectRevert(
            abi.encodeWithSelector(
                CheckpointManager.HeightMustIncrease.selector,
                BLOCK_HEIGHT_800000,
                BLOCK_HEIGHT_800000
            )
        );
        manager.setCheckpoint(
            BLOCK_HEIGHT_800000,
            BLOCK_HASH_800100, // different hash
            CHAIN_WORK_800100,
            TIMESTAMP_800100,
            BITS_800100
        );
    }

    function test_setCheckpoint_revertsIfHeightDecreasing() public {
        // Set first checkpoint at height 800100
        vm.prank(owner);
        manager.setCheckpoint(
            BLOCK_HEIGHT_800100,
            BLOCK_HASH_800100,
            CHAIN_WORK_800100,
            TIMESTAMP_800100,
            BITS_800100
        );

        // Try to set checkpoint with lower height
        vm.prank(owner);
        vm.expectRevert(
            abi.encodeWithSelector(
                CheckpointManager.HeightMustIncrease.selector,
                BLOCK_HEIGHT_800000,
                BLOCK_HEIGHT_800100
            )
        );
        manager.setCheckpoint(
            BLOCK_HEIGHT_800000,
            BLOCK_HASH_800000,
            CHAIN_WORK_800000,
            TIMESTAMP_800000,
            BITS_800000
        );
    }

    function test_setCheckpoint_revertsIfZeroBlockHash() public {
        vm.prank(owner);
        vm.expectRevert(CheckpointManager.InvalidBlockHash.selector);
        manager.setCheckpoint(
            BLOCK_HEIGHT_800000,
            bytes32(0),
            CHAIN_WORK_800000,
            TIMESTAMP_800000,
            BITS_800000
        );
    }

    function test_setCheckpoint_revertsIfZeroTimestamp() public {
        vm.prank(owner);
        vm.expectRevert(CheckpointManager.InvalidTimestamp.selector);
        manager.setCheckpoint(
            BLOCK_HEIGHT_800000,
            BLOCK_HASH_800000,
            CHAIN_WORK_800000,
            0,
            BITS_800000
        );
    }

    function test_setCheckpoint_revertsIfZeroBits() public {
        vm.prank(owner);
        vm.expectRevert(CheckpointManager.InvalidBits.selector);
        manager.setCheckpoint(
            BLOCK_HEIGHT_800000,
            BLOCK_HASH_800000,
            CHAIN_WORK_800000,
            TIMESTAMP_800000,
            0
        );
    }

    // ============ getCheckpoint Tests ============

    function test_getCheckpoint_returnsZeroForNonExistent() public view {
        ICheckpointManager.Checkpoint memory cp = manager.getCheckpoint(999999);
        assertEq(cp.height, 0);
        assertEq(cp.blockHash, bytes32(0));
        assertEq(cp.chainWork, 0);
        assertEq(cp.timestamp, 0);
    }

    // ============ isValidCheckpoint Tests ============

    function test_isValidCheckpoint_returnsTrueForValid() public {
        vm.prank(owner);
        manager.setCheckpoint(
            BLOCK_HEIGHT_800000,
            BLOCK_HASH_800000,
            CHAIN_WORK_800000,
            TIMESTAMP_800000,
            BITS_800000
        );

        bool valid = manager.isValidCheckpoint(BLOCK_HEIGHT_800000, BLOCK_HASH_800000);
        assertTrue(valid);
    }

    function test_isValidCheckpoint_returnsFalseForWrongHash() public {
        vm.prank(owner);
        manager.setCheckpoint(
            BLOCK_HEIGHT_800000,
            BLOCK_HASH_800000,
            CHAIN_WORK_800000,
            TIMESTAMP_800000,
            BITS_800000
        );

        bool valid = manager.isValidCheckpoint(BLOCK_HEIGHT_800000, BLOCK_HASH_800100);
        assertFalse(valid);
    }

    function test_isValidCheckpoint_returnsFalseForNonExistent() public view {
        bool valid = manager.isValidCheckpoint(BLOCK_HEIGHT_800000, BLOCK_HASH_800000);
        assertFalse(valid);
    }

    // ============ latestCheckpointHeight Tests ============

    function test_latestCheckpointHeight_returnsZeroInitially() public view {
        assertEq(manager.latestCheckpointHeight(), 0);
    }

    function test_latestCheckpointHeight_updatesAfterSet() public {
        vm.prank(owner);
        manager.setCheckpoint(
            BLOCK_HEIGHT_800000,
            BLOCK_HASH_800000,
            CHAIN_WORK_800000,
            TIMESTAMP_800000,
            BITS_800000
        );

        assertEq(manager.latestCheckpointHeight(), BLOCK_HEIGHT_800000);

        vm.prank(owner);
        manager.setCheckpoint(
            BLOCK_HEIGHT_800100,
            BLOCK_HASH_800100,
            CHAIN_WORK_800100,
            TIMESTAMP_800100,
            BITS_800100
        );

        assertEq(manager.latestCheckpointHeight(), BLOCK_HEIGHT_800100);
    }

    // ============ latestCheckpoint Tests ============

    function test_latestCheckpoint_revertsIfNone() public {
        vm.expectRevert(abi.encodeWithSelector(CheckpointManager.CheckpointNotFound.selector, 0));
        manager.latestCheckpoint();
    }

    function test_latestCheckpoint_returnsLatest() public {
        vm.prank(owner);
        manager.setCheckpoint(
            BLOCK_HEIGHT_800000,
            BLOCK_HASH_800000,
            CHAIN_WORK_800000,
            TIMESTAMP_800000,
            BITS_800000
        );

        vm.prank(owner);
        manager.setCheckpoint(
            BLOCK_HEIGHT_800100,
            BLOCK_HASH_800100,
            CHAIN_WORK_800100,
            TIMESTAMP_800100,
            BITS_800100
        );

        ICheckpointManager.Checkpoint memory cp = manager.latestCheckpoint();
        assertEq(cp.height, BLOCK_HEIGHT_800100);
        assertEq(cp.blockHash, BLOCK_HASH_800100);
    }

    // ============ Multiple Checkpoints Tests ============

    function test_multipleCheckpoints_maintainsAll() public {
        // Set multiple checkpoints
        vm.startPrank(owner);

        manager.setCheckpoint(
            BLOCK_HEIGHT_800000,
            BLOCK_HASH_800000,
            CHAIN_WORK_800000,
            TIMESTAMP_800000,
            BITS_800000
        );

        manager.setCheckpoint(
            BLOCK_HEIGHT_800100,
            BLOCK_HASH_800100,
            CHAIN_WORK_800100,
            TIMESTAMP_800100,
            BITS_800100
        );

        vm.stopPrank();

        // Both checkpoints should be retrievable
        ICheckpointManager.Checkpoint memory cp1 = manager.getCheckpoint(BLOCK_HEIGHT_800000);
        ICheckpointManager.Checkpoint memory cp2 = manager.getCheckpoint(BLOCK_HEIGHT_800100);

        assertEq(cp1.height, BLOCK_HEIGHT_800000);
        assertEq(cp1.blockHash, BLOCK_HASH_800000);

        assertEq(cp2.height, BLOCK_HEIGHT_800100);
        assertEq(cp2.blockHash, BLOCK_HASH_800100);
    }

    // ============ Ownership Tests ============

    function test_transferOwnership_success() public {
        address newOwner = makeAddr("newOwner");

        vm.prank(owner);
        manager.transferOwnership(newOwner);

        assertEq(manager.owner(), newOwner);
    }

    function test_transferOwnership_revertsIfNotOwner() public {
        address newOwner = makeAddr("newOwner");

        vm.prank(attacker);
        vm.expectRevert(CheckpointManager.Unauthorized.selector);
        manager.transferOwnership(newOwner);
    }

    function test_transferOwnership_revertsIfZeroAddress() public {
        vm.prank(owner);
        vm.expectRevert(CheckpointManager.InvalidAddress.selector);
        manager.transferOwnership(address(0));
    }

    // ============ Constructor Tests ============

    function test_constructor_revertsIfZeroOwner() public {
        vm.expectRevert(CheckpointManager.InvalidAddress.selector);
        new CheckpointManager(address(0));
    }

    function test_constructor_setsOwner() public view {
        assertEq(manager.owner(), owner);
    }
}
