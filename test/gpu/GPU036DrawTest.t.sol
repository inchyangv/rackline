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
import { LendingVaultV2 } from "../../contracts/gpu/LendingVaultV2.sol";
import { CreditFacilityManager } from "../../contracts/gpu/CreditFacilityManager.sol";
import { IProviderRegistry } from "../../contracts/gpu/interfaces/IProviderRegistry.sol";
import { IDebtLedger } from "../../contracts/gpu/interfaces/IDebtLedger.sol";
import { IRiskPolicy } from "../../contracts/gpu/interfaces/IRiskPolicy.sol";
import { IReceivableBook } from "../../contracts/gpu/interfaces/IReceivableBook.sol";
import { IExposureController, IVaultCashView } from "../../contracts/gpu/interfaces/IExposureController.sol";
import { IControlRegistry } from "../../contracts/gpu/interfaces/IControlRegistry.sol";
import { IAuthorizationVerifier } from "../../contracts/gpu/interfaces/IAuthorizationVerifier.sol";
import { ICreditFacilityManager } from "../../contracts/gpu/interfaces/ICreditFacilityManager.sol";

/// @dev TEST_ONLY loan token: standard ERC20 whose `transfer` can be made to deliver less than requested
///      (partial delivery) to prove full rollback of a draw.
contract ShortfallToken {
    string public name = "TEST_ONLY loan USD";
    string public symbol = "tUSD";
    uint8 public decimals = 6;
    uint256 public totalSupply;
    uint256 public shortfall;
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    function setShortfall(uint256 s) external {
        shortfall = s;
    }

    function mint(address to, uint256 amount) external {
        totalSupply += amount;
        balanceOf[to] += amount;
    }

    function approve(address spender, uint256 amount) external returns (bool) {
        allowance[msg.sender][spender] = amount;
        return true;
    }

    function transfer(address to, uint256 amount) external returns (bool) {
        uint256 deliver = amount > shortfall ? amount - shortfall : 0;
        balanceOf[msg.sender] -= amount;
        balanceOf[to] += deliver;
        totalSupply -= amount - deliver;
        return true;
    }

    function transferFrom(address from, address to, uint256 amount) external returns (bool) {
        allowance[from][msg.sender] -= amount;
        balanceOf[from] -= amount;
        balanceOf[to] += amount;
        return true;
    }
}

/**
 * @title GPU036DrawTest
 * @notice CreditFacilityManager: anchored underwriting decision, atomic reserve → recordDraw → lend, repayFor by
 *         anyone, state machine parity with GPU-013. LOCAL_MOCK only: MockBlockProver + synthetic wire fixture;
 *         funded draws for real customers/LPs need GPU-010/063 (출시 조건). G-ASC is GPU-080.
 */
contract GPU036DrawTest is Test {
    // actors
    address admin = address(0xAD);
    address registrar = address(0x4E6);
    uint256 constant UNDERWRITER_KEY = 0x0DE;
    address underwriter;
    address guardian = address(0x6A);
    address servicer = address(0x5E);
    address treasury = address(0x7E);
    address relayer = address(0x4E);
    uint256 constant BORROWER_KEY = 0xB0B;
    address borrowerWallet;
    address lp = address(0x1B);
    address mallory = address(0xBAD);

    // system
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
    ShortfallToken loan;
    LendingVaultV2 vault;
    ReceivableBook book;
    ExposureController ctl;
    CreditFacilityManager mgr;

    string wireJson;
    string transitionsJson;

    bytes32 constant MANIFEST = 0x2b0162d0c206f421138269a721c6338d8cf294d67dc644bb8b35ebb9bfbff6bb;
    bytes32 constant ENV_ID_HASH = keccak256("cc3-testnet");
    uint64 constant CHAIN_KEY = 1;
    uint64 constant SEPOLIA = 11_155_111;
    GpuTypes.ProviderId MOCK = GpuTypes.ProviderId.wrap(keccak256("mockdepin-testonly"));
    address constant ESCROW = address(0xE1);
    address constant ISSUER = address(0x155);
    address constant PAYER = address(0xFA);
    address constant USDC = address(0x05DC);
    bytes32 constant REF_A = keccak256("inv-2026-08-A");
    bytes32 constant REF_B = keccak256("inv-2026-08-B");
    GpuTypes.AccountKey ACCOUNT_A = GpuTypes.AccountKey.wrap(keccak256("mockdepin-testonly:acct-A"));
    bytes32 constant BORROWER_A = keccak256("borrower-A");
    bytes32 constant GROUP_A = keccak256("group-A");
    GpuTypes.FacilityId FA = GpuTypes.FacilityId.wrap(keccak256("facility-A"));
    GpuTypes.FacilityId FB = GpuTypes.FacilityId.wrap(keccak256("facility-B"));
    bytes32 constant AGR_A = keccak256("agreement-A");
    bytes32 constant POLICY_V1 = keccak256("policy-v1");
    bytes32 constant POLICY_V2 = keccak256("policy-v2");
    uint64 constant HEIGHT = 9_100_000;
    uint64 constant DUE_AT = 1_761_868_800;
    uint64 constant T0 = 1_750_000_000;
    uint256 constant LP_CASH = 100_000e6;

    bytes32 constant T_RECOGNIZED =
        keccak256("ObligationRecognized(bytes32,bytes32,address,address,address,uint256,uint64,uint32)");
    bytes32 constant T_ASSIGNED = keccak256("ObligationAssigned(bytes32,bytes32,bytes32,uint32)");
    bytes32 constant T_CORRECTED = keccak256("ObligationCorrected(bytes32,bytes32,int256,uint32,uint8)");
    bytes32 constant T_PAYOUT = keccak256("PayoutReceived(bytes32,bytes32,address,address,uint256,uint64)");
    bytes32 constant T_CANCELLED = keccak256("PayoutCancelled(bytes32,bytes32,uint64,uint256)");
    bytes32 constant T_CHECKPOINT = keccak256("SourceCheckpoint(bytes32,uint64,uint32,uint256,uint256)");

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
    uint64 uwNonce = 1;

    // ================================================================== setup

    function setUp() public {
        vm.warp(T0);
        wireJson = vm.readFile("test/fixtures/gpu/attestcoin/wire/synthetic-obligation-v1.json");
        transitionsJson = vm.readFile("test/fixtures/gpu/facility-transitions-v1.json");
        underwriter = vm.addr(UNDERWRITER_KEY);
        borrowerWallet = vm.addr(BORROWER_KEY);

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
        roles.grantRole(roles.TREASURY(), treasury);
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
        loan = new ShortfallToken();
        vault = new LendingVaultV2(roles, ledger, address(loan));
        book = new ReceivableBook(roles, evidence, providers, accounts);
        ctl = new ExposureController(roles, book, ledger, control, policy, IVaultCashView(address(vault)));
        mgr = new CreditFacilityManager(roles, ledger, vault, accounts, control, ctl, policy, book, evidence, auth);

        vm.startPrank(admin);
        evidence.bindVerifier(MOCK, verifier);
        evidence.setConsumer(address(book), true);
        ledger.setWriter(address(mgr), true);
        ledger.setWriter(address(ctl), true);
        ctl.setManager(address(mgr), true);
        vault.setManager(address(mgr), true);
        vm.stopPrank();

        vm.prank(registrar);
        accounts.linkAccount(BORROWER_A, MOCK, ACCOUNT_A);
        _linkWallet(BORROWER_KEY, BORROWER_A, 1);

        _publishPolicy(POLICY_V1, 10_000e6, 10_000e6, 20_000e6, 20_000e6);
        _agreement(AGR_A, BORROWER_A, ACCOUNT_A);

        // LP cash
        loan.mint(lp, LP_CASH);
        vm.startPrank(lp);
        loan.approve(address(vault), LP_CASH);
        vault.deposit(LP_CASH, 0);
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
        providers.registerEmitter(MOCK, ESCROW, T_CHECKPOINT, GpuTypes.EvidenceMeaning.CORRECTION, 0, address(0));
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

    function _assertion(
        uint256 key,
        GpuTypes.AssertionPurpose purpose,
        bytes32 subject,
        uint64 nonce,
        uint64 epoch,
        uint64 ttl
    ) internal view returns (GpuTypes.SupplementaryAssertion memory a) {
        a = GpuTypes.SupplementaryAssertion({
            purpose: purpose,
            subject: subject,
            signer: vm.addr(key),
            keyEpoch: epoch,
            nonce: nonce,
            issuedAt: uint64(block.timestamp),
            expiresAt: uint64(block.timestamp) + ttl,
            signature: ""
        });
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(key, auth.hashAssertion(a));
        a.signature = abi.encodePacked(r, s, v);
    }

    function _linkWallet(uint256 key, bytes32 borrowerId, uint64 nonce) internal {
        bytes32 subject = accounts.walletLinkSubject(borrowerId, vm.addr(key));
        GpuTypes.SupplementaryAssertion memory a =
            _assertion(key, GpuTypes.AssertionPurpose.WALLET_LINK, subject, nonce, 0, 10 minutes);
        vm.prank(registrar);
        accounts.linkWallet(borrowerId, a);
    }

    function _terms(uint64 maturity) internal pure returns (IDebtLedger.Terms memory) {
        return IDebtLedger.Terms({
            loanAsset: GpuTypes.AssetRef({ chainId: 102_031, token: address(0x10A4), decimals: 6 }),
            rateBps: 1000,
            maturityAt: maturity,
            termsVersionId: keccak256("terms-v1"),
            policyVersionId: POLICY_V1,
            executionProfile: GpuTypes.ExecutionProfile.LOCAL_MOCK,
            capitalizeUnpaidInterest: false
        });
    }

    /// @dev Book registration → manager open (DRAFT) → exposure enrollment → underwriter authorization.
    function _openFacility(GpuTypes.FacilityId f, uint256 limit) internal {
        vm.startPrank(underwriter);
        book.registerFacility(f, BORROWER_A, MOCK, _usdc());
        mgr.openFacility(f, BORROWER_A, borrowerWallet, _terms(0), AGR_A, 1);
        control.bindFacility(AGR_A, f);
        ctl.enrollFacility(f, GROUP_A);
        ctl.setAuthorization(f, limit, POLICY_V1, AGR_A, 1, T0 + 30 days);
        vm.stopPrank();
    }

    function _auth(GpuTypes.FacilityId f, uint256 limit) internal view returns (GpuTypes.CreditAuthorization memory) {
        return GpuTypes.CreditAuthorization({
            facilityId: f,
            decisionHash: keccak256("decision-1"),
            limit: limit,
            validUntil: T0 + 30 days,
            policyVersionId: POLICY_V1,
            manifestHash: MANIFEST,
            controlAgreementVersionHash: mgr.controlVersionHash(AGR_A, 1)
        });
    }

    function _anchor(GpuTypes.CreditAuthorization memory a) internal {
        GpuTypes.SupplementaryAssertion memory s = _assertion(
            UNDERWRITER_KEY,
            GpuTypes.AssertionPurpose.CREDIT_APPROVAL,
            keccak256(abi.encode(a)),
            uwNonce++,
            0,
            10 minutes
        );
        vm.prank(underwriter);
        mgr.anchorAuthorization(a, s);
    }

    function _activate(GpuTypes.FacilityId f) internal {
        vm.prank(registrar);
        mgr.transition(f, GpuTypes.FacilityState.UNDER_REVIEW, "onboarding_complete");
        vm.prank(underwriter);
        mgr.transition(f, GpuTypes.FacilityState.CONTROL_PENDING, "credit_decision_approved");
        vm.prank(servicer);
        mgr.transition(f, GpuTypes.FacilityState.ACTIVE, "control_grade_e2_effective");
    }

    /// @dev Full happy-path setup: facility A open, anchored 50k, ACTIVE, inv-A (12,000) assigned + checkpoint.
    function _readyA() internal {
        _openFacility(FA, 50_000e6);
        _anchor(_auth(FA, 50_000e6));
        _activate(FA);
        _recognizeFixture();
        _assign(REF_A, FA, 2);
        _checkpoint(ACCOUNT_A, 1, 3, 21_000e6, 0);
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
        IReceivableBook.ReceivableClaim[] memory cs = new IReceivableBook.ReceivableClaim[](1);
        cs[0] = c;
        Log[] memory ls = new Log[](1);
        ls[0] = l;
        vm.prank(relayer);
        book.ingest(MOCK, _envelope(_txBytes(1, ls), nextHeight++, 0), ESCROW, _topics(topic0), cs);
    }

    function _recognizeFixture() internal {
        bytes memory txBytes = vm.parseJsonBytes(wireJson, ".cases.obligation2Logs.txBytes");
        IReceivableBook.ReceivableClaim[] memory cs = new IReceivableBook.ReceivableClaim[](2);
        cs[0] = _claim(
            0,
            ACCOUNT_A,
            REF_A,
            bytes32(uint256(uint160(ISSUER))),
            abi.encode(PAYER, ESCROW, 12_000e6, DUE_AT, uint32(1))
        );
        cs[1] = _claim(
            1, ACCOUNT_A, REF_B, bytes32(uint256(uint160(ISSUER))), abi.encode(PAYER, ESCROW, 9000e6, DUE_AT, uint32(1))
        );
        vm.prank(relayer);
        book.ingest(MOCK, _envelope(txBytes, HEIGHT, 17), ESCROW, _topics(T_RECOGNIZED), cs);
    }

    function _assign(bytes32 ref, GpuTypes.FacilityId f, uint32 rev) internal {
        bytes32 fk = book.facilityKey(f);
        bytes memory data = abi.encode(rev);
        _ingestOne(T_ASSIGNED, _log(T_ASSIGNED, ACCOUNT_A, ref, fk, 4, data), _claim(0, ACCOUNT_A, ref, fk, data));
    }

    function _checkpoint(GpuTypes.AccountKey acct, uint64 seq, uint32 latestRev, uint256 open, uint256 paidCum)
        internal
    {
        bytes memory data = abi.encode(seq, latestRev, open, paidCum);
        _ingestOne(T_CHECKPOINT, _log(T_CHECKPOINT, acct, 0, 0, 2, data), _claim(0, acct, 0, 0, data));
    }

    function _borrow(uint256 amount) internal {
        vm.prank(borrowerWallet);
        mgr.borrow(FA, amount, amount);
    }

    // ================================================================== positive path

    function test_happyPath_drawWithNativelyProvenBase() public {
        _readyA();
        GpuTypes.DrawEvaluation memory ev = mgr.evaluateDraw(FA, 0);
        assertEq(ev.eligibleReceivables, 12_000e6);
        assertEq(ev.receivableLimit, 6000e6); // 50% advance
        assertEq(ev.availableDraw, 6000e6);

        uint256 before = loan.balanceOf(borrowerWallet);
        vm.expectEmit(true, false, false, true, address(mgr));
        emit ICreditFacilityManager.Borrowed(FA, 5000e6, 5000e6, keccak256("decision-1"));
        _borrow(5000e6);
        assertEq(loan.balanceOf(borrowerWallet) - before, 5000e6);
        assertEq(ledger.view_(FA).principal, 5000e6);
        assertEq(ctl.reservedOf(FA), 0, "reservation consumed atomically");
        assertEq(vault.availableCash(), LP_CASH - 5000e6);
        assertEq(mgr.evaluateDraw(FA, 0).availableDraw, 1000e6);
        assertEq(uint8(mgr.state(FA)), uint8(GpuTypes.FacilityState.ACTIVE));
        assertEq(uint8(ledger.view_(FA).state), uint8(GpuTypes.FacilityState.ACTIVE), "ledger mirrors state");
    }

    function test_repayFor_byThirdParty_excessRefundableToBorrowerOnly() public {
        _readyA();
        _borrow(5000e6);
        vm.warp(block.timestamp + 365 days);
        uint256 debt = ledger.legalDebtAt(FA, uint64(block.timestamp));
        assertEq(debt, 5500e6); // 10% simple, principal only
        loan.mint(mallory, 6000e6);
        vm.startPrank(mallory);
        loan.approve(address(mgr), 6000e6);
        GpuTypes.RepayResult memory r = mgr.repayFor(FA, 6000e6);
        vm.stopPrank();
        assertEq(r.applied, 5500e6);
        assertEq(r.interestPaid, 500e6);
        assertEq(r.principalPaid, 5000e6);
        assertEq(r.excess, 500e6);
        assertEq(r.newDebt, 0);
        assertEq(uint8(mgr.state(FA)), uint8(GpuTypes.FacilityState.REPAID));
        assertEq(vault.refundableOf(FA), 500e6);
        assertEq(vault.nav(), LP_CASH + 500e6, "interest is LP income; excess is not");
        // only the linked wallet may claim the refund
        vm.prank(mallory);
        vm.expectRevert(abi.encodeWithSelector(ICreditFacilityManager.NotBorrower.selector, FA, mallory));
        mgr.claimRefund(FA);
        vm.prank(borrowerWallet);
        mgr.claimRefund(FA);
        assertEq(vault.refundableOf(FA), 0);
    }

    function test_twoStepReservation_executeWithinTtl() public {
        _readyA();
        vm.prank(borrowerWallet);
        bytes32 id = mgr.reserveDraw(FA, 4000e6, 1 hours);
        assertEq(ctl.reservedOf(FA), 4000e6);
        assertEq(mgr.evaluateDraw(FA, 0).availableDraw, 2000e6, "reservation counts against availability");
        vm.prank(borrowerWallet);
        mgr.executeReservedDraw(id, 4000e6);
        assertEq(ledger.view_(FA).principal, 4000e6);
        assertEq(ctl.reservedOf(FA), 0);
    }

    // ================================================================== rejections

    function test_frontRun_attackerCannotBorrowOrAnchor() public {
        _readyA();
        vm.prank(mallory);
        vm.expectRevert(abi.encodeWithSelector(ICreditFacilityManager.NotBorrower.selector, FA, mallory));
        mgr.borrow(FA, 1000e6, 0);
        // a non-underwriter signature over a perfectly formed authorization is rejected by the verifier
        GpuTypes.CreditAuthorization memory a = _auth(FA, 50_000e6);
        GpuTypes.SupplementaryAssertion memory s =
            _assertion(0xBAD, GpuTypes.AssertionPurpose.CREDIT_APPROVAL, keccak256(abi.encode(a)), 99, 0, 10 minutes);
        vm.prank(mallory);
        vm.expectRevert(
            abi.encodeWithSelector(IAuthorizationVerifier.KeyEpochInvalid.selector, vm.addr(0xBAD), uint64(0))
        );
        mgr.anchorAuthorization(a, s);
    }

    function test_duplicateApprovalNonce_rejected() public {
        _openFacility(FA, 50_000e6);
        GpuTypes.CreditAuthorization memory a = _auth(FA, 50_000e6);
        GpuTypes.SupplementaryAssertion memory s = _assertion(
            UNDERWRITER_KEY, GpuTypes.AssertionPurpose.CREDIT_APPROVAL, keccak256(abi.encode(a)), 7, 0, 10 minutes
        );
        vm.prank(underwriter);
        mgr.anchorAuthorization(a, s);
        vm.prank(underwriter);
        vm.expectRevert(
            abi.encodeWithSelector(
                IAuthorizationVerifier.NonceAlreadyUsed.selector,
                underwriter,
                GpuTypes.AssertionPurpose.CREDIT_APPROVAL,
                uint64(7)
            )
        );
        mgr.anchorAuthorization(a, s);
    }

    function test_duplicateReservation_cannotBeExecutedTwice() public {
        _readyA();
        vm.prank(borrowerWallet);
        bytes32 id = mgr.reserveDraw(FA, 3000e6, 1 hours);
        vm.prank(borrowerWallet);
        mgr.executeReservedDraw(id, 3000e6);
        vm.prank(borrowerWallet);
        vm.expectRevert(
            abi.encodeWithSelector(
                IExposureController.ReservationNotActive.selector, id, IExposureController.ReservationState.CONSUMED
            )
        );
        mgr.executeReservedDraw(id, 3000e6);
        assertEq(ledger.view_(FA).principal, 3000e6);
    }

    function test_capRace_secondDrawBeyondHeadroomReverts() public {
        _readyA();
        _borrow(4000e6);
        // availability = min(limit-debt, receivableLimit-debt=2000, headroom, cash) = 2000
        vm.prank(borrowerWallet);
        vm.expectRevert(abi.encodeWithSelector(ICreditFacilityManager.ExceedsAvailableDraw.selector, 2001e6, 2000e6));
        mgr.borrow(FA, 2001e6, 0);
        _borrow(2000e6);
        assertEq(ledger.view_(FA).principal, 6000e6);
    }

    function test_stalledDraw_expiredReservationRejected() public {
        _readyA();
        vm.prank(borrowerWallet);
        bytes32 id = mgr.reserveDraw(FA, 3000e6, 10 minutes);
        vm.warp(block.timestamp + 11 minutes);
        vm.prank(borrowerWallet);
        vm.expectRevert(
            abi.encodeWithSelector(IExposureController.ReservationExpired.selector, id, uint64(T0 + 10 minutes))
        );
        mgr.executeReservedDraw(id, 3000e6);
        assertEq(ledger.view_(FA).principal, 0);
        // explicit on-chain expiry releases the headroom; off-chain timeouts release nothing
        assertEq(ctl.reservedOf(FA), 3000e6);
        ctl.expireReservation(id);
        assertEq(ctl.reservedOf(FA), 0);
    }

    function test_insufficientVaultLiquidity() public {
        _readyA();
        uint256 shares = vault.balanceOf(lp);
        vm.prank(lp);
        vault.withdraw(shares, 0); // LP pulls all cash
        assertEq(vault.availableCash(), 0);
        vm.prank(borrowerWallet);
        vm.expectRevert(abi.encodeWithSelector(ICreditFacilityManager.ExceedsAvailableDraw.selector, 1000e6, 0));
        mgr.borrow(FA, 1000e6, 0);
    }

    function test_wrongFacilityAuthorization_rejected() public {
        _openFacility(FA, 50_000e6);
        _openFacility(FB, 50_000e6);
        GpuTypes.CreditAuthorization memory a = _auth(FB, 50_000e6);
        // signed for FB but the underwriter anchors it on FA? The subject binds facilityId: anchoring on FA is
        // impossible because `auth.facilityId` is FB; the only "wrong facility" attack is a limit/asset mismatch.
        a.limit = 60_000e6; // does not match the exposure authorization (50,000)
        GpuTypes.SupplementaryAssertion memory s = _assertion(
            UNDERWRITER_KEY,
            GpuTypes.AssertionPurpose.CREDIT_APPROVAL,
            keccak256(abi.encode(a)),
            uwNonce++,
            0,
            10 minutes
        );
        vm.prank(underwriter);
        vm.expectRevert(
            abi.encodeWithSelector(CreditFacilityManager.ExposureAuthorizationMismatch.selector, FB, "limit")
        );
        mgr.anchorAuthorization(a, s);
    }

    function test_wrongBorrowerWallet_cannotOpenOrDraw() public {
        vm.prank(underwriter);
        book.registerFacility(FA, BORROWER_A, MOCK, _usdc());
        vm.prank(underwriter);
        vm.expectRevert(abi.encodeWithSelector(CreditFacilityManager.WalletNotLinked.selector, BORROWER_A, mallory));
        mgr.openFacility(FA, BORROWER_A, mallory, _terms(0), AGR_A, 1);
    }

    function test_lateMinedExpiredApproval_rejected() public {
        _readyA();
        vm.warp(T0 + 30 days); // authorization validUntil reached
        vm.prank(borrowerWallet);
        vm.expectRevert(abi.encodeWithSelector(ICreditFacilityManager.AuthorizationMissingOrExpired.selector, FA));
        mgr.borrow(FA, 1000e6, 0);
    }

    function test_expiredAnchor_cannotBeAnchored() public {
        _openFacility(FA, 50_000e6);
        GpuTypes.CreditAuthorization memory a = _auth(FA, 50_000e6);
        a.validUntil = uint64(block.timestamp);
        GpuTypes.SupplementaryAssertion memory s = _assertion(
            UNDERWRITER_KEY,
            GpuTypes.AssertionPurpose.CREDIT_APPROVAL,
            keccak256(abi.encode(a)),
            uwNonce++,
            0,
            10 minutes
        );
        vm.prank(underwriter);
        vm.expectRevert(abi.encodeWithSelector(ICreditFacilityManager.AuthorizationMissingOrExpired.selector, FA));
        mgr.anchorAuthorization(a, s);
    }

    function test_partialTokenDelivery_rollsBackEverything() public {
        _readyA();
        loan.setShortfall(1); // vault "sends" 5000, wallet receives 5000 - 1
        vm.prank(borrowerWallet);
        vm.expectRevert(abi.encodeWithSelector(CreditFacilityManager.InsufficientReceived.selector, 5000e6, 5000e6 - 1));
        mgr.borrow(FA, 5000e6, 5000e6);
        assertEq(ledger.view_(FA).principal, 0, "ledger draw rolled back");
        assertEq(ctl.reservedOf(FA), 0, "reservation rolled back");
        assertEq(vault.availableCash(), LP_CASH, "vault cash untouched");
        assertEq(mgr.evaluateDraw(FA, 0).availableDraw, 6000e6);
    }

    function test_controlVersionBumpedAfterAnchor_rejected() public {
        _readyA();
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
        vm.prank(borrowerWallet);
        vm.expectRevert(abi.encodeWithSelector(ICreditFacilityManager.ControlInsufficientOrStale.selector, FA));
        mgr.borrow(FA, 1000e6, 0);
    }

    function test_controlObservationStale_rejected() public {
        _readyA();
        vm.warp(block.timestamp + 2 days); // observation max age 1 day
        vm.prank(borrowerWallet);
        vm.expectRevert(abi.encodeWithSelector(ICreditFacilityManager.ControlInsufficientOrStale.selector, FA));
        mgr.borrow(FA, 1000e6, 0);
    }

    function test_policyVersionChanged_rejected() public {
        _readyA();
        _publishPolicy(POLICY_V2, 10_000e6, 10_000e6, 20_000e6, 20_000e6);
        vm.prank(borrowerWallet);
        vm.expectRevert(abi.encodeWithSelector(CreditFacilityManager.PolicyVersionStale.selector, POLICY_V1));
        mgr.borrow(FA, 1000e6, 0);
        // a fresh anchor on the old policy is also refused
        GpuTypes.CreditAuthorization memory a = _auth(FA, 50_000e6);
        GpuTypes.SupplementaryAssertion memory s = _assertion(
            UNDERWRITER_KEY,
            GpuTypes.AssertionPurpose.CREDIT_APPROVAL,
            keccak256(abi.encode(a)),
            uwNonce++,
            0,
            10 minutes
        );
        vm.prank(underwriter);
        vm.expectRevert(abi.encodeWithSelector(CreditFacilityManager.PolicyVersionStale.selector, POLICY_V1));
        mgr.anchorAuthorization(a, s);
    }

    function test_manifestMismatch_rejected() public {
        _openFacility(FA, 50_000e6);
        GpuTypes.CreditAuthorization memory a = _auth(FA, 50_000e6);
        a.manifestHash = keccak256("some-other-manifest");
        GpuTypes.SupplementaryAssertion memory s = _assertion(
            UNDERWRITER_KEY,
            GpuTypes.AssertionPurpose.CREDIT_APPROVAL,
            keccak256(abi.encode(a)),
            uwNonce++,
            0,
            10 minutes
        );
        vm.prank(underwriter);
        vm.expectRevert(
            abi.encodeWithSelector(
                ICreditFacilityManager.AuthorizationManifestMismatch.selector, MANIFEST, a.manifestHash
            )
        );
        mgr.anchorAuthorization(a, s);
    }

    function test_noNativeEvidence_signatureAloneCannotDraw() public {
        _openFacility(FA, 50_000e6);
        _anchor(_auth(FA, 50_000e6));
        _activate(FA);
        // underwriter approved 50,000 and the facility is ACTIVE, but no receivable was natively proven
        vm.prank(borrowerWallet);
        vm.expectRevert(abi.encodeWithSelector(ICreditFacilityManager.NativeEvidenceRequired.selector, FA));
        mgr.borrow(FA, 1e6, 0);
        assertEq(mgr.evaluateDraw(FA, 0).availableDraw, 0);
    }

    function test_expiredEvidence_rejected() public {
        _readyA();
        vm.warp(block.timestamp + 8 days); // claim validUntil = +7d ⇒ eligible 0 / evidence expired
            // re-observe control so the only failing gate is evidence
        vm.prank(servicer);
        control.observe(AGR_A, GpuTypes.ControlGrade.E2, ESCROW);
        vm.prank(borrowerWallet);
        vm.expectRevert(abi.encodeWithSelector(ICreditFacilityManager.NativeEvidenceRequired.selector, FA));
        mgr.borrow(FA, 1e6, 0);
    }

    function test_pausedDraws_blockBorrow_notRepayFor() public {
        _readyA();
        _borrow(2000e6);
        vm.prank(guardian);
        mgr.pauseDraws(true);
        assertTrue(mgr.drawsPaused());
        vm.prank(borrowerWallet);
        vm.expectRevert(ICreditFacilityManager.DrawsArePaused.selector);
        mgr.borrow(FA, 1000e6, 0);
        loan.mint(borrowerWallet, 1000e6);
        vm.startPrank(borrowerWallet);
        loan.approve(address(mgr), 1000e6);
        GpuTypes.RepayResult memory r = mgr.repayFor(FA, 1000e6);
        vm.stopPrank();
        assertEq(r.principalPaid, 1000e6);
        assertEq(ledger.view_(FA).principal, 1000e6);
        // per-facility freeze by guardian also blocks draws but not repayment
        vm.prank(guardian);
        mgr.pauseDraws(false);
        vm.prank(guardian);
        mgr.freezeDraws(FA, "evidence_stale");
        vm.prank(borrowerWallet);
        vm.expectRevert(
            abi.encodeWithSelector(
                CreditFacilityManager.FacilityNotActive.selector, FA, GpuTypes.FacilityState.DRAW_FROZEN
            )
        );
        mgr.borrow(FA, 100e6, 0);
        bytes32 guardianRole = roles.GUARDIAN();
        vm.prank(mallory);
        vm.expectRevert(abi.encodeWithSelector(CreditFacilityManager.NotRole.selector, guardianRole, mallory));
        mgr.pauseDraws(true);
    }

    function test_noTestnetGrantOrLimitIncreaseSelectors() public view {
        bytes4[5] memory forbidden = [
            bytes4(keccak256("grantTestnetCredit(bytes32,uint256)")),
            bytes4(keccak256("increaseLimit(bytes32,uint256)")),
            bytes4(keccak256("setLimit(bytes32,uint256)")),
            bytes4(keccak256("pauseRepayments(bool)")),
            bytes4(keccak256("borrowTo(bytes32,address,uint256)"))
        ];
        bytes memory code = address(mgr).code;
        for (uint256 i = 0; i < forbidden.length; i++) {
            assertFalse(_containsSelector(code, forbidden[i]), "forbidden entry point present");
        }
        assertTrue(_containsSelector(code, ICreditFacilityManager.repayFor.selector));
    }

    function _containsSelector(bytes memory code, bytes4 sel) internal pure returns (bool) {
        // PUSH4 <selector> appears in the dispatcher of every externally callable function
        for (uint256 i = 0; i + 5 <= code.length; i++) {
            if (
                code[i] == 0x63 && code[i + 1] == sel[0] && code[i + 2] == sel[1] && code[i + 3] == sel[2]
                    && code[i + 4] == sel[3]
            ) {
                return true;
            }
        }
        return false;
    }

    // ================================================================== state machine parity (GPU-013 JSON)

    function _stateOf(string memory s) internal pure returns (GpuTypes.FacilityState) {
        bytes32 h = keccak256(bytes(s));
        if (h == keccak256("DRAFT")) return GpuTypes.FacilityState.DRAFT;
        if (h == keccak256("UNDER_REVIEW")) return GpuTypes.FacilityState.UNDER_REVIEW;
        if (h == keccak256("CONTROL_PENDING")) return GpuTypes.FacilityState.CONTROL_PENDING;
        if (h == keccak256("ACTIVE")) return GpuTypes.FacilityState.ACTIVE;
        if (h == keccak256("DRAW_FROZEN")) return GpuTypes.FacilityState.DRAW_FROZEN;
        if (h == keccak256("DELINQUENT")) return GpuTypes.FacilityState.DELINQUENT;
        if (h == keccak256("DEFAULTED")) return GpuTypes.FacilityState.DEFAULTED;
        if (h == keccak256("RECOVERY")) return GpuTypes.FacilityState.RECOVERY;
        if (h == keccak256("REPAID")) return GpuTypes.FacilityState.REPAID;
        if (h == keccak256("RELEASED")) return GpuTypes.FacilityState.RELEASED;
        if (h == keccak256("CLOSED_WITH_LOSS")) return GpuTypes.FacilityState.CLOSED_WITH_LOSS;
        revert("unknown state");
    }

    function test_transitionTable_matchesGpu013Json() public view {
        bool[11][11] memory allowed;
        uint256 n;
        while (vm.keyExistsJson(transitionsJson, string.concat(".transitions[", vm.toString(n), "]"))) {
            string memory p = string.concat(".transitions[", vm.toString(n), "]");
            GpuTypes.FacilityState from = _stateOf(vm.parseJsonString(transitionsJson, string.concat(p, ".from")));
            GpuTypes.FacilityState to = _stateOf(vm.parseJsonString(transitionsJson, string.concat(p, ".to")));
            allowed[uint8(from)][uint8(to)] = true;
            n++;
        }
        assertEq(n, 16, "transition count in the JSON");
        for (uint8 a = 0; a < 11; a++) {
            for (uint8 b = 0; b < 11; b++) {
                if (a == b) continue; // self-transitions (draw/repay_for) are actions, not state changes
                assertEq(
                    mgr.isTransitionAllowed(GpuTypes.FacilityState(a), GpuTypes.FacilityState(b)),
                    allowed[a][b],
                    string.concat("parity ", vm.toString(a), "->", vm.toString(b))
                );
            }
        }
    }

    function test_transitions_authoritiesAndGuards() public {
        _openFacility(FA, 50_000e6);
        // registrar only for onboarding_complete
        vm.prank(underwriter);
        vm.expectRevert();
        mgr.transition(FA, GpuTypes.FacilityState.UNDER_REVIEW, "onboarding_complete");
        vm.prank(registrar);
        mgr.transition(FA, GpuTypes.FacilityState.UNDER_REVIEW, "onboarding_complete");
        // credit_decision_approved needs an anchored, valid decision
        vm.prank(underwriter);
        vm.expectRevert(abi.encodeWithSelector(ICreditFacilityManager.AuthorizationMissingOrExpired.selector, FA));
        mgr.transition(FA, GpuTypes.FacilityState.CONTROL_PENDING, "credit_decision_approved");
        _anchor(_auth(FA, 50_000e6));
        vm.prank(underwriter);
        mgr.transition(FA, GpuTypes.FacilityState.CONTROL_PENDING, "credit_decision_approved");
        // skipping a state is illegal
        vm.prank(servicer);
        vm.expectRevert(
            abi.encodeWithSelector(
                ICreditFacilityManager.IllegalTransition.selector,
                GpuTypes.FacilityState.CONTROL_PENDING,
                GpuTypes.FacilityState.REPAID
            )
        );
        mgr.transition(FA, GpuTypes.FacilityState.REPAID, "x");
        // control must be usable at E2 to activate: revoke first ⇒ rejected
        vm.prank(guardian);
        control.revoke(AGR_A, "incident");
        vm.prank(servicer);
        vm.expectRevert(abi.encodeWithSelector(ICreditFacilityManager.ControlInsufficientOrStale.selector, FA));
        mgr.transition(FA, GpuTypes.FacilityState.ACTIVE, "control_grade_e2_effective");
    }

    function test_releaseRequiresZeroDebt_andRepaidIsSystemOnly() public {
        _readyA();
        _borrow(1000e6);
        // nobody can force REPAID while debt is outstanding (system-only transition)
        vm.prank(servicer);
        vm.expectRevert();
        mgr.transition(FA, GpuTypes.FacilityState.REPAID, "debt_zero");
        loan.mint(borrowerWallet, 1000e6);
        vm.startPrank(borrowerWallet);
        loan.approve(address(mgr), 1000e6);
        mgr.repayFor(FA, 1000e6);
        vm.stopPrank();
        assertEq(uint8(mgr.state(FA)), uint8(GpuTypes.FacilityState.REPAID));
        vm.prank(treasury);
        mgr.transition(FA, GpuTypes.FacilityState.RELEASED, "release_conditions_met");
        assertEq(uint8(mgr.state(FA)), uint8(GpuTypes.FacilityState.RELEASED));
    }

    function test_profileMismatch_rejectedAtOpen() public {
        vm.prank(underwriter);
        book.registerFacility(FA, BORROWER_A, MOCK, _usdc());
        IDebtLedger.Terms memory t = _terms(0);
        t.executionProfile = GpuTypes.ExecutionProfile.PRODUCTION;
        vm.prank(underwriter);
        vm.expectRevert(
            abi.encodeWithSelector(
                ICreditFacilityManager.ProfileMismatch.selector,
                GpuTypes.ExecutionProfile.LOCAL_MOCK,
                GpuTypes.ExecutionProfile.PRODUCTION
            )
        );
        mgr.openFacility(FA, BORROWER_A, borrowerWallet, t, AGR_A, 1);
    }

    function test_newAnchorSupersedes_lowerLimitNeverErasesDebt() public {
        _readyA();
        _borrow(5000e6);
        vm.prank(underwriter);
        ctl.setAuthorization(FA, 1000e6, POLICY_V1, AGR_A, 1, T0 + 30 days);
        GpuTypes.CreditAuthorization memory a = _auth(FA, 1000e6);
        a.decisionHash = keccak256("decision-2");
        _anchor(a);
        assertEq(mgr.anchor(FA).epoch, 2);
        assertEq(ledger.view_(FA).principal, 5000e6, "debt untouched by the lower limit");
        assertEq(mgr.evaluateDraw(FA, 0).availableDraw, 0);
        vm.prank(borrowerWallet);
        vm.expectRevert(abi.encodeWithSelector(ICreditFacilityManager.ExceedsAvailableDraw.selector, 1e6, 0));
        mgr.borrow(FA, 1e6, 0);
    }
}
