// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import { Script, console } from "forge-std/Script.sol";
import { HashCreditManager } from "../contracts/HashCreditManager.sol";
import { LendingVault } from "../contracts/LendingVault.sol";
import { RelayerSigVerifier } from "../contracts/RelayerSigVerifier.sol";
import { RiskConfig } from "../contracts/RiskConfig.sol";
import { IRiskConfig } from "../contracts/interfaces/IRiskConfig.sol";
import { PoolRegistry } from "../contracts/PoolRegistry.sol";
import { MockERC20 } from "../contracts/mocks/MockERC20.sol";

/**
 * @title Deploy
 * @notice Deployment script for HashCredit protocol
 *
 * Usage:
 *   # Local (Anvil)
 *   forge script script/Deploy.s.sol --rpc-url http://localhost:8545 --broadcast
 *
 *   # Testnet
 *   forge script script/Deploy.s.sol --rpc-url $RPC_URL --broadcast --verify
 */
contract Deploy is Script {
    // Default configuration
    uint256 constant FIXED_APR_BPS = 1000; // 10% APR
    uint64 constant BTC_PRICE_USD = 50_000_00000000; // $50,000 (8 decimals)
    uint32 constant ADVANCE_RATE_BPS = 5000; // 50%
    uint32 constant WINDOW_SECONDS = 30 days;
    uint128 constant NEW_BORROWER_CAP = 10_000_000000; // $10,000 (6 decimals)
    uint64 constant MIN_PAYOUT_SATS = 10000; // 0.0001 BTC

    function run() external {
        uint256 deployerPrivateKey = vm.envUint("PRIVATE_KEY");
        address relayerSigner = vm.envOr("RELAYER_SIGNER", vm.addr(deployerPrivateKey));

        vm.startBroadcast(deployerPrivateKey);

        // 1. Deploy Mock USDC (for testing, use real USDC on mainnet)
        MockERC20 usdc = new MockERC20("USD Coin", "USDC", 6);
        console.log("MockUSDC deployed at:", address(usdc));

        // 2. Deploy RelayerSigVerifier
        RelayerSigVerifier verifier = new RelayerSigVerifier(relayerSigner);
        console.log("RelayerSigVerifier deployed at:", address(verifier));
        console.log("  Relayer signer:", relayerSigner);

        // 3. Deploy RiskConfig
        IRiskConfig.RiskParams memory riskParams = IRiskConfig.RiskParams({
            confirmationsRequired: 6,
            advanceRateBps: ADVANCE_RATE_BPS,
            windowSeconds: WINDOW_SECONDS,
            newBorrowerCap: NEW_BORROWER_CAP,
            globalCap: 0, // No global cap initially
            minPayoutSats: MIN_PAYOUT_SATS,
            btcPriceUsd: BTC_PRICE_USD
        });
        RiskConfig riskConfig = new RiskConfig(riskParams);
        console.log("RiskConfig deployed at:", address(riskConfig));

        // 4. Deploy PoolRegistry (permissive mode for MVP)
        PoolRegistry poolRegistry = new PoolRegistry(true);
        console.log("PoolRegistry deployed at:", address(poolRegistry));

        // 5. Deploy LendingVault
        LendingVault vault = new LendingVault(address(usdc), FIXED_APR_BPS);
        console.log("LendingVault deployed at:", address(vault));

        // 6. Deploy HashCreditManager
        HashCreditManager manager = new HashCreditManager(
            address(verifier),
            address(vault),
            address(riskConfig),
            address(poolRegistry),
            address(usdc)
        );
        console.log("HashCreditManager deployed at:", address(manager));

        // 7. Configure Vault to accept Manager
        vault.setManager(address(manager));
        console.log("Vault manager set to:", address(manager));

        // 8. Mint initial USDC liquidity (for testing)
        uint256 initialLiquidity = 1_000_000_000000; // 1M USDC
        usdc.mint(msg.sender, initialLiquidity);
        usdc.approve(address(vault), initialLiquidity);
        vault.deposit(initialLiquidity);
        console.log("Initial liquidity deposited:", initialLiquidity / 1e6, "USDC");

        vm.stopBroadcast();

        // Print summary
        console.log("\n=== Deployment Summary ===");
        console.log("MockUSDC:          ", address(usdc));
        console.log("RelayerSigVerifier:", address(verifier));
        console.log("RiskConfig:        ", address(riskConfig));
        console.log("PoolRegistry:      ", address(poolRegistry));
        console.log("LendingVault:      ", address(vault));
        console.log("HashCreditManager: ", address(manager));
        console.log("\nRelayer Signer:    ", relayerSigner);
        console.log("Initial Liquidity: ", initialLiquidity / 1e6, "USDC");
    }
}
