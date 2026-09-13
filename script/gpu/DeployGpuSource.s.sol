// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import { Script, console } from "forge-std/Script.sol";
import { SourceEscrow } from "../../contracts/gpu/source/SourceEscrow.sol";
import { GpuTestToken } from "../../contracts/gpu/mocks/GpuTestToken.sol";

/// @notice GPU-080 technical source fixture on actual Sepolia. Emits real public-chain source logs carrying
/// SIMULATED partner revenue. This is not an E2 agreement, provider approval, or live loan.
contract DeployGpuSource is Script {
    function run() external returns (SourceEscrow escrow, GpuTestToken token) {
        require(block.chainid == 11_155_111, "Sepolia only");
        uint256 key = vm.envUint("PRIVATE_KEY");
        address issuer = vm.addr(key);
        address borrower = vm.envAddress("GPU_BORROWER");
        bytes32 accountKey = keccak256("mockdepin-testonly:native-integration");
        bytes32 obligationRef = keccak256("gpu080-obligation-v2");
        vm.startBroadcast(key);
        token = new GpuTestToken();
        escrow = new SourceEscrow(issuer, address(0));
        escrow.setIssuer(issuer, true);
        // Borrower account is a distinct, explicitly simulated identity; issuer cannot self-classify borrower cash.
        escrow.registerAccount(accountKey, borrower);
        escrow.admitToken(address(token), 6, false);
        escrow.setPayer(issuer, true);
        escrow.recognizeObligation(accountKey, obligationRef, issuer, address(token), 100e6, uint64(block.timestamp + 1 days));
        bytes32 facilityId = keccak256("gpu080-facility-v2");
        escrow.assignObligation(accountKey, obligationRef, keccak256(abi.encodePacked(facilityId)));
        token.faucet();
        token.approve(address(escrow), 25e6);
        escrow.settle(accountKey, obligationRef, address(token), 25e6, keccak256("gpu080-settlement-1"));
        escrow.reserveCheckpoint(accountKey, uint64(block.timestamp + 15 minutes));
        vm.stopBroadcast();
        console.log("SourceEscrow", address(escrow));
        console.log("SourceTestToken", address(token));
        console.log("SourceIssuer", issuer);
        console.log("sourceChainId", block.chainid);
        console.log("partnerRevenue SIMULATED; partnerSourceBinding UNCONFIGURED; evidence REAL_SOURCE_TX_PENDING_NATIVE_PROOF");
        console.logBytes32(accountKey); console.logBytes32(obligationRef);
    }
}
