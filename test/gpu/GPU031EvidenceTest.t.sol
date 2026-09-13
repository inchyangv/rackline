// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import { Test } from "forge-std/Test.sol";
import { INativeQueryVerifier } from "@gluwa/asc-contracts/contracts/write-ability/common/INativeQueryVerifier.sol";
import { GpuTypes } from "../../contracts/gpu/types/GpuTypes.sol";
import { ProtocolRoles } from "../../contracts/gpu/ProtocolRoles.sol";
import { ProviderRegistry } from "../../contracts/gpu/ProviderRegistry.sol";
import { AuthorizationVerifier } from "../../contracts/gpu/AuthorizationVerifier.sol";
import { EvidenceBook } from "../../contracts/gpu/EvidenceBook.sol";
import { AttestcoinRevenueVerifier } from "../../contracts/gpu/AttestcoinRevenueVerifier.sol";
import { MockBlockProver } from "../../contracts/gpu/mocks/MockBlockProver.sol";
import { IProviderRegistry } from "../../contracts/gpu/interfaces/IProviderRegistry.sol";
import { IRevenueVerifier } from "../../contracts/gpu/interfaces/IRevenueVerifier.sol";
import { IEvidenceBook } from "../../contracts/gpu/interfaces/IEvidenceBook.sol";

/// @dev Consumer double: consumes through the book and optionally reverts afterwards (business failure).
contract TestConsumer {
    IEvidenceBook public immutable BOOK;
    bool public failAfterConsume;
    uint256 public applied;

    constructor(IEvidenceBook book) {
        BOOK = book;
    }

    function setFail(bool f) external {
        failAfterConsume = f;
    }

    function ingest(
        GpuTypes.ProviderId providerId,
        GpuTypes.NativeProofEnvelope calldata envelope,
        address emitter,
        bytes32[] calldata topic0s,
        IEvidenceBook.ConsumeInstruction[] calldata instructions
    ) external returns (IEvidenceBook.EvidenceRecord[] memory recs) {
        recs = BOOK.consume(providerId, envelope, emitter, topic0s, instructions);
        applied += recs.length; // "business effect"
        if (failAfterConsume) revert("business rule failed");
    }
}

/**
 * @title GPU031EvidenceTest
 * @notice EvidenceBook: only native verifier output creates records; one consumption per proof-bound log; economic
 *         dedup; consumer allowlist; atomicity with business effect; verifier replacement replay; auxiliary
 *         signatures have no path in. LOCAL_MOCK verification only (G-ASC = GPU-080).
 */
contract GPU031EvidenceTest is Test {
    ProtocolRoles roles;
    ProviderRegistry providers;
    AuthorizationVerifier auth;
    MockBlockProver prover;
    AttestcoinRevenueVerifier verifier;
    EvidenceBook book;
    TestConsumer consumer;

    address admin = address(0xAD);
    address registrar = address(0x4E6);
    address mallory = address(0xBAD);
    uint256 constant UNDERWRITER_KEY = 0x0DE;
    address underwriter;

    string wireJson;

    bytes32 constant MANIFEST = 0x2b0162d0c206f421138269a721c6338d8cf294d67dc644bb8b35ebb9bfbff6bb;
    bytes32 constant ENV_ID_HASH = keccak256("cc3-testnet");
    uint64 constant CHAIN_KEY = 1;
    uint64 constant SEPOLIA = 11_155_111;
    GpuTypes.ProviderId MOCK = GpuTypes.ProviderId.wrap(keccak256("mockdepin-testonly"));
    address constant ESCROW = address(0xE1);
    bytes32 constant TOPIC =
        keccak256("ObligationRecognized(bytes32,bytes32,address,address,address,uint256,uint64,uint32)");
    GpuTypes.AccountKey ACCOUNT = GpuTypes.AccountKey.wrap(keccak256("mockdepin-testonly:acct-A"));
    GpuTypes.EconomicEventId ECON_A =
        GpuTypes.EconomicEventId.wrap(keccak256("mockdepin-testonly/acct-A/OBLIGATION/inv-2026-08-A"));
    GpuTypes.EconomicEventId ECON_B =
        GpuTypes.EconomicEventId.wrap(keccak256("mockdepin-testonly/acct-A/OBLIGATION/inv-2026-08-B"));
    uint64 constant HEIGHT = 9_100_000;
    uint64 constant MAX_VALIDITY = 30 days;

    function setUp() public {
        vm.warp(1_800_000_000);
        underwriter = vm.addr(UNDERWRITER_KEY);
        wireJson = vm.readFile("test/fixtures/gpu/attestcoin/wire/synthetic-obligation-v1.json");

        roles = new ProtocolRoles(admin);
        providers = new ProviderRegistry(roles);
        auth = new AuthorizationVerifier(roles, 15 minutes);
        prover = new MockBlockProver();
        vm.startPrank(admin);
        roles.grantRole(roles.REGISTRAR(), registrar);
        roles.grantRole(roles.UNDERWRITER(), underwriter);
        vm.stopPrank();

        vm.startPrank(registrar);
        providers.registerProvider(MOCK, _cfg(MANIFEST, ENV_ID_HASH));
        providers.registerEmitter(
            MOCK, ESCROW, TOPIC, GpuTypes.EvidenceMeaning.OBLIGATION_RECOGNIZED, bytes32(0), address(0)
        );
        vm.stopPrank();

        verifier = _verifier(MOCK, ENV_ID_HASH);
        book = new EvidenceBook(roles, providers, ENV_ID_HASH, MAX_VALIDITY);
        consumer = new TestConsumer(book);
        vm.startPrank(admin);
        book.bindVerifier(MOCK, verifier);
        book.setConsumer(address(consumer), true);
        vm.stopPrank();
    }

    // ------------------------------------------------------------------ helpers

    function _cfg(bytes32 manifest, bytes32 envIdHash) internal pure returns (IProviderRegistry.ProviderConfig memory) {
        return IProviderRegistry.ProviderConfig({
            sourceChain: GpuTypes.SourceChainRef({
                envIdHash: envIdHash, chainKey: CHAIN_KEY, chainId: SEPOLIA, encoding: 1, manifestHash: manifest
            }),
            executionProfile: GpuTypes.ExecutionProfile.LOCAL_MOCK,
            testOnly: true,
            policyVersionId: keccak256("policy-v1"),
            admissionEnabled: true
        });
    }

    function _verifier(GpuTypes.ProviderId pid, bytes32 envIdHash) internal returns (AttestcoinRevenueVerifier) {
        return new AttestcoinRevenueVerifier(
            address(prover),
            providers,
            pid,
            GpuTypes.SourceChainRef({
                envIdHash: envIdHash, chainKey: CHAIN_KEY, chainId: SEPOLIA, encoding: 1, manifestHash: MANIFEST
            }),
            GpuTypes.ExecutionProfile.LOCAL_MOCK,
            AttestcoinRevenueVerifier.Limits({ maxTxBytes: 8192, maxLogs: 16, maxSiblings: 32, maxContinuityRoots: 64 })
        );
    }

    function _fixture(string memory name) internal view returns (bytes memory) {
        return vm.parseJsonBytes(wireJson, string.concat(".cases.", name, ".txBytes"));
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
        e.siblings = new INativeQueryVerifier.MerkleProofEntry[](5);
        for (uint256 i = 0; i < 5; i++) {
            e.siblings[i] = INativeQueryVerifier.MerkleProofEntry({
                hash: keccak256(abi.encode(i)), isLeft: (txIndex >> i) & 1 == 1
            });
        }
        e.lowerEndpointDigest = keccak256("lower");
        e.continuityRoots = new bytes32[](1);
        e.continuityRoots[0] = keccak256("c0");
    }

    function _topics() internal pure returns (bytes32[] memory t) {
        t = new bytes32[](1);
        t[0] = TOPIC;
    }

    function _ins(uint32 ordinal, GpuTypes.EconomicEventId econ)
        internal
        view
        returns (IEvidenceBook.ConsumeInstruction memory)
    {
        return IEvidenceBook.ConsumeInstruction({
            logOrdinal: ordinal,
            economicEventId: econ,
            accountKey: ACCOUNT,
            validUntil: uint64(block.timestamp + 7 days)
        });
    }

    function _both() internal view returns (IEvidenceBook.ConsumeInstruction[] memory ins) {
        ins = new IEvidenceBook.ConsumeInstruction[](2);
        ins[0] = _ins(0, ECON_A);
        ins[1] = _ins(1, ECON_B);
    }

    function _one(uint32 ordinal, GpuTypes.EconomicEventId econ)
        internal
        view
        returns (IEvidenceBook.ConsumeInstruction[] memory ins)
    {
        ins = new IEvidenceBook.ConsumeInstruction[](1);
        ins[0] = _ins(ordinal, econ);
    }

    function _consume(IEvidenceBook.ConsumeInstruction[] memory ins)
        internal
        returns (IEvidenceBook.EvidenceRecord[] memory)
    {
        return consumer.ingest(MOCK, _envelope(_fixture("obligation2Logs"), 17), ESCROW, _topics(), ins);
    }

    function _id(uint32 ordinal) internal view returns (GpuTypes.SourceEventId) {
        return verifier.sourceEventId(HEIGHT, 17, ordinal);
    }

    // ------------------------------------------------------------------ positive

    function test_consume_twoLogsOfOneTx_recordedSeparately() public {
        IEvidenceBook.EvidenceRecord[] memory recs = _consume(_both());
        assertEq(recs.length, 2);
        for (uint32 i = 0; i < 2; i++) {
            assertTrue(book.isConsumed(_id(i)));
            IEvidenceBook.EvidenceRecord memory r = book.record(_id(i));
            assertEq(GpuTypes.SourceEventId.unwrap(r.id), GpuTypes.SourceEventId.unwrap(_id(i)));
            assertEq(uint8(r.meaning), uint8(GpuTypes.EvidenceMeaning.OBLIGATION_RECOGNIZED), "meaning from registry");
            assertEq(uint8(r.method), uint8(GpuTypes.VerificationMethod.LOCAL_MOCK), "mock verification is labeled");
            assertEq(uint8(r.trust), uint8(GpuTypes.Trust.PROVEN));
            assertEq(r.consumer, address(consumer));
            assertEq(r.manifestHash, MANIFEST);
            assertEq(r.provenAt, uint64(block.timestamp));
            assertEq(r.locator.height, HEIGHT);
            assertEq(r.locator.txIndex, 17);
            assertEq(r.locator.logOrdinal, i);
            assertEq(r.emitter, ESCROW);
            assertEq(r.topic0, TOPIC);
            assertEq(GpuTypes.ProviderId.unwrap(r.providerId), GpuTypes.ProviderId.unwrap(MOCK));
        }
        assertTrue(book.economicEventSeen(ECON_A));
        assertTrue(book.economicEventSeen(ECON_B));
        assertEq(GpuTypes.SourceEventId.unwrap(book.firstSourceEventOf(ECON_B)), GpuTypes.SourceEventId.unwrap(_id(1)));
        assertEq(consumer.applied(), 2);
    }

    function test_consume_emitsEvents() public {
        vm.expectEmit(true, true, true, true, address(book));
        emit IEvidenceBook.EconomicEventFirstSeen(ECON_A, _id(0));
        vm.expectEmit(true, true, true, true, address(book));
        emit IEvidenceBook.SourceEventConsumed(
            _id(0), ECON_A, address(consumer), GpuTypes.EvidenceMeaning.OBLIGATION_RECOGNIZED, MANIFEST
        );
        _consume(_one(0, ECON_A));
    }

    function test_consume_eachLogSeparately_thenSecondConsumptionOfSameLogRejected() public {
        _consume(_one(0, ECON_A));
        assertTrue(book.isConsumed(_id(0)));
        assertFalse(book.isConsumed(_id(1)));
        // the other log of the same tx is still consumable with a fresh submission
        _consume(_one(1, ECON_B));
        assertTrue(book.isConsumed(_id(1)));
        // same log again, even with a different economic id: rejected
        vm.expectRevert(abi.encodeWithSelector(IEvidenceBook.AlreadyConsumed.selector, _id(0)));
        _consume(_one(0, GpuTypes.EconomicEventId.wrap(keccak256("other-econ"))));
    }

    function test_consume_dataHashBindsVerifiedLogContent() public {
        IEvidenceBook.EvidenceRecord[] memory recs = _consume(_one(1, ECON_B));
        // the second log carries inv-B / 9,000 USDC (fixture); the record binds the verified topics+data
        assertTrue(recs[0].dataHash != bytes32(0));
        vm.prank(address(consumer));
        GpuTypes.VerifiedSourceEvent[] memory ev =
            verifier.verifyAndExtract(_envelope(_fixture("obligation2Logs"), 17), ESCROW, _topics());
        assertEq(recs[0].dataHash, keccak256(abi.encode(ev[1].topics, ev[1].data)));
    }

    // ------------------------------------------------------------------ nothing but native output creates records

    function test_nativeFailure_recordsNothing() public {
        prover.setResult(false);
        vm.expectRevert(abi.encodeWithSelector(IRevenueVerifier.NativeVerificationFailed.selector, abi.encode(false)));
        _consume(_both());
        assertFalse(book.isConsumed(_id(0)));
        assertFalse(book.economicEventSeen(ECON_A));
    }

    function test_nativeMissing_verifierNotBound() public {
        GpuTypes.ProviderId other = GpuTypes.ProviderId.wrap(keccak256("other"));
        vm.expectRevert(abi.encodeWithSelector(IEvidenceBook.VerifierNotBound.selector, other));
        consumer.ingest(other, _envelope(_fixture("obligation2Logs"), 17), ESCROW, _topics(), _both());
    }

    function test_auxiliarySignature_hasNoPathIntoTheBook() public {
        // A perfectly valid underwriter CREDIT_APPROVAL assertion exists and verifies…
        bytes32 subject = keccak256("facility-1-decision");
        GpuTypes.SupplementaryAssertion memory a = GpuTypes.SupplementaryAssertion({
            purpose: GpuTypes.AssertionPurpose.CREDIT_APPROVAL,
            subject: subject,
            signer: underwriter,
            keyEpoch: 0,
            nonce: 1,
            issuedAt: uint64(block.timestamp),
            expiresAt: uint64(block.timestamp + 10 minutes),
            signature: ""
        });
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(UNDERWRITER_KEY, auth.hashAssertion(a));
        a.signature = abi.encodePacked(r, s, v);
        assertTrue(auth.isValid(a, GpuTypes.AssertionPurpose.CREDIT_APPROVAL, subject));
        auth.verifyAndConsume(a, GpuTypes.AssertionPurpose.CREDIT_APPROVAL, subject);
        // …and it changes nothing in the evidence book; with native = false the book still records nothing.
        prover.setResult(false);
        vm.expectRevert();
        _consume(_both());
        assertFalse(book.isConsumed(_id(0)));
        assertFalse(book.economicEventSeen(ECON_A));
    }

    function test_adminCannotRegisterEvidenceDirectly() public {
        // The only mutating entry points besides consume are wiring; none takes an event or an id.
        vm.startPrank(admin);
        (bool ok,) = address(book)
            .call(
                abi.encodeWithSignature(
                    "recordEvent(bytes32,bytes32)", GpuTypes.SourceEventId.unwrap(_id(0)), bytes32(0)
                )
            );
        vm.stopPrank();
        assertFalse(ok);
        assertFalse(book.isConsumed(_id(0)));
    }

    // ------------------------------------------------------------------ consumer rights / front-run

    function test_nonConsumerRejected_andPublicVerifyDoesNotPreempt() public {
        // mallory verifies publicly through the verifier (stateless) …
        vm.prank(mallory);
        verifier.verifyAndExtract(_envelope(_fixture("obligation2Logs"), 17), ESCROW, _topics());
        // … and cannot consume
        vm.prank(mallory);
        vm.expectRevert(abi.encodeWithSelector(IEvidenceBook.ConsumerNotAllowed.selector, mallory));
        book.consume(MOCK, _envelope(_fixture("obligation2Logs"), 17), ESCROW, _topics(), _both());
        // the legitimate consumer still consumes both logs afterwards
        IEvidenceBook.EvidenceRecord[] memory recs = _consume(_both());
        assertEq(recs.length, 2);
    }

    function test_consumerRevoked_cannotConsume() public {
        vm.prank(admin);
        book.setConsumer(address(consumer), false);
        vm.expectRevert(abi.encodeWithSelector(IEvidenceBook.ConsumerNotAllowed.selector, address(consumer)));
        _consume(_both());
    }

    function test_onlyAdminWires() public {
        vm.startPrank(mallory);
        vm.expectRevert(abi.encodeWithSelector(EvidenceBook.NotAdmin.selector, mallory));
        book.setConsumer(mallory, true);
        vm.expectRevert(abi.encodeWithSelector(EvidenceBook.NotAdmin.selector, mallory));
        book.bindVerifier(MOCK, verifier);
        vm.expectRevert(abi.encodeWithSelector(EvidenceBook.NotAdmin.selector, mallory));
        book.setSelfAssertedEmitter(MOCK, ESCROW, true);
        vm.stopPrank();
    }

    // ------------------------------------------------------------------ atomicity with business effect

    function test_businessRevert_rollsBackConsumption_thenRetrySucceeds() public {
        consumer.setFail(true);
        vm.expectRevert(bytes("business rule failed"));
        _consume(_both());
        assertFalse(book.isConsumed(_id(0)));
        assertFalse(book.isConsumed(_id(1)));
        assertFalse(book.economicEventSeen(ECON_A));
        consumer.setFail(false);
        _consume(_both());
        assertTrue(book.isConsumed(_id(0)));
        assertTrue(book.isConsumed(_id(1)));
        assertEq(consumer.applied(), 2);
    }

    // ------------------------------------------------------------------ economic dedup / instructions

    function test_sameEconomicEvent_fromAnotherLog_rejected() public {
        _consume(_one(0, ECON_A));
        vm.expectRevert(abi.encodeWithSelector(IEvidenceBook.EconomicEventAlreadyRecorded.selector, ECON_A, _id(0)));
        _consume(_one(1, ECON_A));
        assertFalse(book.isConsumed(_id(1)));
    }

    function test_instruction_unknownOrdinal_duplicateOrdinal_tooMany() public {
        vm.expectRevert(abi.encodeWithSelector(IEvidenceBook.UnknownLogOrdinal.selector, uint32(5)));
        _consume(_one(5, ECON_A));

        IEvidenceBook.ConsumeInstruction[] memory dup = new IEvidenceBook.ConsumeInstruction[](2);
        dup[0] = _ins(0, ECON_A);
        dup[1] = _ins(0, ECON_B);
        vm.expectRevert(abi.encodeWithSelector(IEvidenceBook.InvalidInstruction.selector, "duplicate logOrdinal"));
        _consume(dup);

        IEvidenceBook.ConsumeInstruction[] memory three = new IEvidenceBook.ConsumeInstruction[](3);
        three[0] = _ins(0, ECON_A);
        three[1] = _ins(1, ECON_B);
        three[2] = _ins(2, GpuTypes.EconomicEventId.wrap(keccak256("c")));
        vm.expectRevert(abi.encodeWithSelector(IEvidenceBook.InstructionMismatch.selector, 2, 3));
        _consume(three);

        vm.expectRevert(abi.encodeWithSelector(IEvidenceBook.InstructionMismatch.selector, 2, 0));
        _consume(new IEvidenceBook.ConsumeInstruction[](0));
    }

    function test_instruction_accountKeyMustMatchVerifiedTopic() public {
        IEvidenceBook.ConsumeInstruction[] memory ins = _one(0, ECON_A);
        ins[0].accountKey = GpuTypes.AccountKey.wrap(keccak256("mockdepin-testonly:acct-B"));
        vm.expectRevert(abi.encodeWithSelector(IEvidenceBook.InvalidInstruction.selector, "accountKey != topics[1]"));
        _consume(ins);
    }

    function test_instruction_validity_staleOrBeyondPolicy() public {
        IEvidenceBook.ConsumeInstruction[] memory ins = _one(0, ECON_A);
        ins[0].validUntil = uint64(block.timestamp);
        vm.expectRevert(abi.encodeWithSelector(IEvidenceBook.StaleVerification.selector, _id(0)));
        _consume(ins);
        ins[0].validUntil = uint64(block.timestamp + MAX_VALIDITY + 1);
        vm.expectRevert(abi.encodeWithSelector(IEvidenceBook.InvalidInstruction.selector, "validUntil beyond policy"));
        _consume(ins);
        ins[0].validUntil = uint64(block.timestamp + MAX_VALIDITY);
        _consume(ins);
        assertEq(book.record(_id(0)).validUntil, uint64(block.timestamp + MAX_VALIDITY));
    }

    function test_reverseRevision_bothLogsRecordable_positionPreserved() public {
        // The book records proof-bound positions; revision ordering is a receivable-level rule (GPU-035/081).
        // Consuming ordinal 1 before ordinal 0 leaves both locators intact for the consumer to order.
        _consume(_one(1, ECON_B));
        _consume(_one(0, ECON_A));
        assertEq(book.record(_id(1)).locator.logOrdinal, 1);
        assertEq(book.record(_id(0)).locator.logOrdinal, 0);
    }

    // ------------------------------------------------------------------ other account / chain / provider

    function test_verifierForAnotherEnvironment_cannotBeBound() public {
        bytes32 otherEnv = keccak256("cc3-mainnet");
        GpuTypes.ProviderId pid = GpuTypes.ProviderId.wrap(keccak256("mainnet-provider"));
        vm.prank(registrar);
        providers.registerProvider(pid, _cfg(MANIFEST, otherEnv));
        AttestcoinRevenueVerifier v2 = _verifier(pid, otherEnv);
        vm.prank(admin);
        vm.expectRevert(abi.encodeWithSelector(IEvidenceBook.VerifierEnvMismatch.selector, ENV_ID_HASH, otherEnv));
        book.bindVerifier(pid, v2);
    }

    function test_verifierBoundUnderWrongProvider_rejected() public {
        GpuTypes.ProviderId pid = GpuTypes.ProviderId.wrap(keccak256("second-provider"));
        vm.prank(registrar);
        providers.registerProvider(pid, _cfg(MANIFEST, ENV_ID_HASH));
        AttestcoinRevenueVerifier v2 = _verifier(pid, ENV_ID_HASH);
        vm.prank(admin);
        vm.expectRevert(EvidenceBook.InvalidVerifierBinding.selector);
        book.bindVerifier(MOCK, v2); // reject misconfiguration at binding, before evidence can be consumed
        assertEq(address(book.verifierOf(MOCK)), address(verifier));
    }

    function test_wrongChainKey_rejectedByVerifier_nothingRecorded() public {
        GpuTypes.NativeProofEnvelope memory e = _envelope(_fixture("obligation2Logs"), 17);
        e.chainKey = 3;
        vm.expectRevert(abi.encodeWithSelector(IRevenueVerifier.ChainKeyMismatch.selector, CHAIN_KEY, uint64(3)));
        consumer.ingest(MOCK, e, ESCROW, _topics(), _both());
        assertFalse(book.isConsumed(_id(0)));
    }

    // ------------------------------------------------------------------ verifier replacement replay

    function test_verifierReplacement_replayOfConsumedLogRejected() public {
        _consume(_both());
        AttestcoinRevenueVerifier v2 = _verifier(MOCK, ENV_ID_HASH); // new deployment, same provider/env
        vm.prank(admin);
        book.bindVerifier(MOCK, v2);
        assertEq(address(book.verifierOf(MOCK)), address(v2));
        vm.expectRevert(abi.encodeWithSelector(IEvidenceBook.AlreadyConsumed.selector, _id(0)));
        _consume(_one(0, GpuTypes.EconomicEventId.wrap(keccak256("new-econ-after-upgrade"))));
        // and a different economic id for the same log does not create a second economic event
        assertFalse(book.economicEventSeen(GpuTypes.EconomicEventId.wrap(keccak256("new-econ-after-upgrade"))));
    }

    // ------------------------------------------------------------------ self-asserted emitters

    function test_selfAssertedEmitter_staysOffchainAssertion() public {
        vm.prank(admin);
        book.setSelfAssertedEmitter(MOCK, ESCROW, true);
        IEvidenceBook.EvidenceRecord[] memory recs = _consume(_one(0, ECON_A));
        assertEq(uint8(recs[0].method), uint8(GpuTypes.VerificationMethod.OFFCHAIN_ASSERTION));
        assertEq(uint8(recs[0].trust), uint8(GpuTypes.Trust.ASSERTED));
        assertTrue(book.isConsumed(_id(0)), "still consumed once, still not GPU revenue");
    }
}
