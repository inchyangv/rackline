// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import { Script, console } from "forge-std/Script.sol";
import { CreditFacilityManager } from "../../contracts/gpu/CreditFacilityManager.sol";
import { AuthorizationVerifier } from "../../contracts/gpu/AuthorizationVerifier.sol";
import { AccountRegistry } from "../../contracts/gpu/AccountRegistry.sol";
import { ControlRegistry } from "../../contracts/gpu/ControlRegistry.sol";
import { ReceivableBook } from "../../contracts/gpu/ReceivableBook.sol";
import { ExposureController } from "../../contracts/gpu/ExposureController.sol";
import { GpuRiskPolicy } from "../../contracts/gpu/GpuRiskPolicy.sol";
import { GpuTypes } from "../../contracts/gpu/types/GpuTypes.sol";
import { IDebtLedger } from "../../contracts/gpu/interfaces/IDebtLedger.sol";

/// @notice Opens an ADDITIONAL TEST_ONLY facility for the already onboarded simulated borrower/account.
///         A REPAID facility is terminal, so a further live draw needs a fresh facility id, control agreement,
///         underwriter authorization and its own source obligations. Reuses the published TEST_ONLY policy and
///         never mints a borrowing base: draws still require consumed native proofs and a fresh checkpoint.
contract OpenGpuFacility is Script {
    GpuTypes.ProviderId public constant PROVIDER = GpuTypes.ProviderId.wrap(keccak256("mockdepin-testonly"));
    GpuTypes.AccountKey public constant ACCOUNT =
        GpuTypes.AccountKey.wrap(keccak256("mockdepin-testonly:native-integration"));
    bytes32 public constant BORROWER = keccak256("gpu080-borrower-v2");
    bytes32 public constant POLICY = keccak256("gpu080-TEST_ONLY-policy-v2");

    struct Env {
        address borrower;
        address source;
        address sourceToken;
        GpuTypes.FacilityId facility;
        bytes32 agreement;
        uint256 limit;
    }

    function run() external {
        require(block.chainid == 102_031, "CC3 testnet only");
        CreditFacilityManager manager = CreditFacilityManager(vm.envAddress("GPU_MANAGER"));
        uint256 operatorKey = vm.envUint("PRIVATE_KEY");
        uint256 underwriterKey = vm.envUint("GPU_UNDERWRITER_PRIVATE_KEY");
        Env memory env = Env({
            borrower: vm.envAddress("GPU_BORROWER"),
            source: vm.envAddress("GPU_SOURCE_EMITTER"),
            sourceToken: vm.envAddress("GPU_SOURCE_TOKEN"),
            facility: GpuTypes.FacilityId.wrap(keccak256(bytes(vm.envString("GPU_FACILITY_NAME")))),
            agreement: keccak256(bytes(vm.envString("GPU_AGREEMENT_NAME"))),
            limit: vm.envUint("GPU_FACILITY_LIMIT")
        });
        require(
            AccountRegistry(address(manager.ACCOUNTS())).isWalletOf(BORROWER, env.borrower),
            "borrower wallet must already be linked"
        );
        require(GpuRiskPolicy(address(manager.POLICY())).params(POLICY).testOnly, "TEST_ONLY policy required");

        _open(manager, underwriterKey, env);

        vm.startBroadcast(operatorKey);
        ControlRegistry(address(manager.CONTROL())).observe(env.agreement, GpuTypes.ControlGrade.E2, env.source);
        manager.transition(env.facility, GpuTypes.FacilityState.UNDER_REVIEW, "TEST_ONLY_onboarding");
        vm.stopBroadcast();

        _authorize(manager, AuthorizationVerifier(address(manager.AUTH())), underwriterKey, env.facility, env.agreement, env.limit);

        vm.startBroadcast(operatorKey);
        manager.transition(env.facility, GpuTypes.FacilityState.ACTIVE, "TEST_ONLY_simulated_control");
        vm.stopBroadcast();
        console.log("facilityId");
        console.logBytes32(GpuTypes.FacilityId.unwrap(env.facility));
        console.log("controlAgreementId");
        console.logBytes32(env.agreement);
        console.log("TEST_ONLY facility opened. Native proof consumption is still required before draw.");
    }

    function _open(CreditFacilityManager manager, uint256 underwriterKey, Env memory env) internal {
        ControlRegistry control = ControlRegistry(address(manager.CONTROL()));
        IDebtLedger.Terms memory terms = IDebtLedger.Terms({
            loanAsset: GpuTypes.AssetRef(uint64(block.chainid), manager.VAULT().asset(), 6),
            rateBps: 1000,
            maturityAt: uint64(block.timestamp + 1 days),
            termsVersionId: keccak256("TEST_ONLY_NO_MONETARY_VALUE"),
            policyVersionId: POLICY,
            executionProfile: GpuTypes.ExecutionProfile.NATIVE_TESTNET,
            capitalizeUnpaidInterest: false
        });
        vm.startBroadcast(underwriterKey);
        control.createAgreement(
            env.agreement,
            BORROWER,
            ACCOUNT,
            GpuTypes.ControlGrade.E2,
            env.source,
            11_155_111,
            keccak256("TEST_ONLY_SIMULATED_CONTROL_NOT_PARTNER_E2"),
            uint64(block.timestamp),
            uint64(block.timestamp + 2 days),
            keccak256("LOCAL_SOURCE_PERMISSION_TEST_NOT_LIVE_PARTNER_POC")
        );
        ReceivableBook(address(manager.BOOK()))
            .registerFacility(env.facility, BORROWER, PROVIDER, GpuTypes.AssetRef(11_155_111, env.sourceToken, 6));
        manager.openFacility(env.facility, BORROWER, env.borrower, terms, env.agreement, 1);
        control.bindFacility(env.agreement, env.facility);
        ExposureController(address(manager.EXPOSURE())).enrollFacility(env.facility, BORROWER);
        vm.stopBroadcast();
    }

    function _authorize(
        CreditFacilityManager manager,
        AuthorizationVerifier auth,
        uint256 key,
        GpuTypes.FacilityId facility,
        bytes32 agreement,
        uint256 limit
    ) internal {
        uint64 until = uint64(block.timestamp + 1 days);
        GpuTypes.CreditAuthorization memory approval = GpuTypes.CreditAuthorization({
            facilityId: facility,
            decisionHash: keccak256(abi.encode("TEST_ONLY_NATIVE_REQUIRED", facility, ACCOUNT, POLICY)),
            limit: limit,
            validUntil: until,
            policyVersionId: POLICY,
            manifestHash: manager.EVIDENCE().verifierOf(PROVIDER).manifestHash(),
            controlAgreementVersionHash: manager.controlVersionHash(agreement, 1)
        });
        GpuTypes.SupplementaryAssertion memory signature =
            _sign(
                auth,
                key,
                GpuTypes.AssertionPurpose.CREDIT_APPROVAL,
                keccak256(abi.encode(approval)),
                uint64(vm.envUint("GPU_APPROVAL_NONCE")) // per-(signer, purpose) nonce; 1 was consumed by the v2 facility
            );
        vm.startBroadcast(key);
        ExposureController(address(manager.EXPOSURE())).setAuthorization(facility, limit, POLICY, agreement, 1, until);
        manager.anchorAuthorization(approval, signature);
        manager.transition(facility, GpuTypes.FacilityState.CONTROL_PENDING, "TEST_ONLY_native_approval");
        vm.stopBroadcast();
    }

    function _sign(
        AuthorizationVerifier auth,
        uint256 key,
        GpuTypes.AssertionPurpose purpose,
        bytes32 subject,
        uint64 nonce
    ) internal view returns (GpuTypes.SupplementaryAssertion memory assertion) {
        assertion = GpuTypes.SupplementaryAssertion(
            purpose, subject, vm.addr(key), 0, nonce, uint64(block.timestamp), uint64(block.timestamp + 10 minutes), ""
        );
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(key, auth.hashAssertion(assertion));
        assertion.signature = abi.encodePacked(r, s, v);
    }
}
