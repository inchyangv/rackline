// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import { INativeQueryVerifier } from "@gluwa/asc-contracts/contracts/write-ability/common/INativeQueryVerifier.sol";

/**
 * @title GpuTypes
 * @notice Common typed identifiers, enums and structs for the Rackline GPU receivables facility (GPU-029).
 * @dev Enum member order mirrors `config/gpu/schema/domain-v1.schema.json` exactly; `test/gpu/GPU029InterfacesTest`
 *      asserts ordinal parity with `test/fixtures/gpu/enums-v1.json`. No Bitcoin-era fields (sats/txid/vout) exist
 * here.
 *
 *      Accounting ownership:
 *      - amounts are integer base units of the facility's loan asset unless a struct carries its own `AssetRef`;
 *      - a `VerifiedSourceEvent` proves only that a log occurred on the source chain (R2-D05);
 *      - a `SupplementaryAssertion` is an auxiliary signature and never a source fact (R2-D04);
 *      - a `CreditAuthorization` is an underwriting decision anchor, never a limit by itself.
 */
library GpuTypes {
    // ------------------------------------------------------------------ enums (order = domain-v1 schema)

    enum ExecutionProfile {
        LOCAL_MOCK,
        NATIVE_TESTNET,
        PRODUCTION
    }

    enum VerificationMethod {
        ATTESTCOIN_NATIVE,
        LOCAL_MOCK,
        OFFCHAIN_ASSERTION
    }

    enum NativeStatus {
        NOT_REQUIRED,
        NOT_REQUESTED,
        OBSERVED,
        WAITING_ATTESTATION,
        PROOF_READY,
        SUBMITTED,
        NATIVE_ACCEPTED,
        CONSUMED,
        INVALID,
        UNSUPPORTED,
        EXPIRED
    }

    enum EarningsProvenance {
        UNCLASSIFIED,
        PROVIDER_SETTLEMENT,
        PROVIDER_INCENTIVE,
        SELF_TRANSFER,
        THIRD_PARTY_UNKNOWN,
        REFUND_OR_REVERSAL,
        SIMULATED
    }

    enum ControlGrade {
        E0,
        E1,
        E2,
        E3
    }

    enum CashState {
        NONE,
        SOURCE_ESCROW,
        IN_FLIGHT,
        DESTINATION_RECEIVED,
        ALLOCATED,
        RETURNED
    }

    enum FacilityState {
        DRAFT,
        UNDER_REVIEW,
        CONTROL_PENDING,
        ACTIVE,
        DRAW_FROZEN,
        DELINQUENT,
        DEFAULTED,
        RECOVERY,
        REPAID,
        RELEASED,
        CLOSED_WITH_LOSS
    }

    enum EvidenceMeaning {
        OBLIGATION_RECOGNIZED,
        ASSIGNMENT_RECOGNIZED,
        CORRECTION,
        PAYOUT,
        PAYMENT_CANCELLED
    }

    enum Trust {
        PROVEN,
        ASSERTED,
        OBSERVED,
        CLAIMED
    }

    /// @notice Purposes of auxiliary EIP-712 signatures (docs/gpu/permissions-and-states.md §2).
    enum AssertionPurpose {
        WALLET_LINK,
        AGREEMENT_CONSENT,
        CREDIT_APPROVAL,
        CONTROL_ATTESTATION,
        RELAY,
        TREASURY_OP
    }

    // ------------------------------------------------------------------ identifiers

    /// @dev Off-chain ULIDs are carried on-chain as `keccak256(bytes(ulid))`.
    type FacilityId is bytes32;
    type ProviderId is bytes32; // keccak256(bytes(providerSlug))
    type AccountKey is bytes32; // keccak256(bytes(providerSlug ":" externalAccountId))
    type SourceEventId is bytes32; // keccak256(abi.encode(keccak256(envId), chainKey, height, txIndex, logOrdinal))
    type EconomicEventId is bytes32; // keccak256(bytes(economicEventId string))

    // ------------------------------------------------------------------ assets / chains

    /// @notice Asset reference; `token == address(0)` means the chain's native coin.
    struct AssetRef {
        uint64 chainId;
        address token;
        uint8 decimals;
    }

    /// @notice Source chain binding fixed by the environment manifest (docs/gpu/attestcoin/environment.md).
    struct SourceChainRef {
        bytes32 envIdHash; // keccak256(bytes(envId)), e.g. "cc3-testnet"
        uint64 chainKey; // Creditcoin-internal key (ChainInfo), not the EVM chain id
        uint64 chainId; // EVM chain id of the source chain
        uint8 encoding; // SDK EncodingVersion; only 1 is supported
        bytes32 manifestHash; // sha256 of the manifest the verifier was deployed with
    }

    /// @notice Proof-bound position of one receipt log (GPU-076 §3). `logOrdinal` is the index inside the receipt's
    ///         log array, never the RPC block-global logIndex.
    struct SourceEventLocator {
        uint64 chainKey;
        uint64 height;
        uint64 txIndex; // computed on-chain by the precompile's calculateTxIndex
        uint32 logOrdinal;
    }

    // ------------------------------------------------------------------ native proof types (R2-D02)

    /// @notice Untrusted proof input in the official BlockProver shape (SDK 0.18.0 / asc-contracts 0.2.1). Nothing in
    ///         it is trusted until `INativeQueryVerifier.verifyAndEmit` succeeds on exactly these bytes.
    struct NativeProofEnvelope {
        uint64 chainKey;
        uint64 height;
        bytes encodedTransaction;
        bytes32 merkleRoot;
        INativeQueryVerifier.MerkleProofEntry[] siblings;
        bytes32 lowerEndpointDigest;
        bytes32[] continuityRoots;
    }

    /// @notice One receipt log extracted from natively verified bytes. Proves occurrence only.
    struct VerifiedSourceEvent {
        SourceEventId id;
        SourceEventLocator locator;
        address emitter;
        bytes32 topic0;
        bytes32[] topics; // topics[0] == topic0
        bytes data;
        bytes32 manifestHash;
        address verifier; // app adapter contract that performed the native call
    }

    // ------------------------------------------------------------------ auxiliary signatures (R2-D04)

    /// @notice Auxiliary EIP-712 signature. Creates wallet links, consents, approvals — never source facts.
    struct SupplementaryAssertion {
        AssertionPurpose purpose;
        bytes32 subject; // id the assertion is about (facility, agreement version hash, wallet link hash)
        address signer;
        uint64 keyEpoch;
        uint64 nonce;
        uint64 issuedAt;
        uint64 expiresAt;
        bytes signature; // ECDSA or ERC-1271 payload
    }

    /// @notice Underwriter decision anchor recorded on-chain; `borrow` checks it, it never grants a limit alone.
    struct CreditAuthorization {
        FacilityId facilityId;
        bytes32 decisionHash; // hash of the off-chain CreditDecision (inputs, policy version, evidence set)
        uint256 limit; // loan asset base units
        uint64 validUntil;
        bytes32 policyVersionId;
        bytes32 manifestHash; // evidence must have been verified under this manifest
        bytes32 controlAgreementVersionHash;
    }

    // ------------------------------------------------------------------ ledger views

    /// @notice Facility ledger snapshot (single ledger for manager and vault; docs/gpu/accounting.md §1).
    struct FacilityLedgerView {
        FacilityState state;
        AssetRef loanAsset;
        uint256 principal;
        uint256 unpaidInterest;
        uint256 fees;
        uint256 reservedDraws;
        uint32 rateBps;
        uint64 lastAccrualAt;
        uint64 maturityAt;
        bytes32 termsVersionId;
        bytes32 policyVersionId;
        ExecutionProfile executionProfile;
    }

    /// @notice Result of a `repayFor`. `requested` is what the caller asked, `received` what the vault actually got
    ///         (fee-on-transfer aware), `applied` what reduced debt, `excess` what is owed back to the borrower.
    struct RepayResult {
        uint256 requested;
        uint256 received;
        uint256 applied;
        uint256 feePaid;
        uint256 interestPaid;
        uint256 principalPaid;
        uint256 excess;
        uint256 newDebt;
    }

    /// @notice Borrowing-base evaluation at draw time (PIVOT §6.3).
    struct DrawEvaluation {
        uint256 eligibleReceivables;
        uint256 receivableLimit;
        uint256 facilityLimit;
        uint256 facilityRoom;
        uint256 headroom; // min of concentration headrooms
        uint256 vaultCash;
        uint256 availableDraw;
        uint64 evidenceValidUntil;
        uint64 checkpointAge;
    }
}
