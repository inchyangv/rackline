// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import { Test } from "forge-std/Test.sol";
import { INativeQueryVerifier } from "@gluwa/asc-contracts/contracts/write-ability/common/INativeQueryVerifier.sol";
import { GpuTypes } from "../../contracts/gpu/types/GpuTypes.sol";
import { ProtocolRoles } from "../../contracts/gpu/ProtocolRoles.sol";
import { ProviderRegistry } from "../../contracts/gpu/ProviderRegistry.sol";
import { AccountRegistry } from "../../contracts/gpu/AccountRegistry.sol";
import { AuthorizationVerifier } from "../../contracts/gpu/AuthorizationVerifier.sol";
import { EvidenceBook } from "../../contracts/gpu/EvidenceBook.sol";
import { AttestcoinRevenueVerifier } from "../../contracts/gpu/AttestcoinRevenueVerifier.sol";
import { MockBlockProver } from "../../contracts/gpu/mocks/MockBlockProver.sol";
import { DebtLedger } from "../../contracts/gpu/DebtLedger.sol";
import { ControlRegistry } from "../../contracts/gpu/ControlRegistry.sol";
import { GpuRiskPolicy } from "../../contracts/gpu/GpuRiskPolicy.sol";
import { ReceivableBook } from "../../contracts/gpu/ReceivableBook.sol";
import { ExposureController } from "../../contracts/gpu/ExposureController.sol";
import { IProviderRegistry } from "../../contracts/gpu/interfaces/IProviderRegistry.sol";
import { IDebtLedger } from "../../contracts/gpu/interfaces/IDebtLedger.sol";
import { IRiskPolicy } from "../../contracts/gpu/interfaces/IRiskPolicy.sol";
import { IReceivableBook } from "../../contracts/gpu/interfaces/IReceivableBook.sol";
import { IExposureController, IVaultCashView } from "../../contracts/gpu/interfaces/IExposureController.sol";
import { IEvidenceBook } from "../../contracts/gpu/interfaces/IEvidenceBook.sol";

/// @dev Vault cash view double (GPU-034 implements the real one).
contract MockVaultCash is IVaultCashView {
    uint256 public availableCash = 1_000_000e6;

    function set(uint256 c) external {
        availableCash = c;
    }
}

/**
 * @title GPU035RiskTest
 * @notice ReceivableBook (proof-driven receivables + checkpoint gate), GpuRiskPolicy (versions, caps) and
 *         ExposureController (headroom, reservations, atomic consume). LOCAL_MOCK verification only: the BlockProver
 *         is a test double and txBytes are SYNTHETIC (same encoder layout as the pinned SDK, asserted against the
 *         committed fixture). G-ASC is GPU-080.
 */
contract GPU035RiskTest is Test {
    // ------------------------------------------------------------------ actors
    address admin = address(0xAD);
    address registrar = address(0x4E6);
    address underwriter = address(0x0DE);
    address guardian = address(0x6A);
    address servicer = address(0x5E);
    address relayer = address(0x4E);
    address manager = address(0x3A);
    address mallory = address(0xBAD);

    // ------------------------------------------------------------------ system
    ProtocolRoles roles;
    ProviderRegistry providers;
    AuthorizationVerifier auth;
    AccountRegistry accounts;
    MockBlockProver prover;
    AttestcoinRevenueVerifier verifier;
    EvidenceBook evidence;
    DebtLedger ledger;
    ControlRegistry control;
    GpuRiskPolicy policy;
    MockVaultCash vault;
    ReceivableBook book;
    ExposureController ctl;

    string wireJson;

    // ------------------------------------------------------------------ constants (fixture-aligned)
    bytes32 constant MANIFEST = 0x2b0162d0c206f421138269a721c6338d8cf294d67dc644bb8b35ebb9bfbff6bb;
    bytes32 constant ENV_ID_HASH = keccak256("cc3-testnet");
    uint64 constant CHAIN_KEY = 1;
    uint64 constant SEPOLIA = 11_155_111;
    GpuTypes.ProviderId MOCK = GpuTypes.ProviderId.wrap(keccak256("mockdepin-testonly"));
    address constant ESCROW = address(0xE1);
    address constant ISSUER = address(0x155);
    address constant PAYER = address(0xFA);
    address constant USDC = address(0x05DC);
    address constant OTHER_TOKEN = address(0x07EA);
    bytes32 constant REF_A = keccak256("inv-2026-08-A");
    bytes32 constant REF_B = keccak256("inv-2026-08-B");
    GpuTypes.AccountKey ACCOUNT_A = GpuTypes.AccountKey.wrap(keccak256("mockdepin-testonly:acct-A"));
    GpuTypes.AccountKey ACCOUNT_B = GpuTypes.AccountKey.wrap(keccak256("mockdepin-testonly:acct-B"));
    bytes32 constant BORROWER_A = keccak256("borrower-A");
    bytes32 constant BORROWER_B = keccak256("borrower-B");
    bytes32 constant GROUP_A = keccak256("group-A");
    GpuTypes.FacilityId FA = GpuTypes.FacilityId.wrap(keccak256("facility-A"));
    GpuTypes.FacilityId FB = GpuTypes.FacilityId.wrap(keccak256("facility-B"));
    GpuTypes.FacilityId FC = GpuTypes.FacilityId.wrap(keccak256("facility-C"));
    bytes32 constant AGR_A = keccak256("agreement-A");
    bytes32 constant AGR_B = keccak256("agreement-B");
    bytes32 constant POLICY_V1 = keccak256("policy-v1");
    bytes32 constant POLICY_V2 = keccak256("policy-v2");
    uint64 constant HEIGHT = 9_100_000;
    uint64 constant DUE_AT = 1_761_868_800;
    uint64 constant T0 = 1_750_000_000; // before DUE_AT (2025-10-31): baseline receivables are not overdue

    bytes32 constant T_RECOGNIZED =
        keccak256("ObligationRecognizedV2(bytes32,bytes32,address,address,address,address,uint256,uint64,uint32)");
    bytes32 constant T_ASSIGNED = keccak256("ObligationAssigned(bytes32,bytes32,bytes32,uint32)");
    bytes32 constant T_CORRECTED = keccak256("ObligationCorrected(bytes32,bytes32,int256,uint32,uint8)");
    bytes32 constant T_PAYOUT = keccak256("PayoutReceived(bytes32,bytes32,address,address,uint256,uint64)");
    bytes32 constant T_CANCELLED = keccak256("PayoutCancelled(bytes32,bytes32,uint64,uint256)");
    bytes32 constant T_CHECKPOINT =
        keccak256("SourceCheckpointV2(bytes32,uint64,uint32,uint256,uint256,uint64,uint64)");

    struct Log {
        address addr;
        bytes32[] topics;
        bytes data;
    }

    struct AccessListEntry {
        address account;
        bytes32[] storageKeys;
    }

    uint64 nextHeight = HEIGHT + 1;

    // ================================================================== setup

    function setUp() public {
        vm.warp(T0);
        wireJson = vm.readFile("test/fixtures/gpu/attestcoin/wire/synthetic-obligation-v1.json");

        roles = new ProtocolRoles(admin);
        providers = new ProviderRegistry(roles);
        auth = new AuthorizationVerifier(roles, 15 minutes);
        accounts = new AccountRegistry(roles, auth, providers);
        prover = new MockBlockProver();
        vm.startPrank(admin);
        roles.grantRole(roles.REGISTRAR(), registrar);
        roles.grantRole(roles.UNDERWRITER(), underwriter);
        roles.grantRole(roles.GUARDIAN(), guardian);
        roles.grantRole(roles.SERVICER(), servicer);
        roles.grantRole(roles.RELAYER(), relayer);
        vm.stopPrank();

        _registerProvider();
        verifier = new AttestcoinRevenueVerifier(
            address(prover),
            providers,
            MOCK,
            _sourceRef(),
            GpuTypes.ExecutionProfile.LOCAL_MOCK,
            AttestcoinRevenueVerifier.Limits({
                maxTxBytes: 16_384, maxLogs: 16, maxSiblings: 32, maxContinuityRoots: 64
            })
        );
        evidence = new EvidenceBook(roles, providers, ENV_ID_HASH, 30 days);
        ledger = new DebtLedger(roles);
        control = new ControlRegistry(roles, accounts, ledger, 1 days);
        policy = new GpuRiskPolicy(roles);
        vault = new MockVaultCash();
        book = new ReceivableBook(roles, evidence, providers, accounts);
        ctl = new ExposureController(roles, book, ledger, control, policy, vault);

        vm.startPrank(admin);
        evidence.bindVerifier(MOCK, verifier);
        evidence.setConsumer(address(book), true);
        ledger.setWriter(manager, true);
        ledger.setWriter(address(ctl), true);
        ctl.setManager(manager, true);
        vm.stopPrank();

        vm.startPrank(registrar);
        accounts.linkAccount(BORROWER_A, MOCK, ACCOUNT_A);
        accounts.linkAccount(BORROWER_B, MOCK, ACCOUNT_B);
        vm.stopPrank();

        _publishPolicy(POLICY_V1, 10_000e6, 10_000e6, 20_000e6, 20_000e6);
        _openLedger(FA, 0);
        _openLedger(FB, 0);
        _agreement(AGR_A, BORROWER_A, ACCOUNT_A);
        _agreement(AGR_B, BORROWER_B, ACCOUNT_B);

        vm.startPrank(underwriter);
        book.registerFacility(FA, BORROWER_A, MOCK, _usdc());
        book.registerFacility(FB, BORROWER_A, MOCK, _usdc());
        ctl.enrollFacility(FA, GROUP_A);
        ctl.enrollFacility(FB, GROUP_A);
        ctl.setAuthorization(FA, 50_000e6, POLICY_V1, AGR_A, 1, T0 + 30 days);
        ctl.setAuthorization(FB, 50_000e6, POLICY_V1, AGR_A, 1, T0 + 30 days);
        vm.stopPrank();
    }

    function _registerProvider() internal {
        vm.startPrank(registrar);
        providers.registerProvider(
            MOCK,
            IProviderRegistry.ProviderConfig({
                sourceChain: _sourceRef(),
                executionProfile: GpuTypes.ExecutionProfile.LOCAL_MOCK,
                testOnly: true,
                policyVersionId: POLICY_V1,
                admissionEnabled: true
            })
        );
        providers.registerEmitter(
            MOCK, ESCROW, T_RECOGNIZED, GpuTypes.EvidenceMeaning.OBLIGATION_RECOGNIZED, 0, address(0)
        );
        providers.registerEmitter(
            MOCK, ESCROW, T_ASSIGNED, GpuTypes.EvidenceMeaning.ASSIGNMENT_RECOGNIZED, 0, address(0)
        );
        providers.registerEmitter(MOCK, ESCROW, T_CORRECTED, GpuTypes.EvidenceMeaning.CORRECTION, 0, address(0));
        providers.registerEmitter(MOCK, ESCROW, T_PAYOUT, GpuTypes.EvidenceMeaning.PAYOUT, 0, address(0));
        providers.registerEmitter(MOCK, ESCROW, T_CANCELLED, GpuTypes.EvidenceMeaning.PAYMENT_CANCELLED, 0, address(0));
        // EvidenceMeaning has no CHECKPOINT member (GPU-029 enum); the book keys checkpoints on topic0 and ignores
        // the registered meaning for them. Registered here as CORRECTION only to satisfy emitter registration.
        providers.registerEmitter(MOCK, ESCROW, T_CHECKPOINT, GpuTypes.EvidenceMeaning.CORRECTION, 0, address(0));
        providers.setIssuer(MOCK, ISSUER, true);
        providers.admitToken(MOCK, SEPOLIA, USDC, 6);
        vm.stopPrank();
    }

    function _sourceRef() internal pure returns (GpuTypes.SourceChainRef memory) {
        return GpuTypes.SourceChainRef({
            envIdHash: ENV_ID_HASH, chainKey: CHAIN_KEY, chainId: SEPOLIA, encoding: 1, manifestHash: MANIFEST
        });
    }

    function _usdc() internal pure returns (GpuTypes.AssetRef memory) {
        return GpuTypes.AssetRef({ chainId: SEPOLIA, token: USDC, decimals: 6 });
    }

    function _publishPolicy(bytes32 id, uint256 perBorrower, uint256 perGroup, uint256 perProvider, uint256 global)
        internal
    {
        vm.prank(underwriter);
        policy.publish(
            id,
            IRiskPolicy.Params({
                advanceRateBps: 5000,
                overdueHaircutBps: 500,
                concentrationHaircutBps: 0,
                collectabilityHaircutBps: 0,
                evidenceValidityWindow: 30 days,
                checkpointMaxAge: 7 days,
                controlObservationMaxAge: 1 days,
                decisionValidity: 30 days,
                maxTenor: 90 days,
                reserveBps: 0,
                dscrMinBps: 0,
                perBorrowerCap: perBorrower,
                perGroupCap: perGroup,
                perProviderCap: perProvider,
                globalCap: global,
                testOnly: true
            }),
            0
        );
    }

    function _openLedger(GpuTypes.FacilityId f, uint64 maturity) internal {
        vm.prank(manager);
        ledger.open(
            f,
            IDebtLedger.Terms({
                loanAsset: GpuTypes.AssetRef({ chainId: 102_031, token: address(0x10A4), decimals: 6 }),
                rateBps: 1000,
                maturityAt: maturity,
                termsVersionId: keccak256("terms-v1"),
                policyVersionId: POLICY_V1,
                executionProfile: GpuTypes.ExecutionProfile.LOCAL_MOCK,
                capitalizeUnpaidInterest: false
            })
        );
    }

    function _agreement(bytes32 id, bytes32 borrower, GpuTypes.AccountKey acct) internal {
        vm.prank(underwriter);
        control.createAgreement(
            id,
            borrower,
            acct,
            GpuTypes.ControlGrade.E2,
            ESCROW,
            SEPOLIA,
            keccak256("agreement"),
            T0,
            0,
            keccak256("poc")
        );
        vm.prank(servicer);
        control.observe(id, GpuTypes.ControlGrade.E2, ESCROW);
    }

    // ================================================================== official (uint8, bytes[]) encoder replica

    function _txBytes(uint8 status, Log[] memory logs) internal pure returns (bytes memory) {
        bytes[] memory chunks = new bytes[](3);
        chunks[0] = abi.encode(uint64(7), uint64(210_000), ISSUER, false, ESCROW, uint256(0), hex"1234abcd");
        chunks[1] = abi.encode(
            uint64(SEPOLIA),
            uint128(1_500_000_000),
            uint128(30_000_000_000),
            new AccessListEntry[](0),
            uint8(1),
            bytes32(0x1111111111111111111111111111111111111111111111111111111111111111),
            bytes32(0x2222222222222222222222222222222222222222222222222222222222222222)
        );
        chunks[2] = abi.encode(status, uint64(123_456), logs, new bytes(256));
        return abi.encode(uint8(2), chunks);
    }

    function _obligationLog(bytes32 ref, uint256 amount, uint32 rev) internal pure returns (Log memory l) {
        l.addr = ESCROW;
        l.topics = new bytes32[](4);
        l.topics[0] = T_RECOGNIZED;
        l.topics[1] = GpuTypes.AccountKey.unwrap(GpuTypes.AccountKey.wrap(keccak256("mockdepin-testonly:acct-A")));
        l.topics[2] = ref;
        l.topics[3] = bytes32(uint256(uint160(ISSUER)));
        l.data = abi.encode(PAYER, ESCROW, USDC, amount, DUE_AT, rev);
    }

    function _log(bytes32 topic0, GpuTypes.AccountKey acct, bytes32 t2, bytes32 t3, uint256 n, bytes memory data)
        internal
        pure
        returns (Log memory l)
    {
        l.addr = ESCROW;
        l.topics = new bytes32[](n);
        l.topics[0] = topic0;
        l.topics[1] = GpuTypes.AccountKey.unwrap(acct);
        if (n > 2) l.topics[2] = t2;
        if (n > 3) l.topics[3] = t3;
        l.data = data;
    }

    function _single(IReceivableBook.ReceivableClaim memory c)
        internal
        pure
        returns (IReceivableBook.ReceivableClaim[] memory cs)
    {
        cs = new IReceivableBook.ReceivableClaim[](1);
        cs[0] = c;
    }

    function _one(Log memory l) internal pure returns (Log[] memory ls) {
        ls = new Log[](1);
        ls[0] = l;
    }

    // ================================================================== proof envelope + ingestion helpers

    function _envelope(bytes memory txBytes, uint64 height, uint64 txIndex)
        internal
        pure
        returns (GpuTypes.NativeProofEnvelope memory e)
    {
        e.chainKey = CHAIN_KEY;
        e.height = height;
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

    function _topics(bytes32 t) internal pure returns (bytes32[] memory ts) {
        ts = new bytes32[](1);
        ts[0] = t;
    }

    function _claim(uint32 ordinal, GpuTypes.AccountKey acct, bytes32 t2, bytes32 t3, bytes memory data)
        internal
        view
        returns (IReceivableBook.ReceivableClaim memory)
    {
        return IReceivableBook.ReceivableClaim({
            logOrdinal: ordinal,
            accountKey: acct,
            topic2: t2,
            topic3: t3,
            data: data,
            validUntil: uint64(block.timestamp + 7 days)
        });
    }

    function _ingestOne(bytes32 topic0, Log memory l, IReceivableBook.ReceivableClaim memory c) internal {
        _ingestOneRev(topic0, l, c, "");
    }

    /// @dev `revertData` non-empty ⇒ expect that revert (set after the prank so the prank is not consumed).
    function _ingestOneRev(
        bytes32 topic0,
        Log memory l,
        IReceivableBook.ReceivableClaim memory c,
        bytes memory revertData
    ) internal {
        IReceivableBook.ReceivableClaim[] memory cs = new IReceivableBook.ReceivableClaim[](1);
        cs[0] = c;
        GpuTypes.NativeProofEnvelope memory env = _envelope(_txBytes(1, _one(l)), nextHeight++, 0);
        bytes32[] memory ts = _topics(topic0);
        vm.prank(relayer);
        if (revertData.length != 0) vm.expectRevert(revertData);
        book.ingest(MOCK, env, ESCROW, ts, cs);
    }

    /// @dev Recognize inv-A (12,000) and inv-B (9,000) for account A from the committed fixture bytes.
    function _recognizeFixture() internal {
        bytes memory txBytes = _fixtureTxBytes();
        IReceivableBook.ReceivableClaim[] memory cs = new IReceivableBook.ReceivableClaim[](2);
        cs[0] = _claim(
            0,
            ACCOUNT_A,
            REF_A,
            bytes32(uint256(uint160(ISSUER))),
            abi.encode(PAYER, ESCROW, USDC, 12_000e6, DUE_AT, uint32(1))
        );
        cs[1] = _claim(
            1,
            ACCOUNT_A,
            REF_B,
            bytes32(uint256(uint160(ISSUER))),
            abi.encode(PAYER, ESCROW, USDC, 9000e6, DUE_AT, uint32(1))
        );
        vm.prank(relayer);
        book.ingest(MOCK, _envelope(txBytes, HEIGHT, 17), ESCROW, _topics(T_RECOGNIZED), cs);
    }

    function _fixtureTxBytes() internal view returns (bytes memory) {
        Log[] memory logs = new Log[](2);
        logs[0] = _obligationLog(REF_A, 12_000e6, 1);
        logs[1] = _obligationLog(REF_B, 9000e6, 1);
        return _txBytes(1, logs);
    }

    function _assign(bytes32 ref, GpuTypes.FacilityId f, uint32 rev) internal {
        _assignRev(ref, f, rev, "");
    }

    function _assignRev(bytes32 ref, GpuTypes.FacilityId f, uint32 rev, bytes memory revertData) internal {
        bytes32 fk = book.facilityKey(f);
        bytes memory data = abi.encode(rev);
        _ingestOneRev(
            T_ASSIGNED, _log(T_ASSIGNED, ACCOUNT_A, ref, fk, 4, data), _claim(0, ACCOUNT_A, ref, fk, data), revertData
        );
    }

    function _checkpoint(GpuTypes.AccountKey acct, uint64 seq, uint32 latestRev, uint256 open, uint256 paidCum)
        internal
    {
        bytes memory data = abi.encode(
            seq, latestRev, open, paidCum, uint64(block.timestamp), uint64(block.timestamp + 15 minutes)
        );
        _ingestOne(T_CHECKPOINT, _log(T_CHECKPOINT, acct, 0, 0, 2, data), _claim(0, acct, 0, 0, data));
    }

    function _correct(bytes32 ref, int256 delta, uint32 rev, uint8 reason) internal {
        bytes memory data = abi.encode(delta, rev, reason);
        _ingestOne(T_CORRECTED, _log(T_CORRECTED, ACCOUNT_A, ref, 0, 3, data), _claim(0, ACCOUNT_A, ref, 0, data));
    }

    function _payout(bytes32 ref, address token, uint256 amount, uint64 seq) internal {
        _payoutRev(ref, token, amount, seq, "");
    }

    function _payoutRev(bytes32 ref, address token, uint256 amount, uint64 seq, bytes memory revertData) internal {
        bytes32 t3 = bytes32(uint256(uint160(token)));
        bytes memory data = abi.encode(PAYER, amount, seq);
        _ingestOneRev(
            T_PAYOUT, _log(T_PAYOUT, ACCOUNT_A, ref, t3, 4, data), _claim(0, ACCOUNT_A, ref, t3, data), revertData
        );
    }

    /// @dev inv-A recognized, assigned to FA, account checkpoint published (rev counter = 1 + 1 + 1 = 3).
    function _baseA() internal {
        _recognizeFixture();
        _assign(REF_A, FA, 2);
        _checkpoint(ACCOUNT_A, 1, 3, 21_000e6, 0);
    }

    /// @dev A new checkpoint refreshes the account; proof validity is refreshed only by a new obligation-defining
    ///      event — here a +0 correction at the next revision (revision 3), then checkpoint seq 2 / rev 4.
    function _assignRefresh() internal {
        _correct(REF_A, 0, 3, 4);
        _checkpoint(ACCOUNT_A, 2, 4, 21_000e6, 0);
    }

    function _idA() internal view returns (bytes32) {
        return book.receivableId(MOCK, ACCOUNT_A, REF_A);
    }

    function _ev(GpuTypes.FacilityId f) internal view returns (GpuTypes.DrawEvaluation memory) {
        return ctl.evaluateDraw(f);
    }

    // ================================================================== encoder parity

    function test_encoderReproducesCommittedFixtureBytes() public view {
        Log[] memory logs = new Log[](2);
        logs[0] = _obligationLog(REF_A, 12_000e6, 1);
        logs[1] = _obligationLog(REF_B, 9000e6, 1);
        // The pinned SDK v1 fixture remains immutable. v2 business events use the same official wire encoder.
        logs[0].topics[0] =
            keccak256("ObligationRecognized(bytes32,bytes32,address,address,address,uint256,uint64,uint32)");
        logs[1].topics[0] = logs[0].topics[0];
        logs[0].data = abi.encode(PAYER, ESCROW, 12_000e6, DUE_AT, uint32(1));
        logs[1].data = abi.encode(PAYER, ESCROW, 9000e6, DUE_AT, uint32(1));
        bytes memory expected = vm.parseJsonBytes(wireJson, ".cases.obligation2Logs.txBytes");
        assertEq(_txBytes(1, logs), expected, "Solidity replica of the SDK V1 encoder must match the fixture");
        assertEq(_txBytes(0, _one(logs[0])), vm.parseJsonBytes(wireJson, ".cases.receiptFailed.txBytes"));
    }

    // ================================================================== GPU-035.a receivables + checkpoint gate

    function test_base_requiresAssignmentAndFreshCheckpoint() public {
        _recognizeFixture();
        (uint256 e0,,) = book.eligibleUnpaid(FA, 7 days, 0, 500, uint64(block.timestamp));
        assertEq(e0, 0, "recognized but unassigned: nothing");
        _assign(REF_A, FA, 2);
        (uint256 e1,,) = book.eligibleUnpaid(FA, 7 days, 0, 500, uint64(block.timestamp));
        assertEq(e1, 0, "assigned but no checkpoint: nothing (R2-D06)");
        _checkpoint(ACCOUNT_A, 1, 3, 21_000e6, 0);
        (uint256 e2, uint64 validUntil, uint64 age) = book.eligibleUnpaid(FA, 7 days, 0, 500, uint64(block.timestamp));
        assertEq(e2, 12_000e6);
        assertEq(validUntil, uint64(block.timestamp + 15 minutes));
        assertEq(age, 0);
        GpuTypes.DrawEvaluation memory ev = _ev(FA);
        assertEq(ev.eligibleReceivables, 12_000e6);
        assertEq(ev.receivableLimit, 6000e6, "50% advance rate");
        assertEq(ev.availableDraw, 6000e6);
        IReceivableBook.Receivable memory r = book.receivable(_idA());
        assertEq(uint8(r.state), uint8(IReceivableBook.ReceivableState.ASSIGNED));
        assertEq(r.revision, 2);
        assertEq(book.accountStats(MOCK, ACCOUNT_A).eventsConsumed, 3);
    }

    function test_checkpoint_revisionGapBlocksBase() public {
        _recognizeFixture();
        _assign(REF_A, FA, 2);
        _checkpoint(ACCOUNT_A, 1, 4, 21_000e6, 0); // issuer counter ahead of what we consumed: REVISION_GAP
        (uint256 e,,) = book.eligibleUnpaid(FA, 7 days, 0, 500, uint64(block.timestamp));
        assertEq(e, 0);
        assertEq(_ev(FA).availableDraw, 0);
    }

    function test_checkpoint_openAmountMismatchBlocksBase_withZeroTolerance() public {
        _recognizeFixture();
        _assign(REF_A, FA, 2);
        _checkpoint(ACCOUNT_A, 1, 3, 20_000e6, 0); // issuer says 20k open, we mirror 21k
        (uint256 e,,) = book.eligibleUnpaid(FA, 7 days, 0, 500, uint64(block.timestamp));
        assertEq(e, 0);
        (uint256 tol,,) = book.eligibleUnpaid(FA, 7 days, 500, 500, uint64(block.timestamp)); // 5% tolerance policy
        assertEq(tol, 12_000e6);
    }

    function test_checkpoint_staleBlocksBase_andCannotGoBackwards() public {
        _baseA();
        vm.warp(T0 + 7 days + 1);
        (uint256 e, uint64 validUntil, uint64 age) = book.eligibleUnpaid(FA, 7 days, 0, 500, uint64(block.timestamp));
        assertEq(e, 0);
        assertEq(validUntil, 0);
        assertEq(age, 0, "nothing included: no age reported");
        assertEq(_ev(FA).availableDraw, 0);
        // a checkpoint seq cannot go backwards (seq 3 then seq 2); a replay of seq 1 is the same economic fact and
        // is refused by the EvidenceBook before the book sees it
        _checkpoint(ACCOUNT_A, 3, 3, 21_000e6, 0);
        bytes memory data = abi.encode(
            uint64(2), uint32(3), 21_000e6, uint256(0), uint64(block.timestamp), uint64(block.timestamp + 15 minutes)
        );
        _ingestOneRev(
            T_CHECKPOINT,
            _log(T_CHECKPOINT, ACCOUNT_A, 0, 0, 2, data),
            _claim(0, ACCOUNT_A, 0, 0, data),
            abi.encodeWithSelector(IReceivableBook.CheckpointNotNewer.selector, uint64(3), uint64(2))
        );
        assertEq(book.checkpoint(MOCK, ACCOUNT_A).checkpointSeq, 3);
    }

    function test_partialCorrection_reducesBaseImmediately() public {
        _baseA();
        _correct(REF_A, -2000e6, 3, 0);
        (uint256 e,,) = book.eligibleUnpaid(FA, 7 days, 0, 500, uint64(block.timestamp));
        assertEq(e, 0, "checkpoint now behind (rev 3 vs consumed 4): blocked until re-published");
        _checkpoint(ACCOUNT_A, 2, 4, 19_000e6, 0);
        (uint256 e2,,) = book.eligibleUnpaid(FA, 7 days, 0, 500, uint64(block.timestamp));
        assertEq(e2, 10_000e6);
        assertEq(_ev(FA).receivableLimit, 5000e6);
    }

    function test_paidReceivable_leavesBase_andCannotBeReRecognized() public {
        _baseA();
        _payout(REF_A, USDC, 12_000e6, 1);
        IReceivableBook.Receivable memory r = book.receivable(_idA());
        assertEq(uint8(r.state), uint8(IReceivableBook.ReceivableState.PAID));
        assertEq(r.revision, 3);
        assertEq(r.token, USDC);
        _checkpoint(ACCOUNT_A, 2, 4, 9000e6, 12_000e6);
        (uint256 e,,) = book.eligibleUnpaid(FA, 7 days, 0, 500, uint64(block.timestamp));
        assertEq(e, 0, "paid receivable contributes nothing");
        // a fresh "recognition" of the same obligation ref is not new base: a second proof of revision 1 is the same
        // economic fact (EvidenceBook dedup), and a recognition log at any other revision hits the book's guard
        bytes memory data = abi.encode(PAYER, ESCROW, USDC, uint256(12_000e6), DUE_AT, uint32(1));
        vm.prank(relayer);
        vm.expectRevert(); // EconomicEventAlreadyRecorded
        book.ingest(
            MOCK,
            _envelope(_txBytes(1, _one(_obligationLog(REF_A, 12_000e6, 1))), nextHeight++, 0),
            ESCROW,
            _topics(T_RECOGNIZED),
            _single(_claim(0, ACCOUNT_A, REF_A, bytes32(uint256(uint160(ISSUER))), data))
        );
        bytes memory data4 = abi.encode(PAYER, ESCROW, USDC, uint256(12_000e6), DUE_AT, uint32(4));
        _ingestOneRev(
            T_RECOGNIZED,
            _obligationLog(REF_A, 12_000e6, 4),
            _claim(0, ACCOUNT_A, REF_A, bytes32(uint256(uint160(ISSUER))), data4),
            abi.encodeWithSelector(IReceivableBook.ReceivableExists.selector, _idA())
        );
        assertEq(uint8(book.receivable(_idA()).state), uint8(IReceivableBook.ReceivableState.PAID));
        // and the payout cannot be replayed under the same settlement sequence
        _payoutRev(REF_B, USDC, 1e6, 1, abi.encodeWithSelector(IReceivableBook.SettlementSeen.selector, uint64(1)));
    }

    function test_payoutCancelled_restoresUnpaid_onceOnly() public {
        _baseA();
        _payout(REF_A, USDC, 5000e6, 1);
        assertEq(book.receivable(_idA()).paid, 5000e6);
        bytes memory data = abi.encode(uint64(1), uint256(5000e6));
        _ingestOne(T_CANCELLED, _log(T_CANCELLED, ACCOUNT_A, REF_A, 0, 3, data), _claim(0, ACCOUNT_A, REF_A, 0, data));
        IReceivableBook.Receivable memory r = book.receivable(_idA());
        assertEq(r.paid, 0);
        assertEq(uint8(r.state), uint8(IReceivableBook.ReceivableState.ASSIGNED));
        assertEq(book.accountStats(MOCK, ACCOUNT_A).eventsConsumed, 5);
        // a second cancellation proof for the same settlement is the same economic fact: refused by the EvidenceBook
        vm.prank(relayer);
        vm.expectRevert(); // EconomicEventAlreadyRecorded(key, firstSourceEventId)
        book.ingest(
            MOCK,
            _envelope(_txBytes(1, _one(_log(T_CANCELLED, ACCOUNT_A, REF_A, 0, 3, data))), nextHeight++, 0),
            ESCROW,
            _topics(T_CANCELLED),
            _single(_claim(0, ACCOUNT_A, REF_A, 0, data))
        );
        assertEq(book.receivable(_idA()).paid, 0);
    }

    function test_claimedAmountDifferentFromVerifiedLog_reverts_nothingConsumed() public {
        bytes memory txBytes = _fixtureTxBytes();
        IReceivableBook.ReceivableClaim[] memory cs = new IReceivableBook.ReceivableClaim[](2);
        cs[0] = _claim(
            0,
            ACCOUNT_A,
            REF_A,
            bytes32(uint256(uint160(ISSUER))),
            abi.encode(PAYER, ESCROW, USDC, uint256(99_000e6), DUE_AT, uint32(1))
        );
        cs[1] = _claim(
            1,
            ACCOUNT_A,
            REF_B,
            bytes32(uint256(uint160(ISSUER))),
            abi.encode(PAYER, ESCROW, USDC, 9000e6, DUE_AT, uint32(1))
        );
        vm.prank(relayer);
        vm.expectRevert(); // ClaimMismatch(expected, claimed)
        book.ingest(MOCK, _envelope(txBytes, HEIGHT, 17), ESCROW, _topics(T_RECOGNIZED), cs);
        assertFalse(evidence.isConsumed(verifier.sourceEventId(HEIGHT, 17, 0)));
        assertFalse(evidence.isConsumed(verifier.sourceEventId(HEIGHT, 17, 1)));
        assertEq(uint8(book.receivable(_idA()).state), uint8(IReceivableBook.ReceivableState.NONE));
    }

    function test_revisionOrder_gapAndStaleRejected() public {
        _recognizeFixture();
        _assignRev(
            REF_A, FA, 3, abi.encodeWithSelector(IReceivableBook.RevisionGap.selector, _idA(), uint32(2), uint32(3))
        );
        _assign(REF_A, FA, 2);
        // the same revision through a second proof is the same economic fact: EvidenceBook dedup fires first
        bytes32 fk = book.facilityKey(FA);
        bytes memory d2 = abi.encode(uint32(2));
        vm.prank(relayer);
        vm.expectRevert(); // EconomicEventAlreadyRecorded
        book.ingest(
            MOCK,
            _envelope(_txBytes(1, _one(_log(T_ASSIGNED, ACCOUNT_A, REF_A, fk, 4, d2))), nextHeight++, 0),
            ESCROW,
            _topics(T_ASSIGNED),
            _single(_claim(0, ACCOUNT_A, REF_A, fk, d2))
        );
        // a lower revision (a distinct, out-of-order fact) is stale
        _assignRev(
            REF_A, FA, 1, abi.encodeWithSelector(IReceivableBook.RevisionStale.selector, _idA(), uint32(2), uint32(1))
        );
        assertEq(book.receivable(_idA()).revision, 2);
    }

    function test_assignment_toFacilityOfAnotherBorrower_rejected() public {
        _recognizeFixture();
        // FC belongs to borrower B; account A's obligation cannot be assigned to it
        _openLedger(FC, 0);
        vm.prank(underwriter);
        book.registerFacility(FC, BORROWER_B, MOCK, _usdc());
        _assignRev(
            REF_A, FC, 2, abi.encodeWithSelector(IReceivableBook.AccountNotOfBorrower.selector, ACCOUNT_A, BORROWER_B)
        );
        // unknown facility key
        bytes memory data = abi.encode(uint32(2));
        bytes32 bogus = keccak256("nope");
        _ingestOneRev(
            T_ASSIGNED,
            _log(T_ASSIGNED, ACCOUNT_A, REF_A, bogus, 4, data),
            _claim(0, ACCOUNT_A, REF_A, bogus, data),
            abi.encodeWithSelector(IReceivableBook.FacilityKeyMismatch.selector, bogus)
        );
        assertEq(uint8(book.receivable(_idA()).state), uint8(IReceivableBook.ReceivableState.OPEN));
    }

    function test_payoutInOtherToken_rejected_andUnattributedPayoutNeverBase() public {
        _baseA();
        _payoutRev(
            REF_A,
            OTHER_TOKEN,
            1e6,
            1,
            abi.encodeWithSelector(IReceivableBook.TokenMismatch.selector, USDC, OTHER_TOKEN)
        );
        // unattributed payout (obligationRef 0): recorded, never a receivable
        _payout(bytes32(0), USDC, 777e6, 2);
        IReceivableBook.AccountStats memory s = book.accountStats(MOCK, ACCOUNT_A);
        assertEq(s.paidCumulative, 777e6);
        assertEq(s.openAmount, 21_000e6);
        assertEq(s.eventsConsumed, 3, "unattributed payouts do not bump the obligation counter");
        _checkpoint(ACCOUNT_A, 2, 3, 21_000e6, 777e6); // paid cumulative must reconcile too
        (uint256 e,,) = book.eligibleUnpaid(FA, 7 days, 0, 500, uint64(block.timestamp));
        assertEq(e, 12_000e6);
    }

    function test_disputed_andExpiredEvidence_excluded() public {
        _baseA();
        bytes32 idA = _idA();
        vm.prank(guardian);
        book.setDisputed(idA, true, "issuer dispute");
        (uint256 e,,) = book.eligibleUnpaid(FA, 7 days, 0, 500, uint64(block.timestamp));
        assertEq(e, 0);
        vm.prank(underwriter);
        book.setDisputed(idA, false, "resolved");
        // evidence validUntil (7d from claims) expires before the checkpoint window (use 30d max age)
        vm.warp(T0 + 7 days);
        (uint256 e2,,) = book.eligibleUnpaid(FA, 30 days, 0, 500, uint64(block.timestamp));
        assertEq(e2, 0, "expired proof validity drops the receivable");
        vm.prank(mallory);
        vm.expectRevert();
        book.setDisputed(idA, true, "x");
    }

    function test_overdueHaircut_applied() public {
        _baseA();
        // evidence claims are valid 7 days and the checkpoint ages; re-publish both after passing dueAt
        vm.warp(DUE_AT + 1);
        (uint256 stale,,) = book.eligibleUnpaid(FA, 7 days, 0, 500, uint64(block.timestamp));
        assertEq(stale, 0, "proof validity and checkpoint expired meanwhile");
        _assignRefresh();
        (uint256 e,,) = book.eligibleUnpaid(FA, 365 days, 0, 500, uint64(block.timestamp));
        assertEq(e, 12_000e6 * 9500 / 10_000, "5% overdue haircut (1-30 days past due)");
        (uint256 e0,,) = book.eligibleUnpaid(FA, 365 days, 0, 0, uint64(block.timestamp));
        assertEq(e0, 12_000e6);
    }

    function test_ingest_roleGated_andNoDirectRegistration() public {
        bytes memory txBytes = _fixtureTxBytes();
        IReceivableBook.ReceivableClaim[] memory cs = new IReceivableBook.ReceivableClaim[](1);
        cs[0] = _claim(
            0,
            ACCOUNT_A,
            REF_A,
            bytes32(uint256(uint160(ISSUER))),
            abi.encode(PAYER, ESCROW, USDC, 12_000e6, DUE_AT, uint32(1))
        );
        bytes32 relayerRole = roles.RELAYER();
        GpuTypes.NativeProofEnvelope memory env = _envelope(txBytes, HEIGHT, 17);
        bytes32[] memory ts = _topics(T_RECOGNIZED);
        vm.prank(mallory);
        vm.expectRevert(abi.encodeWithSelector(ReceivableBook.NotRole.selector, relayerRole, mallory));
        book.ingest(MOCK, env, ESCROW, ts, cs);
        vm.prank(underwriter);
        (bool ok,) = address(book).call(abi.encodeWithSignature("recognize(bytes32,uint256)", REF_A, 1e6));
        assertFalse(ok, "no direct recognition path");
    }

    // ================================================================== GPU-035.b policy / exposure / reservations

    function test_groupCap_10k_with8kOutstanding_leaves2k() public {
        _baseA();
        vm.prank(manager);
        ledger.recordDraw(FB, 8000e6); // FB is in the same borrower/group as FA
        GpuTypes.DrawEvaluation memory ev = _ev(FA);
        assertEq(ev.headroom, 2000e6);
        assertEq(ev.availableDraw, 2000e6);
        vm.prank(manager);
        vm.expectRevert(abi.encodeWithSelector(IExposureController.InsufficientHeadroom.selector, 2000e6 + 1, 2000e6));
        ctl.reserve(FA, 2000e6 + 1, 1, uint64(block.timestamp + 1 hours));
    }

    function test_twoReservations_thenConsume_noDoubleCount() public {
        _baseA();
        vm.startPrank(manager);
        bytes32 r1 = ctl.reserve(FA, 3000e6, 1, uint64(block.timestamp + 1 hours));
        assertEq(_ev(FA).availableDraw, 3000e6, "reserved counts against room");
        bytes32 r2 = ctl.reserve(FA, 3000e6, 2, uint64(block.timestamp + 1 hours));
        assertEq(_ev(FA).availableDraw, 0);
        vm.expectRevert(abi.encodeWithSelector(IExposureController.InsufficientHeadroom.selector, 1, 0));
        ctl.reserve(FA, 1, 3, uint64(block.timestamp + 1 hours));
        assertEq(ctl.exposureGlobal(uint64(block.timestamp)), 6000e6, "reservations are exposure");
        ctl.consumeReservation(r1);
        assertEq(ctl.reservedOf(FA), 3000e6);
        assertEq(ledger.legalDebtAt(FA, uint64(block.timestamp)), 3000e6);
        assertEq(ctl.exposureGlobal(uint64(block.timestamp)), 6000e6, "reserved -> debt is atomic, never both");
        ctl.consumeReservation(r2);
        assertEq(ctl.reservedOf(FA), 0);
        assertEq(ledger.legalDebtAt(FA, uint64(block.timestamp)), 6000e6);
        assertEq(_ev(FA).availableDraw, 0);
        // replay
        vm.expectRevert(
            abi.encodeWithSelector(
                IExposureController.ReservationNotActive.selector, r1, IExposureController.ReservationState.CONSUMED
            )
        );
        ctl.consumeReservation(r1);
        vm.expectRevert(abi.encodeWithSelector(IExposureController.NonceUsed.selector, FA, uint64(1)));
        ctl.reserve(FA, 1, 1, uint64(block.timestamp + 1 hours));
        vm.stopPrank();
    }

    function test_reservation_cancelAndExpire_onlyOnChain() public {
        _baseA();
        vm.prank(manager);
        bytes32 r1 = ctl.reserve(FA, 1000e6, 1, uint64(block.timestamp + 1 hours));
        vm.warp(T0 + 2 hours);
        // past expiry: still reserved until someone calls expire on-chain; consume is refused
        assertEq(ctl.reservedOf(FA), 1000e6);
        vm.prank(manager);
        vm.expectRevert(
            abi.encodeWithSelector(IExposureController.ReservationExpired.selector, r1, uint64(T0 + 1 hours))
        );
        ctl.consumeReservation(r1);
        vm.prank(mallory);
        ctl.expireReservation(r1);
        assertEq(ctl.reservedOf(FA), 0);
        // cancel path (manager or underwriter), not mallory
        _checkpoint(ACCOUNT_A, 2, 3, 21_000e6, 0);
        vm.prank(manager);
        bytes32 r2 = ctl.reserve(FA, 1000e6, 2, uint64(block.timestamp + 1 hours));
        vm.prank(mallory);
        vm.expectRevert(abi.encodeWithSelector(IExposureController.NotManager.selector, mallory));
        ctl.cancelReservation(r2);
        vm.prank(mallory);
        vm.expectRevert(
            abi.encodeWithSelector(IExposureController.ReservationInvalidated.selector, r2, "not yet expired")
        );
        ctl.expireReservation(r2);
        vm.prank(underwriter);
        ctl.cancelReservation(r2);
        assertEq(ctl.reservedOf(FA), 0);
    }

    function test_stalePolicyVersion_rejectsReservationsAndAuthorizations() public {
        _baseA();
        vm.prank(manager);
        bytes32 r1 = ctl.reserve(FA, 1000e6, 1, uint64(block.timestamp + 1 hours));
        _publishPolicy(POLICY_V2, 10_000e6, 10_000e6, 20_000e6, 20_000e6);
        assertEq(_ev(FA).availableDraw, 0, "authorization pinned to a stale policy");
        vm.prank(manager);
        vm.expectRevert(abi.encodeWithSelector(IExposureController.PolicyStale.selector, POLICY_V1));
        ctl.reserve(FA, 1, 2, uint64(block.timestamp + 1 hours));
        vm.prank(manager);
        vm.expectRevert(
            abi.encodeWithSelector(IExposureController.ReservationInvalidated.selector, r1, "policy changed")
        );
        ctl.consumeReservation(r1);
        // re-authorize under v2: old reservation is still invalid (epoch changed), new ones work
        vm.prank(underwriter);
        vm.expectRevert(abi.encodeWithSelector(IExposureController.PolicyStale.selector, POLICY_V1));
        ctl.setAuthorization(FA, 50_000e6, POLICY_V1, AGR_A, 1, T0 + 30 days);
        vm.prank(underwriter);
        ctl.setAuthorization(FA, 50_000e6, POLICY_V2, AGR_A, 1, T0 + 30 days);
        vm.prank(manager);
        vm.expectRevert(
            abi.encodeWithSelector(IExposureController.ReservationInvalidated.selector, r1, "authorization changed")
        );
        ctl.consumeReservation(r1);
        vm.prank(manager);
        ctl.cancelReservation(r1);
        assertEq(_ev(FA).availableDraw, 6000e6);
    }

    function test_staleControl_versionBumpAndObservationAge_block() public {
        _baseA();
        assertEq(_ev(FA).availableDraw, 6000e6);
        vm.warp(T0 + 1 days + 1); // observation older than controlObservationMaxAge (1 day)
        assertEq(_ev(FA).availableDraw, 0);
        vm.prank(manager);
        vm.expectRevert(abi.encodeWithSelector(IExposureController.ControlNotUsable.selector, AGR_A, uint32(1)));
        ctl.reserve(FA, 1, 1, uint64(block.timestamp + 1 hours));
        vm.prank(servicer);
        control.observe(AGR_A, GpuTypes.ControlGrade.E2, ESCROW);
        _checkpoint(ACCOUNT_A, 2, 3, 21_000e6, 0);
        assertEq(_ev(FA).availableDraw, 6000e6);
        // new agreement version invalidates the pinned version 1
        vm.prank(underwriter);
        control.bumpVersion(
            AGR_A,
            GpuTypes.ControlGrade.E2,
            ESCROW,
            SEPOLIA,
            keccak256("agreement-v2"),
            uint64(block.timestamp),
            0,
            keccak256("poc")
        );
        assertEq(_ev(FA).availableDraw, 0);
        vm.prank(manager);
        vm.expectRevert(abi.encodeWithSelector(IExposureController.ControlNotUsable.selector, AGR_A, uint32(1)));
        ctl.reserve(FA, 1, 2, uint64(block.timestamp + 1 hours));
        // an E1 agreement can never authorize (G-D)
        vm.prank(registrar);
        control.createAgreement(
            keccak256("agr-e1"),
            BORROWER_A,
            ACCOUNT_A,
            GpuTypes.ControlGrade.E1,
            ESCROW,
            SEPOLIA,
            keccak256("h"),
            T0,
            0,
            0
        );
        vm.prank(servicer);
        control.observe(keccak256("agr-e1"), GpuTypes.ControlGrade.E1, ESCROW);
        vm.prank(underwriter);
        ctl.setAuthorization(FA, 50_000e6, POLICY_V1, keccak256("agr-e1"), 1, T0 + 30 days);
        assertEq(_ev(FA).availableDraw, 0);
    }

    function test_overlappingCategories_minHeadroomWins() public {
        _baseA();
        _publishPolicy(POLICY_V2, 10_000e6, 10_000e6, 4000e6, 20_000e6); // provider cap tighter
        vm.prank(underwriter);
        ctl.setAuthorization(FA, 50_000e6, POLICY_V2, AGR_A, 1, T0 + 30 days);
        assertEq(_ev(FA).headroom, 4000e6);
        assertEq(_ev(FA).availableDraw, 4000e6);
    }

    function test_vaultCash_limitsAvailableDraw() public {
        _baseA();
        vault.set(1234e6);
        GpuTypes.DrawEvaluation memory ev = _ev(FA);
        assertEq(ev.vaultCash, 1234e6);
        assertEq(ev.availableDraw, 1234e6);
        vault.set(0);
        assertEq(_ev(FA).availableDraw, 0);
    }

    function test_globalCap11k_accruedInterestOfA_blocksBsOneUnit() public {
        _baseA();
        _publishPolicy(POLICY_V2, 100_000e6, 100_000e6, 100_000e6, 11_000e6);
        vm.startPrank(underwriter);
        ctl.setAuthorization(FA, 50_000e6, POLICY_V2, AGR_A, 1, T0 + 400 days);
        ctl.setAuthorization(FB, 50_000e6, POLICY_V2, AGR_A, 1, T0 + 400 days);
        vm.stopPrank();
        vm.prank(manager);
        ledger.recordDraw(FA, 10_000e6);
        assertEq(ctl.headroomOf(FB, POLICY_V2, uint64(block.timestamp)), 1000e6);
        vm.warp(T0 + 365 days);
        vm.prank(servicer);
        control.observe(AGR_A, GpuTypes.ControlGrade.E2, ESCROW); // keep E2 fresh so only the cap decides
        assertEq(
            ledger.legalDebtAt(FA, uint64(block.timestamp)), 11_000e6, "10% for a year, unrecorded interest counts"
        );
        assertEq(ctl.headroomOf(FB, POLICY_V2, uint64(block.timestamp)), 0);
        vm.prank(manager);
        vm.expectRevert(abi.encodeWithSelector(IExposureController.InsufficientHeadroom.selector, 1, 0));
        ctl.reserve(FB, 1, 1, uint64(block.timestamp + 1 hours));
    }

    function test_capZero_isNotUnlimited() public {
        _baseA();
        _publishPolicy(POLICY_V2, 10_000e6, 10_000e6, 20_000e6, 0);
        vm.prank(underwriter);
        ctl.setAuthorization(FA, 50_000e6, POLICY_V2, AGR_A, 1, T0 + 30 days);
        vm.expectRevert(abi.encodeWithSelector(GpuRiskPolicy.CapNotSet.selector, "global"));
        ctl.evaluateDraw(FA);
        vm.prank(manager);
        vm.expectRevert(abi.encodeWithSelector(GpuRiskPolicy.CapNotSet.selector, "global"));
        ctl.reserve(FA, 1, 1, uint64(block.timestamp + 1 hours));
        // facility limit 0 = no execution
        _publishPolicy(keccak256("policy-v3"), 10_000e6, 10_000e6, 20_000e6, 20_000e6);
        vm.prank(underwriter);
        ctl.setAuthorization(FA, 0, keccak256("policy-v3"), AGR_A, 1, T0 + 30 days);
        assertEq(_ev(FA).availableDraw, 0);
        vm.prank(manager);
        vm.expectRevert(abi.encodeWithSelector(IExposureController.FacilityLimitZero.selector, FA));
        ctl.reserve(FA, 1, 1, uint64(block.timestamp + 1 hours));
    }

    function test_limitDecrease_neverErasesDebt() public {
        _baseA();
        vm.startPrank(manager);
        bytes32 r = ctl.reserve(FA, 6000e6, 1, uint64(block.timestamp + 1 hours));
        ctl.consumeReservation(r);
        vm.stopPrank();
        vm.prank(underwriter);
        ctl.setAuthorization(FA, 1000e6, POLICY_V1, AGR_A, 1, T0 + 30 days);
        assertEq(ledger.legalDebtAt(FA, uint64(block.timestamp)), 6000e6);
        GpuTypes.DrawEvaluation memory ev = _ev(FA);
        assertEq(ev.facilityLimit, 1000e6);
        assertEq(ev.facilityRoom, 0);
        assertEq(ev.availableDraw, 0);
        assertEq(ctl.exposureOfBorrower(BORROWER_A, uint64(block.timestamp)), 6000e6);
    }

    function test_maturity_andDecisionExpiry_blockNewDraws() public {
        _openLedger(FC, T0 + 10 days);
        vm.startPrank(underwriter);
        book.registerFacility(FC, BORROWER_A, MOCK, _usdc());
        ctl.enrollFacility(FC, GROUP_A);
        ctl.setAuthorization(FC, 50_000e6, POLICY_V1, AGR_A, 1, T0 + 5 days);
        vm.stopPrank();
        _recognizeFixture();
        _assign(REF_A, FC, 2);
        _checkpoint(ACCOUNT_A, 1, 3, 21_000e6, 0);
        assertEq(_ev(FC).availableDraw, 6000e6);
        vm.warp(T0 + 5 days);
        assertEq(_ev(FC).availableDraw, 0, "credit decision expired");
        vm.prank(manager);
        vm.expectRevert(
            abi.encodeWithSelector(IExposureController.AuthorizationExpired.selector, FC, uint64(T0 + 5 days))
        );
        ctl.reserve(FC, 1, 1, uint64(block.timestamp + 1 hours));
        vm.prank(underwriter);
        ctl.setAuthorization(FC, 50_000e6, POLICY_V1, AGR_A, 1, T0 + 40 days);
        vm.prank(servicer);
        control.observe(AGR_A, GpuTypes.ControlGrade.E2, ESCROW);
        vm.warp(T0 + 10 days);
        assertEq(_ev(FC).availableDraw, 0, "matured facility");
    }

    function test_largeValues_noOverflow() public {
        _recognizeFixture();
        // a 1e12 USDC obligation (1e18 base units) through the same proven path
        bytes32 refBig = keccak256("inv-big");
        bytes memory data = abi.encode(PAYER, ESCROW, USDC, uint256(1e18), DUE_AT, uint32(1));
        _ingestOne(
            T_RECOGNIZED,
            _log(T_RECOGNIZED, ACCOUNT_A, refBig, bytes32(uint256(uint160(ISSUER))), 4, data),
            _claim(0, ACCOUNT_A, refBig, bytes32(uint256(uint160(ISSUER))), data)
        );
        _assign(refBig, FA, 2);
        _checkpoint(ACCOUNT_A, 1, 4, 21_000e6 + 1e18, 0);
        _publishPolicy(POLICY_V2, type(uint128).max, type(uint128).max, type(uint128).max, type(uint128).max);
        vm.prank(underwriter);
        ctl.setAuthorization(FA, type(uint128).max, POLICY_V2, AGR_A, 1, T0 + 30 days);
        vault.set(type(uint128).max);
        GpuTypes.DrawEvaluation memory ev = _ev(FA);
        assertEq(ev.eligibleReceivables, 1e18);
        assertEq(ev.receivableLimit, 5e17);
        assertEq(ev.availableDraw, ev.receivableLimit);
    }

    function test_exposureIsLedgerDebtPlusReservations_noWriteOffCoupling() public {
        _baseA();
        vm.startPrank(manager);
        bytes32 r = ctl.reserve(FA, 2000e6, 1, uint64(block.timestamp + 1 hours));
        ctl.consumeReservation(r);
        ctl.reserve(FA, 1000e6, 2, uint64(block.timestamp + 1 hours));
        ledger.freezeAccrual(FA); // non-accrual is not forgiveness
        vm.stopPrank();
        uint64 at = uint64(block.timestamp);
        assertEq(
            ctl.exposureOfBorrower(BORROWER_A, at), ledger.legalDebtAt(FA, at) + ledger.legalDebtAt(FB, at) + 1000e6
        );
        assertEq(ctl.exposureOfProvider(MOCK, at), ctl.exposureGlobal(at));
        // no write-off / impairment entry point on the controller or the policy
        (bool ok1,) = address(ctl).call(abi.encodeWithSignature("writeOff(bytes32,uint256)", FA, 1));
        (bool ok2,) = address(policy).call(abi.encodeWithSignature("impair(bytes32,uint256)", FA, 1));
        assertFalse(ok1);
        assertFalse(ok2);
        assertEq(ctl.exposureOfBorrower(BORROWER_A, at), 3000e6);
    }

    function test_policy_publishRules_andVersioning() public {
        assertEq(policy.currentVersion(), POLICY_V1);
        assertTrue(policy.isCurrent(POLICY_V1));
        IRiskPolicy.Params memory p = policy.params(POLICY_V1);
        vm.prank(mallory);
        vm.expectRevert(abi.encodeWithSelector(GpuRiskPolicy.NotUnderwriter.selector, mallory));
        policy.publish(POLICY_V2, p, 0);
        vm.prank(underwriter);
        vm.expectRevert(abi.encodeWithSelector(GpuRiskPolicy.PolicyExists.selector, POLICY_V1));
        policy.publish(POLICY_V1, p, 0);
        p.advanceRateBps = 10_001;
        vm.prank(underwriter);
        vm.expectRevert(abi.encodeWithSelector(GpuRiskPolicy.InvalidParams.selector, "advanceRate"));
        policy.publish(POLICY_V2, p, 0);
        _publishPolicy(POLICY_V2, 1, 1, 1, 1);
        assertFalse(policy.isCurrent(POLICY_V1));
        assertEq(policy.versionCount(), 2);
        vm.expectRevert(abi.encodeWithSelector(GpuRiskPolicy.PolicyNotCurrent.selector, POLICY_V1, POLICY_V2));
        policy.requireCurrent(POLICY_V1);
        // pure evaluation floors and takes the minimum of every room
        GpuTypes.DrawEvaluation memory e =
            policy.evaluate(POLICY_V1, 12_000e6 + 1, 50_000e6, 1000e6, 500e6, 3000e6, 2500e6);
        assertEq(e.receivableLimit, uint256(12_000e6 + 1) / 2);
        assertEq(e.facilityRoom, 48_500e6);
        assertEq(e.availableDraw, 2500e6);
    }

    function test_manager_onlyRoles() public {
        _baseA();
        vm.prank(mallory);
        vm.expectRevert(abi.encodeWithSelector(IExposureController.NotManager.selector, mallory));
        ctl.reserve(FA, 1, 1, uint64(block.timestamp + 1 hours));
        bytes32 uw = roles.UNDERWRITER();
        vm.prank(mallory);
        vm.expectRevert(abi.encodeWithSelector(ExposureController.NotRole.selector, uw, mallory));
        ctl.setAuthorization(FA, 1, POLICY_V1, AGR_A, 1, T0 + 30 days);
        vm.prank(mallory);
        vm.expectRevert(abi.encodeWithSelector(ExposureController.NotRole.selector, keccak256("ADMIN"), mallory));
        ctl.setManager(mallory, true);
        // a manager may not record debt without a reservation through the controller (ledger writer list is admin's)
        assertFalse(ledger.isWriter(mallory));
    }

    function test_evidenceBook_recordsProofBoundIdsForIngestedLogs() public {
        _baseA();
        assertTrue(evidence.isConsumed(verifier.sourceEventId(HEIGHT, 17, 0)));
        assertTrue(evidence.isConsumed(verifier.sourceEventId(HEIGHT, 17, 1)));
        IEvidenceBook.EvidenceRecord memory rec = evidence.record(verifier.sourceEventId(HEIGHT, 17, 0));
        assertEq(rec.consumer, address(book));
        assertEq(uint8(rec.meaning), uint8(GpuTypes.EvidenceMeaning.OBLIGATION_RECOGNIZED));
        assertEq(uint8(rec.method), uint8(GpuTypes.VerificationMethod.LOCAL_MOCK), "mock verification is labeled");
        // replaying the recognition proof is refused by the EvidenceBook before any state change
        vm.prank(relayer);
        vm.expectRevert(
            abi.encodeWithSelector(IEvidenceBook.AlreadyConsumed.selector, verifier.sourceEventId(HEIGHT, 17, 0))
        );
        _recognizeFixture();
    }
}
