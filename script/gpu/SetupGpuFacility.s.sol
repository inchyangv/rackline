// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import { Script, console } from "forge-std/Script.sol";
import { CreditFacilityManager } from "../../contracts/gpu/CreditFacilityManager.sol";
import { ProtocolRoles } from "../../contracts/gpu/ProtocolRoles.sol";
import { ProviderRegistry } from "../../contracts/gpu/ProviderRegistry.sol";
import { AuthorizationVerifier } from "../../contracts/gpu/AuthorizationVerifier.sol";
import { AccountRegistry } from "../../contracts/gpu/AccountRegistry.sol";
import { ControlRegistry } from "../../contracts/gpu/ControlRegistry.sol";
import { ReceivableBook } from "../../contracts/gpu/ReceivableBook.sol";
import { ExposureController } from "../../contracts/gpu/ExposureController.sol";
import { GpuRiskPolicy } from "../../contracts/gpu/GpuRiskPolicy.sol";
import { GpuTestToken } from "../../contracts/gpu/mocks/GpuTestToken.sol";
import { GpuTypes } from "../../contracts/gpu/types/GpuTypes.sol";
import { IDebtLedger } from "../../contracts/gpu/interfaces/IDebtLedger.sol";
import { IRiskPolicy } from "../../contracts/gpu/interfaces/IRiskPolicy.sol";

/// @notice Approved TEST_ONLY technical loan setup. SIMULATED control is labelled in the agreement/terms and
/// never a partner E2 claim. No borrowing base is minted here: draw remains impossible until real source proofs
/// are consumed through the immutable official native verifier and a source reservation is still current.
contract SetupGpuFacility is Script {
    GpuTypes.FacilityId public constant FACILITY = GpuTypes.FacilityId.wrap(keccak256("gpu080-facility-v2"));
    GpuTypes.ProviderId public constant PROVIDER = GpuTypes.ProviderId.wrap(keccak256("mockdepin-testonly"));
    GpuTypes.AccountKey public constant ACCOUNT =
        GpuTypes.AccountKey.wrap(keccak256("mockdepin-testonly:native-integration"));
    bytes32 public constant BORROWER = keccak256("gpu080-borrower-v2");
    bytes32 public constant AGREEMENT = keccak256("gpu080-SIMULATED-control-v2");
    bytes32 public constant POLICY = keccak256("gpu080-TEST_ONLY-policy-v2");
    uint256 public constant LIMIT = 37_500_000; // 50% of 75 TEST_ONLY source tUSD remaining after the source payout

    function run() external {
        require(block.chainid == 102_031, "CC3 testnet only");
        CreditFacilityManager manager = CreditFacilityManager(vm.envAddress("GPU_MANAGER"));
        uint256 operatorKey = vm.envUint("PRIVATE_KEY");
        uint256 borrowerKey = vm.envUint("GPU_BORROWER_PRIVATE_KEY");
        uint256 underwriterKey = vm.envUint("GPU_UNDERWRITER_PRIVATE_KEY");
        address source = vm.envAddress("GPU_SOURCE_EMITTER");
        address sourceToken = vm.envAddress("GPU_SOURCE_TOKEN");
        _onboard(manager, operatorKey, borrowerKey);
        _underwrite(manager, underwriterKey, vm.addr(borrowerKey), source, sourceToken);
        ControlRegistry control = ControlRegistry(address(manager.CONTROL()));
        vm.startBroadcast(operatorKey);
        control.observe(AGREEMENT, GpuTypes.ControlGrade.E2, source);
        manager.transition(FACILITY, GpuTypes.FacilityState.UNDER_REVIEW, "TEST_ONLY_onboarding");
        vm.stopBroadcast();
        _authorize(manager, AuthorizationVerifier(address(manager.AUTH())), underwriterKey);
        vm.startBroadcast(operatorKey);
        manager.transition(FACILITY, GpuTypes.FacilityState.ACTIVE, "TEST_ONLY_simulated_control");
        manager.pauseDraws(false);
        vm.stopBroadcast();
        console.log("facilityId");
        console.logBytes32(GpuTypes.FacilityId.unwrap(FACILITY));
        console.log("borrowerId");
        console.logBytes32(BORROWER);
        console.log("controlAgreementId");
        console.logBytes32(AGREEMENT);
        console.log("TEST_ONLY setup complete. Native proof consumption is still required before draw.");
    }

    function _onboard(CreditFacilityManager manager, uint256 operatorKey, uint256 borrowerKey) internal {
        ProviderRegistry providers = ProviderRegistry(address(ReceivableBook(address(manager.BOOK())).PROVIDERS()));
        require(
            providers.provider(PROVIDER).testOnly
                && providers.provider(PROVIDER).executionProfile == GpuTypes.ExecutionProfile.NATIVE_TESTNET,
            "TEST_ONLY native provider required"
        );
        GpuTestToken token = GpuTestToken(manager.VAULT().asset());
        require(token.testOnly(), "test token required");
        AccountRegistry accounts = AccountRegistry(address(manager.ACCOUNTS()));
        AuthorizationVerifier auth = AuthorizationVerifier(address(manager.AUTH()));
        GpuTypes.SupplementaryAssertion memory link = _sign(
            auth,
            borrowerKey,
            GpuTypes.AssertionPurpose.WALLET_LINK,
            accounts.walletLinkSubject(BORROWER, vm.addr(borrowerKey)),
            1
        );
        vm.startBroadcast(operatorKey);
        providers.setAdmission(PROVIDER, true, "GPU080 TEST_ONLY actual native integration; no partner admission");
        accounts.linkAccount(BORROWER, PROVIDER, ACCOUNT);
        accounts.linkWallet(BORROWER, link);
        token.faucet();
        token.approve(address(manager.VAULT()), 1000e6);
        manager.VAULT().deposit(1000e6, 1);
        vm.stopBroadcast();
    }

    function _underwrite(
        CreditFacilityManager manager,
        uint256 key,
        address borrower,
        address source,
        address sourceToken
    ) internal {
        vm.startBroadcast(key);
        GpuRiskPolicy(address(manager.POLICY()))
            .publish(
                POLICY,
                IRiskPolicy.Params({
                    advanceRateBps: 5000,
                    overdueHaircutBps: 1000,
                    concentrationHaircutBps: 0,
                    collectabilityHaircutBps: 0,
                    evidenceValidityWindow: 1 days,
                    checkpointMaxAge: 15 minutes,
                    controlObservationMaxAge: 15 minutes,
                    decisionValidity: 1 days,
                    maxTenor: 2 days,
                    reserveBps: 0,
                    dscrMinBps: 0,
                    perBorrowerCap: 100e6,
                    perGroupCap: 100e6,
                    perProviderCap: 100e6,
                    globalCap: 100e6,
                    testOnly: true
                }),
                0
            );
        ControlRegistry control = ControlRegistry(address(manager.CONTROL()));
        control.createAgreement(
            AGREEMENT,
            BORROWER,
            ACCOUNT,
            GpuTypes.ControlGrade.E2,
            source,
            11_155_111,
            keccak256("TEST_ONLY_SIMULATED_CONTROL_NOT_PARTNER_E2"),
            uint64(block.timestamp),
            uint64(block.timestamp + 2 days),
            keccak256("LOCAL_SOURCE_PERMISSION_TEST_NOT_LIVE_PARTNER_POC")
        );
        ReceivableBook(address(manager.BOOK()))
            .registerFacility(FACILITY, BORROWER, PROVIDER, GpuTypes.AssetRef(11_155_111, sourceToken, 6));
        manager.openFacility(
            FACILITY,
            BORROWER,
            borrower,
            IDebtLedger.Terms({
                loanAsset: GpuTypes.AssetRef(uint64(block.chainid), manager.VAULT().asset(), 6),
                rateBps: 1000,
                maturityAt: uint64(block.timestamp + 1 days),
                termsVersionId: keccak256("TEST_ONLY_NO_MONETARY_VALUE"),
                policyVersionId: POLICY,
                executionProfile: GpuTypes.ExecutionProfile.NATIVE_TESTNET,
                capitalizeUnpaidInterest: false
            }),
            AGREEMENT,
            1
        );
        control.bindFacility(AGREEMENT, FACILITY);
        ExposureController(address(manager.EXPOSURE())).enrollFacility(FACILITY, BORROWER);
        vm.stopBroadcast();
    }

    function _authorize(CreditFacilityManager manager, AuthorizationVerifier auth, uint256 key) internal {
        uint64 until = uint64(block.timestamp + 1 days);
        GpuTypes.CreditAuthorization memory approval = GpuTypes.CreditAuthorization({
            facilityId: FACILITY,
            decisionHash: keccak256(abi.encode("TEST_ONLY_NATIVE_REQUIRED", FACILITY, ACCOUNT, POLICY)),
            limit: LIMIT,
            validUntil: until,
            policyVersionId: POLICY,
            manifestHash: manager.EVIDENCE().verifierOf(PROVIDER).manifestHash(),
            controlAgreementVersionHash: manager.controlVersionHash(AGREEMENT, 1)
        });
        GpuTypes.SupplementaryAssertion memory signature =
            _sign(auth, key, GpuTypes.AssertionPurpose.CREDIT_APPROVAL, keccak256(abi.encode(approval)), 1);
        vm.startBroadcast(key);
        ExposureController(address(manager.EXPOSURE())).setAuthorization(FACILITY, LIMIT, POLICY, AGREEMENT, 1, until);
        manager.anchorAuthorization(approval, signature);
        manager.transition(FACILITY, GpuTypes.FacilityState.CONTROL_PENDING, "TEST_ONLY_native_approval");
        manager.approveDrawResume();
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
