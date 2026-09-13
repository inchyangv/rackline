// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import { Test } from "forge-std/Test.sol";
import { DeployGpu } from "../../script/gpu/DeployGpu.s.sol";
import { DeployGpuSource } from "../../script/gpu/DeployGpuSource.s.sol";
import { SetupGpuFacility } from "../../script/gpu/SetupGpuFacility.s.sol";
import { SourceEscrow } from "../../contracts/gpu/source/SourceEscrow.sol";
import { GpuTestToken } from "../../contracts/gpu/mocks/GpuTestToken.sol";
import { GpuTypes } from "../../contracts/gpu/types/GpuTypes.sol";
import { GovernanceTimelock } from "../../contracts/gpu/GovernanceTimelock.sol";
import { DebtLedger } from "../../contracts/gpu/DebtLedger.sol";

/// @notice Script replay in a local EVM, NOT native network evidence. No substituted precompile is installed.
contract GPU043DeploymentTest is Test {
    function test_nativeFacilitySetupNeverCreatesBaseWithoutRealNativeProof() public {
        vm.chainId(102_031);
        vm.warp(1_800_000_000);
        vm.setEnv("PRIVATE_KEY", "1");
        vm.setEnv("GPU_UNDERWRITER", vm.toString(vm.addr(2)));
        vm.setEnv("GPU_UNDERWRITER_PRIVATE_KEY", "2");
        vm.setEnv("GPU_BORROWER_PRIVATE_KEY", "3");
        vm.setEnv("GPU_SOURCE_EMITTER", vm.toString(address(0xE1)));
        vm.setEnv("GPU_SOURCE_TOKEN", vm.toString(address(0x501)));
        vm.deal(vm.addr(1), 100 ether);
        vm.deal(vm.addr(2), 100 ether);
        vm.deal(vm.addr(3), 100 ether);
        DeployGpu.Deployment memory d = new DeployGpu().run();
        vm.setEnv("GPU_MANAGER", vm.toString(address(d.manager)));
        SetupGpuFacility setup = new SetupGpuFacility();
        setup.run();
        assertEq(uint8(d.manager.state(setup.FACILITY())), uint8(GpuTypes.FacilityState.ACTIVE));
        assertEq(d.manager.evaluateDraw(setup.FACILITY(), 0).availableDraw, 0);
        assertEq(d.vault.nav(), 1000e6);
        assertEq(d.ledger.legalDebtAt(setup.FACILITY(), uint64(block.timestamp)), 0);
    }

    function test_nativeTestnetDeploymentSealsWritersAndSupportsWalletLpCycle() public {
        vm.chainId(102_031);
        vm.warp(1_800_000_000);
        vm.setEnv("PRIVATE_KEY", "1"); // public, disposable test key only
        vm.setEnv("GPU_UNDERWRITER", vm.toString(vm.addr(2)));
        address deployer = vm.addr(1);
        vm.deal(deployer, 100 ether);
        DeployGpu deployment = new DeployGpu();
        DeployGpu.Deployment memory d = deployment.run();
        assertTrue(d.ledger.wiringFinalized());
        assertTrue(d.vault.wiringFinalized());
        assertTrue(d.exposure.wiringFinalized());
        assertTrue(d.evidence.wiringFinalized());
        assertTrue(d.manager.drawsPaused());
        assertFalse(d.roles.hasRole(d.roles.ADMIN_ROLE(), deployer));
        assertTrue(d.roles.hasRole(d.roles.ADMIN_ROLE(), address(d.governance)));
        assertEq(address(d.verifier.PRECOMPILE()), address(0x0FD2));
        assertEq(uint8(d.verifier.verificationMethod()), uint8(GpuTypes.VerificationMethod.ATTESTCOIN_NATIVE));
        assertFalse(
            d.providers.isAdmitted(GpuTypes.ProviderId.wrap(keccak256("mockdepin-testonly")), deployment.MANIFEST())
        );
        vm.startPrank(address(0xB0));
        d.token.faucet();
        d.token.approve(address(d.vault), 1000e6);
        uint256 shares = d.vault.deposit(1000e6, 1);
        assertEq(d.vault.withdraw(shares, 1000e6), 1000e6);
        assertEq(d.token.balanceOf(address(0xB0)), 10_000e6);
        vm.stopPrank();
        bytes memory mutation = abi.encodeCall(DebtLedger.setWriter, (address(0xBAD), true));
        vm.prank(deployer);
        d.governance.schedule(address(d.ledger), 0, mutation, bytes32("writer"));
        vm.warp(block.timestamp + 1 days);
        vm.expectRevert(
            abi.encodeWithSelector(
                GovernanceTimelock.ExecutionFailed.selector, abi.encodeWithSelector(DebtLedger.WiringFinalized.selector)
            )
        );
        d.governance.execute(address(d.ledger), 0, mutation, bytes32("writer"));
    }

    function test_sourceScriptEmitsActualStateTransitionsAndProtectedCheckpoint() public {
        vm.chainId(11_155_111);
        vm.warp(1_800_000_000);
        vm.setEnv("PRIVATE_KEY", "1");
        vm.setEnv("GPU_BORROWER", vm.toString(vm.addr(3)));
        vm.deal(vm.addr(1), 100 ether);
        DeployGpuSource deployment = new DeployGpuSource();
        (SourceEscrow source, GpuTestToken token) = deployment.run();
        bytes32 account = keccak256("mockdepin-testonly:native-integration");
        bytes32 obligation = keccak256("gpu080-obligation-v2");
        assertEq(source.obligation(account, obligation).net, 100e6);
        assertEq(source.obligation(account, obligation).paid, 25e6);
        assertEq(token.balanceOf(address(source)), 25e6);
        assertEq(source.protectedUntil(account), block.timestamp + 15 minutes);
        assertEq(uint8(source.partnerSourceBinding()), 0);
    }
}
