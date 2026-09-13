// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import { Test } from "forge-std/Test.sol";
import { DeploySpv } from "../script/DeploySpv.s.sol";
import { HashCreditManager } from "../contracts/HashCreditManager.sol";
import { TestnetMintableERC20 } from "../contracts/TestnetMintableERC20.sol";

/**
 * @title DeploySpvAutoGrantTest
 * @notice GPU-001: the legacy deploy script must never enable demo auto-grant credit with an
 *         external stablecoin or on a non-demo chain. Runs the real script in-process.
 */
contract DeploySpvAutoGrantTest is Test {
    uint256 constant DEPLOYER_KEY = 0xA11CE;
    uint128 constant DEMO_AUTO_GRANT = 1_000_000_000;

    /// @dev `vm.setEnv` is process-global and tests run in parallel, so the stablecoin choice is
    ///      passed explicitly instead of through STABLECOIN_ADDRESS.
    function _runScript(address stablecoinAddr) internal returns (HashCreditManager manager) {
        DeploySpv script = new DeploySpv();
        script.runWith(stablecoinAddr);
        require(script.lastManager() != address(0), "manager not found");
        return HashCreditManager(script.lastManager());
    }

    function setUp() public {
        vm.setEnv("PRIVATE_KEY", vm.toString(DEPLOYER_KEY));
        vm.setEnv("INITIAL_LIQUIDITY", "0");
        vm.deal(vm.addr(DEPLOYER_KEY), 100 ether);
    }

    function test_policyHelpers() public {
        DeploySpv script = new DeploySpv();
        assertTrue(script.isDemoChain(102_031));
        assertTrue(script.isDemoChain(31_337));
        assertFalse(script.isDemoChain(102_030)); // CC3 mainnet
        assertFalse(script.isDemoChain(1));
        assertTrue(script.demoAutoGrantAllowed(true, 31_337));
        assertFalse(script.demoAutoGrantAllowed(false, 31_337)); // external stablecoin
        assertFalse(script.demoAutoGrantAllowed(true, 102_030)); // mainnet
        assertFalse(script.demoAutoGrantAllowed(false, 102_030));
    }

    function test_autoGrant_enabled_onlyFor_scriptTestToken_onDemoChain() public {
        vm.chainId(31_337);
        HashCreditManager manager = _runScript(address(0));
        assertEq(manager.autoGrantCreditAmount(), DEMO_AUTO_GRANT);
    }

    function test_autoGrant_disabled_with_externalStablecoin() public {
        vm.chainId(31_337);
        TestnetMintableERC20 external_ = new TestnetMintableERC20("External", "EXT", 6, address(this));
        HashCreditManager manager = _runScript(address(external_));
        assertEq(manager.autoGrantCreditAmount(), 0);
        assertEq(manager.stablecoin(), address(external_));
    }

    function test_autoGrant_disabled_on_mainnetChain_evenWithTestToken() public {
        vm.chainId(102_030);
        HashCreditManager manager = _runScript(address(0));
        assertEq(manager.autoGrantCreditAmount(), 0);
    }
}
