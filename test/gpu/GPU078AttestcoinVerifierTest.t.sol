// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import { Test } from "forge-std/Test.sol";
import { INativeQueryVerifier } from "@gluwa/asc-contracts/contracts/write-ability/common/INativeQueryVerifier.sol";
import { GpuTypes } from "../../contracts/gpu/types/GpuTypes.sol";
import { ProtocolRoles } from "../../contracts/gpu/ProtocolRoles.sol";
import { ProviderRegistry } from "../../contracts/gpu/ProviderRegistry.sol";
import { IProviderRegistry } from "../../contracts/gpu/interfaces/IProviderRegistry.sol";
import { IRevenueVerifier } from "../../contracts/gpu/interfaces/IRevenueVerifier.sol";
import { MockBlockProver } from "../../contracts/gpu/mocks/MockBlockProver.sol";
import { AttestcoinRevenueVerifier } from "../../contracts/gpu/AttestcoinRevenueVerifier.sol";

/// @dev TEST_ONLY precompile double that answers any selector with scripted raw return data (or reverts).
contract ScriptedProver {
    bytes public verifyReturn = abi.encode(true);
    bytes public txIndexReturn = abi.encode(uint64(0));
    bool public revertVerify;

    function setVerifyReturn(bytes calldata r) external {
        verifyReturn = r;
    }

    function setTxIndexReturn(bytes calldata r) external {
        txIndexReturn = r;
    }

    function setRevertVerify(bool r) external {
        revertVerify = r;
    }

    fallback(bytes calldata input) external returns (bytes memory) {
        bytes4 sel = bytes4(input[:4]);
        if (sel == INativeQueryVerifier.calculateTxIndex.selector) return txIndexReturn;
        if (revertVerify) revert("scripted revert");
        return verifyReturn;
    }
}

/**
 * @title GPU078AttestcoinVerifierTest
 * @notice LOCAL_MOCK tests of the native verification adapter. The BlockProver is a test double here: every
 *         "positive" result below is a mock verification (verificationMethod = LOCAL_MOCK). Real native acceptance
 *         (G-ASC) is GPU-080 on a public testnet and is NOT claimed by this suite.
 */
contract GPU078AttestcoinVerifierTest is Test {
    ProtocolRoles roles;
    ProviderRegistry providers;
    MockBlockProver prover;
    AttestcoinRevenueVerifier verifier;

    address admin = address(0xAD);
    address registrar = address(0x4E6);
    address guardian = address(0x6A);
    address app = address(0xA99);
    address mallory = address(0xBAD);

    string wireJson;
    string idVectors;

    bytes32 constant MANIFEST = 0x2b0162d0c206f421138269a721c6338d8cf294d67dc644bb8b35ebb9bfbff6bb; // cc3-testnet.sepolia
    bytes32 constant ENV_ID_HASH = keccak256("cc3-testnet");
    uint64 constant CHAIN_KEY = 1;
    uint64 constant SEPOLIA = 11_155_111;
    GpuTypes.ProviderId MOCK = GpuTypes.ProviderId.wrap(keccak256("mockdepin-testonly"));
    address constant ESCROW = address(0xE1);
    address constant FOREIGN = address(0xE2);
    address constant ISSUER = address(0x155);
    address constant PAYER = address(0xFA);
    bytes32 constant TOPIC =
        keccak256("ObligationRecognized(bytes32,bytes32,address,address,address,uint256,uint64,uint32)");
    bytes32 constant OTHER_TOPIC = keccak256("PayoutSettled(bytes32,bytes32,address,address,uint256,uint32)");
    bytes32 constant ACCOUNT_KEY = keccak256("mockdepin-testonly:acct-A");
    uint64 constant HEIGHT = 9_100_000;

    function setUp() public {
        wireJson = vm.readFile("test/fixtures/gpu/attestcoin/wire/synthetic-obligation-v1.json");
        idVectors = vm.readFile("test/fixtures/gpu/attestcoin/canonical-id-vectors-v1.json");
        assertEq(vm.parseJsonString(wireJson, ".kind"), "SYNTHETIC_WIRE_FIXTURES");

        roles = new ProtocolRoles(admin);
        providers = new ProviderRegistry(roles);
        prover = new MockBlockProver();
        vm.startPrank(admin);
        roles.grantRole(roles.REGISTRAR(), registrar);
        roles.grantRole(roles.GUARDIAN(), guardian);
        vm.stopPrank();

        vm.startPrank(registrar);
        providers.registerProvider(MOCK, _cfg(GpuTypes.ExecutionProfile.LOCAL_MOCK, true, 1, MANIFEST));
        providers.registerEmitter(
            MOCK, ESCROW, TOPIC, GpuTypes.EvidenceMeaning.OBLIGATION_RECOGNIZED, bytes32(0), address(0)
        );
        vm.stopPrank();

        verifier = _deploy(address(prover), GpuTypes.ExecutionProfile.LOCAL_MOCK, _limits(8192, 16, 32, 64));
    }

    // ------------------------------------------------------------------ helpers

    function _cfg(GpuTypes.ExecutionProfile p, bool testOnly, uint8 encoding, bytes32 manifest)
        internal
        pure
        returns (IProviderRegistry.ProviderConfig memory)
    {
        return IProviderRegistry.ProviderConfig({
            sourceChain: GpuTypes.SourceChainRef({
                envIdHash: ENV_ID_HASH,
                chainKey: CHAIN_KEY,
                chainId: SEPOLIA,
                encoding: encoding,
                manifestHash: manifest
            }),
            executionProfile: p,
            testOnly: testOnly,
            policyVersionId: keccak256("policy-v1"),
            admissionEnabled: true
        });
    }

    function _source() internal pure returns (GpuTypes.SourceChainRef memory) {
        return GpuTypes.SourceChainRef({
            envIdHash: ENV_ID_HASH, chainKey: CHAIN_KEY, chainId: SEPOLIA, encoding: 1, manifestHash: MANIFEST
        });
    }

    function _limits(uint256 tx_, uint256 logs, uint256 sib, uint256 cont)
        internal
        pure
        returns (AttestcoinRevenueVerifier.Limits memory)
    {
        return AttestcoinRevenueVerifier.Limits({
            maxTxBytes: tx_, maxLogs: logs, maxSiblings: sib, maxContinuityRoots: cont
        });
    }

    function _deploy(address precompile, GpuTypes.ExecutionProfile p, AttestcoinRevenueVerifier.Limits memory l)
        internal
        returns (AttestcoinRevenueVerifier)
    {
        return new AttestcoinRevenueVerifier(precompile, providers, MOCK, _source(), p, l);
    }

    function _fixture(string memory name) internal view returns (bytes memory) {
        return vm.parseJsonBytes(wireJson, string.concat(".cases.", name, ".txBytes"));
    }

    /// @dev siblings whose isLeft bits encode `txIndex` (official semantics, MockBlockProver._indexOf).
    function _siblingsFor(uint64 txIndex, uint256 depth)
        internal
        pure
        returns (INativeQueryVerifier.MerkleProofEntry[] memory s)
    {
        s = new INativeQueryVerifier.MerkleProofEntry[](depth);
        for (uint256 i = 0; i < depth; i++) {
            s[i] = INativeQueryVerifier.MerkleProofEntry({
                hash: keccak256(abi.encode(i)), isLeft: (txIndex >> i) & 1 == 1
            });
        }
    }

    function _envelope(bytes memory txBytes, uint64 txIndex)
        internal
        pure
        returns (GpuTypes.NativeProofEnvelope memory e)
    {
        e.chainKey = CHAIN_KEY;
        e.height = HEIGHT;
        e.encodedTransaction = txBytes;
        e.merkleRoot = keccak256("root");
        e.siblings = _siblingsFor(txIndex, 5);
        e.lowerEndpointDigest = keccak256("lower");
        e.continuityRoots = new bytes32[](2);
        e.continuityRoots[0] = keccak256("c0");
        e.continuityRoots[1] = keccak256("c1");
    }

    function _topics() internal pure returns (bytes32[] memory t) {
        t = new bytes32[](1);
        t[0] = TOPIC;
    }

    function _verify(bytes memory txBytes, uint64 txIndex) internal returns (GpuTypes.VerifiedSourceEvent[] memory) {
        vm.prank(app);
        return verifier.verifyAndExtract(_envelope(txBytes, txIndex), ESCROW, _topics());
    }

    function _vectorId(uint256 i) internal view returns (bytes32) {
        return vm.parseJsonBytes32(idVectors, string.concat(".sourceEventIds[", vm.toString(i), "].id"));
    }

    // ------------------------------------------------------------------ positive (mock verification only)

    function test_positive_twoLogs_extractedInReceiptOrder_withProvenPosition() public {
        GpuTypes.VerifiedSourceEvent[] memory ev = _verify(_fixture("obligation2Logs"), 17);
        assertEq(ev.length, 2);
        for (uint32 i = 0; i < 2; i++) {
            assertEq(ev[i].locator.chainKey, CHAIN_KEY);
            assertEq(ev[i].locator.height, HEIGHT);
            assertEq(ev[i].locator.txIndex, 17, "txIndex must come from calculateTxIndex over the merkle proof");
            assertEq(ev[i].locator.logOrdinal, i);
            assertEq(ev[i].emitter, ESCROW);
            assertEq(ev[i].topic0, TOPIC);
            assertEq(ev[i].topics.length, 4);
            assertEq(ev[i].topics[1], ACCOUNT_KEY);
            assertEq(ev[i].manifestHash, MANIFEST);
            assertEq(ev[i].verifier, address(verifier));
            assertEq(
                GpuTypes.SourceEventId.unwrap(ev[i].id),
                GpuTypes.SourceEventId.unwrap(verifier.sourceEventId(HEIGHT, 17, i))
            );
        }
        // the official state-changing overload was used, never the view `verify`
        assertEq(
            prover.lastSelector(),
            bytes4(keccak256("verifyAndEmit(uint64,uint64,bytes,(bytes32,(bytes32,bool)[]),(bytes32,bytes32[]))"))
        );
    }

    function test_positive_eventIdsMatchCrossLanguageVectors() public {
        // canonical-id-vectors-v1.json[0..1]: cc3-testnet / chainKey 1 / height 9100000 / txIndex 17 / ordinal 0,1
        GpuTypes.VerifiedSourceEvent[] memory ev = _verify(_fixture("obligation2Logs"), 17);
        assertEq(GpuTypes.SourceEventId.unwrap(ev[0].id), _vectorId(0));
        assertEq(GpuTypes.SourceEventId.unwrap(ev[1].id), _vectorId(1));
        // vector[4]: uint64/uint32 extremes
        assertEq(
            GpuTypes.SourceEventId.unwrap(verifier.sourceEventId(type(uint64).max, type(uint32).max, type(uint32).max)),
            _vectorId(4)
        );
    }

    function test_positive_decodedDataMatchesFixtureAmountsAndRefs() public {
        GpuTypes.VerifiedSourceEvent[] memory ev = _verify(_fixture("obligation2Logs"), 17);
        string[] memory amounts = vm.parseJsonStringArray(wireJson, ".cases.obligation2Logs.amounts");
        bytes32[] memory refs = vm.parseJsonBytes32Array(wireJson, ".cases.obligation2Logs.refs");
        for (uint256 i = 0; i < 2; i++) {
            (address payer, address payee, uint256 amount, uint64 dueAt, uint32 revision) =
                abi.decode(ev[i].data, (address, address, uint256, uint64, uint32));
            assertEq(payer, PAYER);
            assertEq(payee, ESCROW);
            assertEq(amount, vm.parseUint(amounts[i]));
            assertEq(dueAt, 1_761_868_800);
            assertEq(revision, 1);
            assertEq(ev[i].topics[2], refs[i]);
            assertEq(ev[i].topics[3], bytes32(uint256(uint160(ISSUER))));
        }
        assertEq(vm.parseUint(amounts[0]), 12_000e6);
        assertEq(vm.parseUint(amounts[1]), 9000e6);
    }

    function test_positive_emitsSourceEventVerifiedPerLog() public {
        bytes32 id0 = GpuTypes.SourceEventId.unwrap(verifier.sourceEventId(HEIGHT, 17, 0));
        bytes32 id1 = GpuTypes.SourceEventId.unwrap(verifier.sourceEventId(HEIGHT, 17, 1));
        vm.expectEmit(true, true, true, true, address(verifier));
        emit IRevenueVerifier.SourceEventVerified(
            GpuTypes.SourceEventId.wrap(id0), CHAIN_KEY, HEIGHT, 17, 0, ESCROW, TOPIC
        );
        vm.expectEmit(true, true, true, true, address(verifier));
        emit IRevenueVerifier.SourceEventVerified(
            GpuTypes.SourceEventId.wrap(id1), CHAIN_KEY, HEIGHT, 17, 1, ESCROW, TOPIC
        );
        _verify(_fixture("obligation2Logs"), 17);
    }

    function test_positive_mixedEmitters_onlyRegisteredEmitterAtOrdinal1() public {
        GpuTypes.VerifiedSourceEvent[] memory ev = _verify(_fixture("mixedEmitters"), 3);
        assertEq(ev.length, 1);
        assertEq(ev[0].locator.logOrdinal, 1, "ordinal is the receipt log index, not a dense index of matches");
        assertEq(ev[0].emitter, ESCROW);
        (,, uint256 amount,,) = abi.decode(ev[0].data, (address, address, uint256, uint64, uint32));
        assertEq(amount, 9000e6);
    }

    function test_positive_multipleTopicsAllowed_butOnlyRegisteredOnesMatch() public {
        vm.prank(registrar);
        providers.registerEmitter(MOCK, ESCROW, OTHER_TOPIC, GpuTypes.EvidenceMeaning.PAYOUT, bytes32(0), address(0));
        bytes32[] memory t = new bytes32[](2);
        t[0] = OTHER_TOPIC;
        t[1] = TOPIC;
        vm.prank(app);
        GpuTypes.VerifiedSourceEvent[] memory ev =
            verifier.verifyAndExtract(_envelope(_fixture("obligation2Logs"), 17), ESCROW, t);
        assertEq(ev.length, 2);
    }

    function test_views_reportLocalMockBinding() public view {
        assertEq(uint8(verifier.executionProfile()), uint8(GpuTypes.ExecutionProfile.LOCAL_MOCK));
        assertEq(uint8(verifier.verificationMethod()), uint8(GpuTypes.VerificationMethod.LOCAL_MOCK));
        assertEq(verifier.manifestHash(), MANIFEST);
        GpuTypes.SourceChainRef memory s = verifier.sourceChain();
        assertEq(s.chainKey, CHAIN_KEY);
        assertEq(s.chainId, SEPOLIA);
        assertEq(s.encoding, 1);
        assertEq(s.envIdHash, ENV_ID_HASH);
        assertEq(verifier.maxEncodedTransactionBytes(), 8192);
        assertEq(address(verifier.PRECOMPILE()), address(prover));
    }

    // ------------------------------------------------------------------ position / hints are never trusted

    function test_positionBinding_heightAndTxIndexChangeTheEventId() public {
        GpuTypes.VerifiedSourceEvent[] memory a = _verify(_fixture("obligation2Logs"), 17);
        GpuTypes.VerifiedSourceEvent[] memory b = _verify(_fixture("obligation2Logs"), 18);
        assertTrue(GpuTypes.SourceEventId.unwrap(a[0].id) != GpuTypes.SourceEventId.unwrap(b[0].id));
        GpuTypes.NativeProofEnvelope memory e = _envelope(_fixture("obligation2Logs"), 17);
        e.height = HEIGHT + 1;
        vm.prank(app);
        GpuTypes.VerifiedSourceEvent[] memory c = verifier.verifyAndExtract(e, ESCROW, _topics());
        assertTrue(GpuTypes.SourceEventId.unwrap(a[0].id) != GpuTypes.SourceEventId.unwrap(c[0].id));
    }

    function test_frontRun_publicVerifyHasNoStateEffect_sameResultForApp() public {
        vm.prank(mallory);
        GpuTypes.VerifiedSourceEvent[] memory first =
            verifier.verifyAndExtract(_envelope(_fixture("obligation2Logs"), 17), ESCROW, _topics());
        GpuTypes.VerifiedSourceEvent[] memory second = _verify(_fixture("obligation2Logs"), 17);
        assertEq(first.length, second.length);
        for (uint256 i = 0; i < first.length; i++) {
            assertEq(GpuTypes.SourceEventId.unwrap(first[i].id), GpuTypes.SourceEventId.unwrap(second[i].id));
            assertEq(first[i].data, second[i].data);
        }
        // the verifier holds no consumption state: a third call is still identical
        GpuTypes.VerifiedSourceEvent[] memory third = _verify(_fixture("obligation2Logs"), 17);
        assertEq(GpuTypes.SourceEventId.unwrap(third[1].id), GpuTypes.SourceEventId.unwrap(second[1].id));
    }

    // ------------------------------------------------------------------ receipt / log rejections

    function test_reject_receiptStatusZero() public {
        vm.expectRevert(abi.encodeWithSelector(IRevenueVerifier.ReceiptNotSuccessful.selector, uint8(0)));
        _verify(_fixture("receiptFailed"), 17);
    }

    function test_reject_foreignEmitterWithIdenticalTopics() public {
        vm.expectRevert(IRevenueVerifier.NoMatchingLogs.selector);
        _verify(_fixture("foreignEmitterOnly"), 17);
    }

    function test_reject_requestingUnregisteredEmitter() public {
        vm.expectRevert(abi.encodeWithSelector(IRevenueVerifier.EmitterNotRegistered.selector, FOREIGN, TOPIC));
        vm.prank(app);
        verifier.verifyAndExtract(_envelope(_fixture("foreignEmitterOnly"), 17), FOREIGN, _topics());
    }

    function test_reject_unregisteredTopic() public {
        bytes32[] memory t = new bytes32[](1);
        t[0] = OTHER_TOPIC;
        vm.expectRevert(abi.encodeWithSelector(IRevenueVerifier.EmitterNotRegistered.selector, ESCROW, OTHER_TOPIC));
        vm.prank(app);
        verifier.verifyAndExtract(_envelope(_fixture("obligation2Logs"), 17), ESCROW, t);
    }

    function test_reject_emptyTopicList() public {
        vm.expectRevert(IRevenueVerifier.NoMatchingLogs.selector);
        vm.prank(app);
        verifier.verifyAndExtract(_envelope(_fixture("obligation2Logs"), 17), ESCROW, new bytes32[](0));
    }

    function test_reject_noLogs() public {
        vm.expectRevert(IRevenueVerifier.NoMatchingLogs.selector);
        _verify(_fixture("noLogs"), 17);
    }

    function test_reject_revokedEmitter() public {
        vm.prank(registrar);
        providers.revokeEmitter(MOCK, ESCROW, TOPIC);
        vm.expectRevert(abi.encodeWithSelector(IRevenueVerifier.EmitterNotRegistered.selector, ESCROW, TOPIC));
        _verify(_fixture("obligation2Logs"), 17);
    }

    function test_reject_tooManyLogs() public {
        AttestcoinRevenueVerifier tight =
            _deploy(address(prover), GpuTypes.ExecutionProfile.LOCAL_MOCK, _limits(8192, 1, 32, 64));
        vm.expectRevert(abi.encodeWithSelector(IRevenueVerifier.InputTooLarge.selector, 2, 1));
        vm.prank(app);
        tight.verifyAndExtract(_envelope(_fixture("obligation2Logs"), 17), ESCROW, _topics());
    }

    // ------------------------------------------------------------------ manifest / chain / admission

    function test_reject_wrongChainKey() public {
        GpuTypes.NativeProofEnvelope memory e = _envelope(_fixture("obligation2Logs"), 17);
        e.chainKey = 3;
        vm.expectRevert(abi.encodeWithSelector(IRevenueVerifier.ChainKeyMismatch.selector, CHAIN_KEY, uint64(3)));
        vm.prank(app);
        verifier.verifyAndExtract(e, ESCROW, _topics());
    }

    function test_reject_admissionSwitchedOff() public {
        vm.prank(guardian);
        providers.setAdmission(MOCK, false, "incident");
        vm.expectRevert(abi.encodeWithSelector(IRevenueVerifier.ProviderNotAdmitted.selector, MOCK));
        _verify(_fixture("obligation2Logs"), 17);
    }

    // ------------------------------------------------------------------ native precompile answers (fail closed)

    function test_reject_nativeFalse() public {
        prover.setResult(false);
        vm.expectRevert(abi.encodeWithSelector(IRevenueVerifier.NativeVerificationFailed.selector, abi.encode(false)));
        _verify(_fixture("obligation2Logs"), 17);
    }

    function test_reject_nativeRevert_reasonForwarded() public {
        prover.setRevert(true);
        bytes memory reason = abi.encodeWithSignature("Error(string)", "Merkle proof validation failed");
        vm.expectRevert(abi.encodeWithSelector(IRevenueVerifier.NativeVerificationFailed.selector, reason));
        _verify(_fixture("obligation2Logs"), 17);
    }

    function test_reject_nativeEmptyReturn() public {
        ScriptedProver scripted = new ScriptedProver();
        scripted.setVerifyReturn("");
        AttestcoinRevenueVerifier v =
            _deploy(address(scripted), GpuTypes.ExecutionProfile.LOCAL_MOCK, _limits(8192, 16, 32, 64));
        vm.expectRevert(abi.encodeWithSelector(IRevenueVerifier.NativeVerificationFailed.selector, bytes("")));
        vm.prank(app);
        v.verifyAndExtract(_envelope(_fixture("obligation2Logs"), 17), ESCROW, _topics());
    }

    function test_reject_nativeNonBooleanOrShortReturn() public {
        ScriptedProver scripted = new ScriptedProver();
        AttestcoinRevenueVerifier v =
            _deploy(address(scripted), GpuTypes.ExecutionProfile.LOCAL_MOCK, _limits(8192, 16, 32, 64));
        scripted.setVerifyReturn(abi.encode(uint256(2)));
        vm.expectRevert(
            abi.encodeWithSelector(IRevenueVerifier.NativeVerificationFailed.selector, abi.encode(uint256(2)))
        );
        vm.prank(app);
        v.verifyAndExtract(_envelope(_fixture("obligation2Logs"), 17), ESCROW, _topics());

        scripted.setVerifyReturn(hex"01");
        vm.expectRevert(abi.encodeWithSelector(IRevenueVerifier.NativeVerificationFailed.selector, bytes(hex"01")));
        vm.prank(app);
        v.verifyAndExtract(_envelope(_fixture("obligation2Logs"), 17), ESCROW, _topics());

        scripted.setVerifyReturn(abi.encode(true, true));
        vm.expectRevert(
            abi.encodeWithSelector(IRevenueVerifier.NativeVerificationFailed.selector, abi.encode(true, true))
        );
        vm.prank(app);
        v.verifyAndExtract(_envelope(_fixture("obligation2Logs"), 17), ESCROW, _topics());
    }

    function test_reject_nativeScriptedRevert() public {
        ScriptedProver scripted = new ScriptedProver();
        scripted.setRevertVerify(true);
        AttestcoinRevenueVerifier v =
            _deploy(address(scripted), GpuTypes.ExecutionProfile.LOCAL_MOCK, _limits(8192, 16, 32, 64));
        vm.expectRevert(
            abi.encodeWithSelector(
                IRevenueVerifier.NativeVerificationFailed.selector,
                abi.encodeWithSignature("Error(string)", "scripted revert")
            )
        );
        vm.prank(app);
        v.verifyAndExtract(_envelope(_fixture("obligation2Logs"), 17), ESCROW, _topics());
    }

    function test_reject_txIndexOutOfRangeOrMalformed() public {
        ScriptedProver scripted = new ScriptedProver();
        AttestcoinRevenueVerifier v =
            _deploy(address(scripted), GpuTypes.ExecutionProfile.LOCAL_MOCK, _limits(8192, 16, 32, 64));
        scripted.setTxIndexReturn(abi.encode(uint256(type(uint64).max) + 1));
        vm.expectRevert(
            abi.encodeWithSelector(
                IRevenueVerifier.NativeVerificationFailed.selector, abi.encode(uint256(type(uint64).max) + 1)
            )
        );
        vm.prank(app);
        v.verifyAndExtract(_envelope(_fixture("obligation2Logs"), 17), ESCROW, _topics());

        scripted.setTxIndexReturn("");
        vm.expectRevert(abi.encodeWithSelector(IRevenueVerifier.NativeVerificationFailed.selector, bytes("")));
        vm.prank(app);
        v.verifyAndExtract(_envelope(_fixture("obligation2Logs"), 17), ESCROW, _topics());
    }

    // ------------------------------------------------------------------ input shape (oversized / malformed)

    function test_reject_oversizedEncodedTransaction() public {
        bytes memory txBytes = _fixture("obligation2Logs");
        AttestcoinRevenueVerifier tight =
            _deploy(address(prover), GpuTypes.ExecutionProfile.LOCAL_MOCK, _limits(txBytes.length - 1, 16, 32, 64));
        vm.expectRevert(
            abi.encodeWithSelector(IRevenueVerifier.InputTooLarge.selector, txBytes.length, txBytes.length - 1)
        );
        vm.prank(app);
        tight.verifyAndExtract(_envelope(txBytes, 17), ESCROW, _topics());
    }

    function test_reject_oversizedSiblingsAndContinuity() public {
        GpuTypes.NativeProofEnvelope memory e = _envelope(_fixture("obligation2Logs"), 17);
        e.siblings = _siblingsFor(17, 33);
        vm.expectRevert(abi.encodeWithSelector(IRevenueVerifier.InputTooLarge.selector, 33, 32));
        vm.prank(app);
        verifier.verifyAndExtract(e, ESCROW, _topics());

        e = _envelope(_fixture("obligation2Logs"), 17);
        e.continuityRoots = new bytes32[](65);
        vm.expectRevert(abi.encodeWithSelector(IRevenueVerifier.InputTooLarge.selector, 65, 64));
        vm.prank(app);
        verifier.verifyAndExtract(e, ESCROW, _topics());
    }

    function test_reject_emptyEncodedTransaction() public {
        vm.expectRevert(abi.encodeWithSelector(IRevenueVerifier.MalformedEncoding.selector, bytes("")));
        _verify("", 17);
    }

    function test_reject_malformedBytes_officialDecoderRevertIsWrapped() public {
        // valid leading type byte (2) followed by garbage instead of the chunk array
        bytes memory garbage = abi.encodePacked(uint256(2), keccak256("junk"), keccak256("more"));
        vm.expectRevert(); // MalformedEncoding(reason) with the decoder's revert data
        _verify(garbage, 17);
        // and the error is specifically MalformedEncoding, not a raw decoder panic
        vm.prank(app);
        (bool ok, bytes memory ret) = address(verifier)
            .call(abi.encodeCall(verifier.verifyAndExtract, (_envelope(garbage, 17), ESCROW, _topics())));
        assertFalse(ok);
        assertEq(bytes4(ret), IRevenueVerifier.MalformedEncoding.selector);
    }

    function test_reject_truncatedFixtureBytes() public {
        bytes memory full = _fixture("obligation2Logs");
        bytes memory cut = new bytes(full.length - 64);
        for (uint256 i = 0; i < cut.length; i++) {
            cut[i] = full[i];
        }
        vm.prank(app);
        (bool ok, bytes memory ret) =
            address(verifier).call(abi.encodeCall(verifier.verifyAndExtract, (_envelope(cut, 17), ESCROW, _topics())));
        assertFalse(ok);
        assertEq(bytes4(ret), IRevenueVerifier.MalformedEncoding.selector);
    }

    function test_reject_unsupportedTransactionType() public {
        bytes memory typed = abi.encode(uint8(5), new bytes[](0));
        vm.expectRevert(abi.encodeWithSelector(IRevenueVerifier.TransactionTypeUnsupported.selector, uint8(5)));
        _verify(typed, 17);
    }

    function test_reject_tamperedAmountByte_whenNativeSaysNo() public {
        // A real BlockProver rejects bytes that do not hash to the attested leaf (GPU-080). Locally we can only
        // show that a `false` answer on tampered bytes is fail-closed and no decoded value leaks out.
        bytes memory tampered = _fixture("obligation2Logs");
        tampered[tampered.length - 300] ^= 0x01;
        prover.setResult(false);
        vm.expectRevert(abi.encodeWithSelector(IRevenueVerifier.NativeVerificationFailed.selector, abi.encode(false)));
        _verify(tampered, 17);
    }

    function test_decodeReceiptForSelf_isNotPubliclyCallable() public {
        vm.expectRevert(AttestcoinRevenueVerifier.NotSelf.selector);
        vm.prank(mallory);
        verifier.decodeReceiptForSelf(_fixture("obligation2Logs"));
    }

    // ------------------------------------------------------------------ constructor / profile binding

    function test_constructor_nativeProfileCannotBindMock() public {
        vm.expectRevert(
            abi.encodeWithSelector(
                IRevenueVerifier.MockNotAllowedInProfile.selector, GpuTypes.ExecutionProfile.NATIVE_TESTNET
            )
        );
        _deploy(address(prover), GpuTypes.ExecutionProfile.NATIVE_TESTNET, _limits(8192, 16, 32, 64));
        vm.expectRevert(
            abi.encodeWithSelector(
                IRevenueVerifier.MockNotAllowedInProfile.selector, GpuTypes.ExecutionProfile.PRODUCTION
            )
        );
        _deploy(address(prover), GpuTypes.ExecutionProfile.PRODUCTION, _limits(8192, 16, 32, 64));
    }

    function test_constructor_localMockCannotClaimOfficialAddress() public {
        address official = verifier.OFFICIAL_PRECOMPILE();
        vm.expectRevert(
            abi.encodeWithSelector(
                AttestcoinRevenueVerifier.InvalidBinding.selector,
                "LOCAL_MOCK must bind an explicit test double, not the official address"
            )
        );
        _deploy(official, GpuTypes.ExecutionProfile.LOCAL_MOCK, _limits(8192, 16, 32, 64));
    }

    function test_constructor_rejectsUnsupportedEncoding() public {
        GpuTypes.SourceChainRef memory s = _source();
        s.encoding = 2;
        vm.expectRevert(abi.encodeWithSelector(IRevenueVerifier.EncodingUnsupported.selector, uint8(2)));
        new AttestcoinRevenueVerifier(
            address(prover), providers, MOCK, s, GpuTypes.ExecutionProfile.LOCAL_MOCK, _limits(8192, 16, 32, 64)
        );
    }

    function test_constructor_rejectsZeroLimitsAndZeroBinding() public {
        vm.expectRevert(abi.encodeWithSelector(AttestcoinRevenueVerifier.InvalidBinding.selector, "limits"));
        _deploy(address(prover), GpuTypes.ExecutionProfile.LOCAL_MOCK, _limits(0, 16, 32, 64));
        GpuTypes.SourceChainRef memory s = _source();
        s.manifestHash = bytes32(0);
        vm.expectRevert(
            abi.encodeWithSelector(AttestcoinRevenueVerifier.InvalidBinding.selector, "manifest/chainKey/chainId")
        );
        new AttestcoinRevenueVerifier(
            address(prover), providers, MOCK, s, GpuTypes.ExecutionProfile.LOCAL_MOCK, _limits(8192, 16, 32, 64)
        );
    }

    function test_constructor_rejectsProviderProfileMismatch() public {
        // a NATIVE_TESTNET provider vs a LOCAL_MOCK verifier: profiles must match (no mock verifier for a native
        // provider)
        GpuTypes.ProviderId native = GpuTypes.ProviderId.wrap(keccak256("mockdepin-native-testnet"));
        vm.prank(registrar);
        providers.registerProvider(native, _cfg(GpuTypes.ExecutionProfile.NATIVE_TESTNET, true, 1, MANIFEST));
        vm.expectRevert(abi.encodeWithSelector(AttestcoinRevenueVerifier.InvalidBinding.selector, "provider profile"));
        new AttestcoinRevenueVerifier(
            address(prover),
            providers,
            native,
            _source(),
            GpuTypes.ExecutionProfile.LOCAL_MOCK,
            _limits(8192, 16, 32, 64)
        );
    }

    function test_constructor_rejectsProviderSourceChainMismatch() public {
        bytes32 otherManifest = keccak256("some-other-manifest");
        GpuTypes.ProviderId other = GpuTypes.ProviderId.wrap(keccak256("other-provider"));
        vm.prank(registrar);
        providers.registerProvider(other, _cfg(GpuTypes.ExecutionProfile.LOCAL_MOCK, true, 1, otherManifest));
        vm.expectRevert(
            abi.encodeWithSelector(AttestcoinRevenueVerifier.InvalidBinding.selector, "provider source chain")
        );
        new AttestcoinRevenueVerifier(
            address(prover),
            providers,
            other,
            _source(),
            GpuTypes.ExecutionProfile.LOCAL_MOCK,
            _limits(8192, 16, 32, 64)
        );
    }

    function test_constructor_rejectsUnknownProvider() public {
        GpuTypes.ProviderId unknown = GpuTypes.ProviderId.wrap(keccak256("nobody"));
        vm.expectRevert(abi.encodeWithSelector(ProviderRegistry.ProviderUnknown.selector, unknown));
        new AttestcoinRevenueVerifier(
            address(prover),
            providers,
            unknown,
            _source(),
            GpuTypes.ExecutionProfile.LOCAL_MOCK,
            _limits(8192, 16, 32, 64)
        );
    }

    function test_nativeProfile_bindsOfficialAddressOnly_andReportsAttestcoinNative() public {
        // Deploying against the official address is allowed for a NATIVE_TESTNET provider; no call is made here.
        GpuTypes.ProviderId native = GpuTypes.ProviderId.wrap(keccak256("mockdepin-native-testnet"));
        vm.prank(registrar);
        providers.registerProvider(native, _cfg(GpuTypes.ExecutionProfile.NATIVE_TESTNET, true, 1, MANIFEST));
        AttestcoinRevenueVerifier v = new AttestcoinRevenueVerifier(
            verifier.OFFICIAL_PRECOMPILE(),
            providers,
            native,
            _source(),
            GpuTypes.ExecutionProfile.NATIVE_TESTNET,
            _limits(8192, 16, 32, 64)
        );
        assertEq(uint8(v.verificationMethod()), uint8(GpuTypes.VerificationMethod.ATTESTCOIN_NATIVE));
        assertEq(address(v.PRECOMPILE()), 0x0000000000000000000000000000000000000FD2);
        // On a local EVM there is no precompile at 0xFD2: the call must fail closed, never "succeed" by accident.
        vm.prank(registrar);
        providers.registerEmitter(
            native, ESCROW, TOPIC, GpuTypes.EvidenceMeaning.OBLIGATION_RECOGNIZED, bytes32(0), address(0)
        );
        vm.prank(app);
        (bool ok, bytes memory ret) = address(v)
            .call(abi.encodeCall(v.verifyAndExtract, (_envelope(_fixture("obligation2Logs"), 17), ESCROW, _topics())));
        assertFalse(ok);
        assertEq(bytes4(ret), IRevenueVerifier.NativeVerificationFailed.selector);
    }
}
