// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import { Script, console } from "forge-std/Script.sol";
import { ProtocolRoles } from "../../contracts/gpu/ProtocolRoles.sol";
import { ProviderRegistry } from "../../contracts/gpu/ProviderRegistry.sol";
import { AuthorizationVerifier } from "../../contracts/gpu/AuthorizationVerifier.sol";
import { AccountRegistry } from "../../contracts/gpu/AccountRegistry.sol";
import { DebtLedger } from "../../contracts/gpu/DebtLedger.sol";
import { LendingVaultV2 } from "../../contracts/gpu/LendingVaultV2.sol";
import { ControlRegistry } from "../../contracts/gpu/ControlRegistry.sol";
import { EvidenceBook } from "../../contracts/gpu/EvidenceBook.sol";
import { AttestcoinRevenueVerifier } from "../../contracts/gpu/AttestcoinRevenueVerifier.sol";
import { ReceivableBook } from "../../contracts/gpu/ReceivableBook.sol";
import { GpuRiskPolicy } from "../../contracts/gpu/GpuRiskPolicy.sol";
import { ExposureController } from "../../contracts/gpu/ExposureController.sol";
import { CreditFacilityManager } from "../../contracts/gpu/CreditFacilityManager.sol";
import { RepaymentRouter, IFacilityWallets } from "../../contracts/gpu/RepaymentRouter.sol";
import { RecoveryManager } from "../../contracts/gpu/RecoveryManager.sol";
import { SettlementReceiver } from "../../contracts/gpu/SettlementReceiver.sol";
import { GovernanceTimelock } from "../../contracts/gpu/GovernanceTimelock.sol";
import { GpuTestToken } from "../../contracts/gpu/mocks/GpuTestToken.sol";
import { GpuTypes } from "../../contracts/gpu/types/GpuTypes.sol";
import { IProviderRegistry } from "../../contracts/gpu/interfaces/IProviderRegistry.sol";
import { IVaultCashView } from "../../contracts/gpu/interfaces/IExposureController.sol";

/// @notice Creditcoin TESTNET-only deployment, native official precompile, no credit grants or fabricated provider
/// binding. Draws start paused and provider admission starts disabled. LP faucet/deposit/withdraw is usable.
/// PRIVATE_KEY is consumed in-memory; no key/secret is logged. Native source configuration is a later audited
/// registrar transaction once real source addresses exist. Every execution component is sealed before handover.
contract DeployGpu is Script {
    struct Deployment {
        ProtocolRoles roles;
        ProviderRegistry providers;
        AuthorizationVerifier authorization;
        AccountRegistry accounts;
        DebtLedger ledger;
        LendingVaultV2 vault;
        ControlRegistry control;
        EvidenceBook evidence;
        AttestcoinRevenueVerifier verifier;
        ReceivableBook receivables;
        GpuRiskPolicy risk;
        ExposureController exposure;
        CreditFacilityManager manager;
        RepaymentRouter repayment;
        RecoveryManager recovery;
        SettlementReceiver settlement;
        GovernanceTimelock governance;
        GovernanceTimelock treasury;
        GpuTestToken token;
    }
    bytes32 public constant MANIFEST = 0x2b0162d0c206f421138269a721c6338d8cf294d67dc644bb8b35ebb9bfbff6bb;

    function run() external returns (Deployment memory d) {
        require(block.chainid == 102_031, "CC3 testnet only; no mock verifier on a native profile");
        uint256 key = vm.envUint("PRIVATE_KEY");
        address deployer = vm.addr(key);
        address governor = vm.envOr("GPU_GOVERNOR", deployer);
        address guardian = vm.envOr("GPU_GUARDIAN", deployer);
        uint64 delay_ = uint64(vm.envOr("GPU_GOVERNANCE_DELAY", uint256(1 days)));
        vm.startBroadcast(key);
        d.governance = new GovernanceTimelock(governor, delay_);
        d.treasury = new GovernanceTimelock(governor, delay_);
        d.roles = new ProtocolRoles(deployer);
        d.roles.grantRole(d.roles.REGISTRAR(), deployer);
        d.roles.grantRole(d.roles.SERVICER(), deployer);
        d.roles.grantRole(d.roles.RELAYER(), vm.envOr("GPU_KEEPER", deployer));
        d.roles.grantRole(d.roles.GUARDIAN(), guardian);
        d.roles.grantRole(d.roles.UNDERWRITER(), vm.envAddress("GPU_UNDERWRITER"));
        d.roles.grantRole(d.roles.TREASURY(), vm.envOr("GPU_TREASURY", address(d.treasury)));
        d.token = new GpuTestToken();
        d.providers = new ProviderRegistry(d.roles);
        d.authorization = new AuthorizationVerifier(d.roles, 15 minutes);
        d.accounts = new AccountRegistry(d.roles, d.authorization, d.providers);
        d.ledger = new DebtLedger(d.roles);
        d.vault = new LendingVaultV2(d.roles, d.ledger, address(d.token));
        d.control = new ControlRegistry(d.roles, d.accounts, d.ledger, 15 minutes);
        d.evidence = new EvidenceBook(d.roles, d.providers, keccak256("cc3-testnet"), 1 days);
        _bindNative(d);
        d.receivables = new ReceivableBook(d.roles, d.evidence, d.providers, d.accounts);
        d.risk = new GpuRiskPolicy(d.roles);
        d.exposure = new ExposureController(
            d.roles, d.receivables, d.ledger, d.control, d.risk, IVaultCashView(address(d.vault))
        );
        d.manager = new CreditFacilityManager(
            d.roles,
            d.ledger,
            d.vault,
            d.accounts,
            d.control,
            d.exposure,
            d.risk,
            d.receivables,
            d.evidence,
            d.authorization
        );
        d.repayment = new RepaymentRouter(d.roles, d.ledger, d.vault, IFacilityWallets(address(d.manager)));
        d.recovery = new RecoveryManager(d.roles, d.ledger, d.manager, d.vault, d.repayment);
        d.settlement = new SettlementReceiver(d.roles, d.repayment, address(d.token));
        _wire(d, deployer);
        // Guardian can differ from the broadcast key; in that case leave underwriter approval absent and no policy
        // or admitted collateral, which independently prevents draws until the operator freezes/enables correctly.
        if (guardian == deployer) d.manager.pauseDraws(true);
        d.roles.grantRole(d.roles.ADMIN_ROLE(), address(d.governance));
        d.roles.revokeRole(d.roles.ADMIN_ROLE(), deployer);
        vm.stopBroadcast();
        _report(d);
    }

    function _bindNative(Deployment memory d) internal {
        GpuTypes.ProviderId providerId = GpuTypes.ProviderId.wrap(keccak256("mockdepin-testonly"));
        bytes32 manifest = vm.envOr("GPU_MANIFEST_HASH", MANIFEST);
        GpuTypes.SourceChainRef memory source =
            GpuTypes.SourceChainRef(keccak256("cc3-testnet"), 1, 11_155_111, 1, manifest);
        d.providers
            .registerProvider(
                providerId,
                IProviderRegistry.ProviderConfig(
                    source, GpuTypes.ExecutionProfile.NATIVE_TESTNET, true, bytes32(0), false
                )
            );
        address emitter = vm.envOr("GPU_SOURCE_EMITTER", address(0));
        address token = vm.envOr("GPU_SOURCE_TOKEN", address(0));
        if (emitter != address(0) || token != address(0)) {
            require(emitter != address(0) && token != address(0), "source emitter/token must be paired");
            d.providers.admitToken(providerId, 11_155_111, token, 6);
            d.providers.setIssuer(providerId, vm.envOr("GPU_SOURCE_ISSUER", vm.addr(vm.envUint("PRIVATE_KEY"))), true);
            d.providers
                .registerEmitter(
                    providerId,
                    emitter,
                    keccak256(
                        "ObligationRecognizedV2(bytes32,bytes32,address,address,address,address,uint256,uint64,uint32)"
                    ),
                    GpuTypes.EvidenceMeaning.OBLIGATION_RECOGNIZED,
                    0,
                    address(0)
                );
            d.providers
                .registerEmitter(
                    providerId,
                    emitter,
                    keccak256("ObligationAssigned(bytes32,bytes32,bytes32,uint32)"),
                    GpuTypes.EvidenceMeaning.ASSIGNMENT_RECOGNIZED,
                    0,
                    address(0)
                );
            d.providers
                .registerEmitter(
                    providerId,
                    emitter,
                    keccak256("ObligationCorrected(bytes32,bytes32,int256,uint32,uint8)"),
                    GpuTypes.EvidenceMeaning.CORRECTION,
                    0,
                    address(0)
                );
            d.providers
                .registerEmitter(
                    providerId,
                    emitter,
                    keccak256("PayoutReceived(bytes32,bytes32,address,address,uint256,uint64)"),
                    GpuTypes.EvidenceMeaning.PAYOUT,
                    0,
                    address(0)
                );
            d.providers
                .registerEmitter(
                    providerId,
                    emitter,
                    keccak256("PayoutCancelled(bytes32,bytes32,uint64,uint256)"),
                    GpuTypes.EvidenceMeaning.PAYMENT_CANCELLED,
                    0,
                    address(0)
                );
            d.providers
                .registerEmitter(
                    providerId,
                    emitter,
                    keccak256("SourceCheckpointV2(bytes32,uint64,uint32,uint256,uint256,uint64,uint64)"),
                    GpuTypes.EvidenceMeaning.CORRECTION,
                    0,
                    address(0)
                );
        }
        d.verifier = new AttestcoinRevenueVerifier(
            address(0x0FD2),
            d.providers,
            providerId,
            source,
            GpuTypes.ExecutionProfile.NATIVE_TESTNET,
            AttestcoinRevenueVerifier.Limits(131_072, 256, 64, 512)
        );
        d.evidence.bindVerifier(providerId, d.verifier);
    }

    function _wire(Deployment memory d, address deployer) internal {
        d.ledger.setWriter(address(d.manager), true);
        d.ledger.setWriter(address(d.exposure), true);
        d.ledger.setWriter(address(d.repayment), true);
        d.ledger.setWriter(address(d.recovery), true);
        d.vault.setManager(address(d.manager), true);
        d.vault.setManager(address(d.repayment), true);
        d.exposure.setManager(address(d.manager), true);
        d.evidence.setConsumer(address(d.receivables), true);
        d.manager.bindRecoveryManager(address(d.recovery));
        d.vault.bindRecoveryManager(address(d.recovery));
        d.roles.grantRole(d.roles.GUARDIAN(), address(d.recovery));
        d.roles.grantRole(d.roles.RELAYER(), address(d.settlement));
        // No external conversion or partner rail is invented. A later deployment can bind approved rails before seal.
        d.ledger.finalizeWiring();
        d.vault.finalizeWiring();
        d.exposure.finalizeWiring();
        d.evidence.finalizeWiring();
        d.settlement.finalizeWiring();
        deployer;
    }

    function _report(Deployment memory d) internal view {
        console.log("executionProfile NATIVE_TESTNET");
        console.log("requiredVerification ATTESTCOIN_NATIVE");
        console.log("partnerRevenue SIMULATED; providerAdmission DISABLED; nativeStatus NOT_REQUESTED");
        console.log("chainId", block.chainid);
        console.log("manifestHash");
        console.logBytes32(d.verifier.manifestHash());
        console.log("ProtocolRoles", address(d.roles));
        console.log("ProviderRegistry", address(d.providers));
        console.log("AuthorizationVerifier", address(d.authorization));
        console.log("AccountRegistry", address(d.accounts));
        console.log("DebtLedger", address(d.ledger));
        console.log("LendingVaultV2", address(d.vault));
        console.log("ControlRegistry", address(d.control));
        console.log("EvidenceBook", address(d.evidence));
        console.log("AttestcoinRevenueVerifier", address(d.verifier));
        console.log("ReceivableBook", address(d.receivables));
        console.log("GpuRiskPolicy", address(d.risk));
        console.log("ExposureController", address(d.exposure));
        console.log("CreditFacilityManager", address(d.manager));
        console.log("RepaymentRouter", address(d.repayment));
        console.log("RecoveryManager", address(d.recovery));
        console.log("SettlementReceiver", address(d.settlement));
        console.log("GovernanceTimelock", address(d.governance));
        console.log("TreasuryTimelock", address(d.treasury));
        console.log("GpuTestToken", address(d.token));
    }
}
