// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import { Script, console } from "forge-std/Script.sol";
import { HashCreditManager } from "../contracts/HashCreditManager.sol";
import { LendingVault } from "../contracts/LendingVault.sol";
import { BtcSpvVerifier } from "../contracts/BtcSpvVerifier.sol";
import { CheckpointManager } from "../contracts/CheckpointManager.sol";
import { RiskConfig } from "../contracts/RiskConfig.sol";
import { IRiskConfig } from "../contracts/interfaces/IRiskConfig.sol";
import { PoolRegistry } from "../contracts/PoolRegistry.sol";
import { MockERC20 } from "../contracts/mocks/MockERC20.sol";

/**
 * @title DeploySpv
 * @notice Deployment script for HashCredit protocol with SPV verification mode
 * @dev Deploys CheckpointManager + BtcSpvVerifier instead of RelayerSigVerifier
 *
 * Usage:
 *   # Local (Anvil)
 *   forge script script/DeploySpv.s.sol --rpc-url http://localhost:8545 --broadcast
 *
 *   # Creditcoin Testnet (chainId 102031)
 *   forge script script/DeploySpv.s.sol --rpc-url $CREDITCOIN_TESTNET_RPC --broadcast
 *
 * Environment Variables:
 *   PRIVATE_KEY         - Deployer private key (required)
 *   STABLECOIN_ADDRESS  - Existing stablecoin address (optional, deploys MockUSDC if not set)
 *   INITIAL_LIQUIDITY   - Initial liquidity in stablecoin smallest unit (optional, default 1M)
 */
contract DeploySpv is Script {
    // ============================================
    // Default Configuration
    // ============================================

    uint256 constant FIXED_APR_BPS = 1000; // 10% APR
    uint64 constant BTC_PRICE_USD = 50_000_00000000; // $50,000 (8 decimals)
    uint32 constant ADVANCE_RATE_BPS = 5000; // 50%
    uint32 constant WINDOW_SECONDS = 30 days;
    uint128 constant NEW_BORROWER_CAP = 10_000_000000; // $10,000 (6 decimals)
    uint64 constant MIN_PAYOUT_SATS = 10000; // 0.0001 BTC
    uint256 constant DEFAULT_INITIAL_LIQUIDITY = 1_000_000_000000; // 1M USDC (6 decimals)

    function run() external {
        uint256 deployerPrivateKey = vm.envUint("PRIVATE_KEY");
        address deployer = vm.addr(deployerPrivateKey);

        // Optional: use existing stablecoin
        address stablecoinAddr = vm.envOr("STABLECOIN_ADDRESS", address(0));
        uint256 initialLiquidity = vm.envOr("INITIAL_LIQUIDITY", DEFAULT_INITIAL_LIQUIDITY);

        console.log("=== HashCredit SPV Mode Deployment ===");
        console.log("Deployer:", deployer);
        console.log("Chain ID:", block.chainid);
        console.log("");

        vm.startBroadcast(deployerPrivateKey);

        // 1. Deploy or use existing stablecoin
        MockERC20 usdc;
        if (stablecoinAddr == address(0)) {
            usdc = new MockERC20("USD Coin", "USDC", 6);
            console.log("[1/7] MockUSDC deployed:", address(usdc));
        } else {
            usdc = MockERC20(stablecoinAddr);
            console.log("[1/7] Using existing stablecoin:", stablecoinAddr);
        }

        // 2. Deploy CheckpointManager
        CheckpointManager checkpointManager = new CheckpointManager(deployer);
        console.log("[2/7] CheckpointManager deployed:", address(checkpointManager));

        // 3. Deploy BtcSpvVerifier
        BtcSpvVerifier spvVerifier = new BtcSpvVerifier(deployer, address(checkpointManager));
        console.log("[3/7] BtcSpvVerifier deployed:", address(spvVerifier));

        // 4. Deploy RiskConfig
        IRiskConfig.RiskParams memory riskParams = IRiskConfig.RiskParams({
            confirmationsRequired: 6,
            advanceRateBps: ADVANCE_RATE_BPS,
            windowSeconds: WINDOW_SECONDS,
            newBorrowerCap: NEW_BORROWER_CAP,
            globalCap: 0, // No global cap initially
            minPayoutSats: MIN_PAYOUT_SATS,
            btcPriceUsd: BTC_PRICE_USD,
            minPayoutCountForFullCredit: 3,
            largePayoutThresholdSats: 10_000_000, // 0.1 BTC
            largePayoutDiscountBps: 5000, // 50%
            newBorrowerPeriodSeconds: WINDOW_SECONDS
        });
        RiskConfig riskConfig = new RiskConfig(riskParams);
        console.log("[4/7] RiskConfig deployed:", address(riskConfig));

        // 5. Deploy PoolRegistry (permissive mode for testnet)
        PoolRegistry poolRegistry = new PoolRegistry(true);
        console.log("[5/7] PoolRegistry deployed:", address(poolRegistry));

        // 6. Deploy LendingVault
        LendingVault vault = new LendingVault(address(usdc), FIXED_APR_BPS);
        console.log("[6/7] LendingVault deployed:", address(vault));

        // 7. Deploy HashCreditManager with SPV verifier
        HashCreditManager manager = new HashCreditManager(
            address(spvVerifier),
            address(vault),
            address(riskConfig),
            address(poolRegistry),
            address(usdc)
        );
        console.log("[7/7] HashCreditManager deployed:", address(manager));

        // Configure vault to accept manager
        vault.setManager(address(manager));
        console.log("");
        console.log("Vault manager configured");

        // Mint initial liquidity if using mock USDC
        if (stablecoinAddr == address(0) && initialLiquidity > 0) {
            usdc.mint(deployer, initialLiquidity);
            usdc.approve(address(vault), initialLiquidity);
            vault.deposit(initialLiquidity);
            console.log("Initial liquidity deposited:", initialLiquidity / 1e6, "USDC");
        }

        vm.stopBroadcast();

        // Print deployment summary
        console.log("");
        console.log("========================================");
        console.log("       DEPLOYMENT SUMMARY (SPV)         ");
        console.log("========================================");
        console.log("");
        console.log("Contract Addresses:");
        console.log("  Stablecoin (USDC):   ", address(usdc));
        console.log("  CheckpointManager:   ", address(checkpointManager));
        console.log("  BtcSpvVerifier:      ", address(spvVerifier));
        console.log("  RiskConfig:          ", address(riskConfig));
        console.log("  PoolRegistry:        ", address(poolRegistry));
        console.log("  LendingVault:        ", address(vault));
        console.log("  HashCreditManager:   ", address(manager));
        console.log("");
        console.log("Owner/Admin:           ", deployer);
        console.log("");
        _printEnvAndNextSteps();
    }

    function _printEnvAndNextSteps() internal pure {
        console.log("========================================");
        console.log("       .env CONFIGURATION               ");
        console.log("========================================");
        console.log("");
        console.log("# Add to your .env file:");
        console.log("# STABLECOIN_ADDRESS=<address from above>");
        console.log("# CHECKPOINT_MANAGER=<address from above>");
        console.log("# BTC_SPV_VERIFIER=<address from above>");
        console.log("# RISK_CONFIG=<address from above>");
        console.log("# POOL_REGISTRY=<address from above>");
        console.log("# LENDING_VAULT=<address from above>");
        console.log("# HASH_CREDIT_MANAGER=<address from above>");
        console.log("");
        console.log("========================================");
        console.log("         NEXT STEPS                     ");
        console.log("========================================");
        console.log("");
        console.log("1. Register a Bitcoin checkpoint:");
        console.log("   hashcredit-prover set-checkpoint --height <HEIGHT>");
        console.log("");
        console.log("2. Register borrower BTC address:");
        console.log("   hashcredit-prover set-borrower-pubkey-hash");
        console.log("     --borrower <EVM_ADDRESS>");
        console.log("     --btc-address <BTC_ADDRESS>");
        console.log("");
        console.log("3. Register borrower in Manager:");
        console.log("   cast send $HASH_CREDIT_MANAGER");
        console.log("     'registerBorrower(address,bytes32)'");
        console.log("     <BORROWER_ADDRESS> <BTC_PAYOUT_KEY_HASH>");
        console.log("");
        console.log("4. Submit SPV proof:");
        console.log("   hashcredit-prover submit-proof --txid <TXID>");
        console.log("");
    }
}
