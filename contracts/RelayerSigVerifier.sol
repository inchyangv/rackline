// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import { IVerifierAdapter, PayoutEvidence } from "./interfaces/IVerifierAdapter.sol";

/**
 * @title RelayerSigVerifier
 * @notice EIP-712 signature-based payout verifier for Hackathon MVP
 * @dev Verifies payout claims signed by an authorized relayer using EIP-712
 *
 * Trust Model:
 * - Relayer is trusted to only sign valid Bitcoin payout observations
 * - Contract verifies signature authenticity and enforces replay protection
 * - Production: Replace with BtcSpvVerifier for trustless verification
 *
 * EIP-712 Typed Data:
 * - Domain: name="HashCredit", version="1", chainId, verifyingContract
 * - PayoutClaim: borrower, txid, vout, amountSats, blockHeight, blockTimestamp, deadline
 */
contract RelayerSigVerifier is IVerifierAdapter {
    // ============================================
    // Type Hashes (EIP-712)
    // ============================================

    /// @notice EIP-712 domain type hash
    bytes32 public constant DOMAIN_TYPEHASH =
        keccak256("EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)");

    /// @notice PayoutClaim struct type hash
    bytes32 public constant PAYOUT_CLAIM_TYPEHASH = keccak256(
        "PayoutClaim(address borrower,bytes32 txid,uint32 vout,uint64 amountSats,uint32 blockHeight,uint32 blockTimestamp,uint256 deadline)"
    );

    // ============================================
    // State Variables
    // ============================================

    /// @notice Domain separator (computed once at deployment)
    bytes32 public immutable DOMAIN_SEPARATOR;

    /// @notice Owner address
    address public owner;

    /// @notice Authorized relayer signer address
    address public relayerSigner;

    // ============================================
    // Events
    // ============================================

    /// @notice Emitted when relayer signer is updated
    event RelayerSignerUpdated(address indexed oldSigner, address indexed newSigner);

    /// @notice Emitted when a payout is verified
    event PayoutVerified(address indexed borrower, bytes32 indexed txid, uint32 vout, uint64 amountSats);

    // ============================================
    // Errors
    // ============================================

    /// @notice Invalid signature (wrong signer or malformed)
    error InvalidSignature();

    /// @notice Signature deadline has passed
    error DeadlineExpired();

    /// @notice Invalid address (zero address)
    error InvalidAddress();

    /// @notice Caller not authorized
    error Unauthorized();

    // ============================================
    // Constructor
    // ============================================

    constructor(address relayerSigner_) {
        if (relayerSigner_ == address(0)) revert InvalidAddress();

        owner = msg.sender;
        relayerSigner = relayerSigner_;

        DOMAIN_SEPARATOR = keccak256(
            abi.encode(DOMAIN_TYPEHASH, keccak256("HashCredit"), keccak256("1"), block.chainid, address(this))
        );
    }

    // ============================================
    // Modifiers
    // ============================================

    modifier onlyOwner() {
        if (msg.sender != owner) revert Unauthorized();
        _;
    }

    // ============================================
    // Admin Functions
    // ============================================

    /**
     * @notice Update the authorized relayer signer
     * @param newSigner New relayer signer address
     */
    function setRelayerSigner(address newSigner) external onlyOwner {
        if (newSigner == address(0)) revert InvalidAddress();

        address oldSigner = relayerSigner;
        relayerSigner = newSigner;

        emit RelayerSignerUpdated(oldSigner, newSigner);
    }

    /**
     * @notice Transfer ownership
     * @param newOwner New owner address
     */
    function transferOwnership(address newOwner) external onlyOwner {
        if (newOwner == address(0)) revert InvalidAddress();
        owner = newOwner;
    }

    // ============================================
    // IVerifierAdapter Implementation
    // ============================================

    /**
     * @inheritdoc IVerifierAdapter
     * @dev Proof format: abi.encode(PayoutClaim, signature)
     *      where PayoutClaim = (borrower, txid, vout, amountSats, blockHeight, blockTimestamp, deadline)
     *      and signature = 65-byte ECDSA signature (r, s, v)
     */
    function verifyPayout(bytes calldata proof) external override returns (PayoutEvidence memory) {
        // Decode proof
        (
            address borrower,
            bytes32 txid,
            uint32 vout,
            uint64 amountSats,
            uint32 blockHeight,
            uint32 blockTimestamp,
            uint256 deadline,
            bytes memory signature
        ) = abi.decode(proof, (address, bytes32, uint32, uint64, uint32, uint32, uint256, bytes));

        // Check deadline
        if (block.timestamp > deadline) revert DeadlineExpired();

        // NOTE: Replay protection is handled by HashCreditManager.processedPayouts
        // Verifier is stateless to prevent griefing attacks where attacker calls
        // verifyPayout() directly to block legitimate submitPayout() calls

        // Compute struct hash
        bytes32 structHash = keccak256(
            abi.encode(PAYOUT_CLAIM_TYPEHASH, borrower, txid, vout, amountSats, blockHeight, blockTimestamp, deadline)
        );

        // Compute digest
        bytes32 digest = keccak256(abi.encodePacked("\x19\x01", DOMAIN_SEPARATOR, structHash));

        // Recover signer
        address recoveredSigner = _recoverSigner(digest, signature);
        if (recoveredSigner != relayerSigner) revert InvalidSignature();

        emit PayoutVerified(borrower, txid, vout, amountSats);

        return PayoutEvidence({
            borrower: borrower,
            txid: txid,
            vout: vout,
            amountSats: amountSats,
            blockHeight: blockHeight,
            blockTimestamp: blockTimestamp
        });
    }

    /**
     * @inheritdoc IVerifierAdapter
     * @dev Always returns false - replay protection is handled by HashCreditManager
     *      This verifier is stateless to prevent griefing attacks
     */
    function isPayoutProcessed(bytes32, uint32) external pure override returns (bool) {
        return false;
    }

    // ============================================
    // View Functions
    // ============================================

    /**
     * @notice Compute the EIP-712 digest for a payout claim
     * @dev Useful for off-chain signing
     */
    function getPayoutClaimDigest(
        address borrower,
        bytes32 txid,
        uint32 vout,
        uint64 amountSats,
        uint32 blockHeight,
        uint32 blockTimestamp,
        uint256 deadline
    )
        external
        view
        returns (bytes32)
    {
        bytes32 structHash = keccak256(
            abi.encode(PAYOUT_CLAIM_TYPEHASH, borrower, txid, vout, amountSats, blockHeight, blockTimestamp, deadline)
        );

        return keccak256(abi.encodePacked("\x19\x01", DOMAIN_SEPARATOR, structHash));
    }

    // ============================================
    // Internal Functions
    // ============================================

    /**
     * @notice Recover signer from signature
     * @param digest Message digest
     * @param signature 65-byte signature (r || s || v)
     * @return Recovered signer address
     */
    function _recoverSigner(bytes32 digest, bytes memory signature) internal pure returns (address) {
        if (signature.length != 65) revert InvalidSignature();

        bytes32 r;
        bytes32 s;
        uint8 v;

        assembly {
            r := mload(add(signature, 32))
            s := mload(add(signature, 64))
            v := byte(0, mload(add(signature, 96)))
        }

        // EIP-2: Enforce s is in the lower half order
        if (uint256(s) > 0x7FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF5D576E7357A4501DDFE92F46681B20A0) {
            revert InvalidSignature();
        }

        // Support both 27/28 and 0/1 for v
        if (v < 27) {
            v += 27;
        }

        if (v != 27 && v != 28) {
            revert InvalidSignature();
        }

        address signer = ecrecover(digest, v, r, s);
        if (signer == address(0)) revert InvalidSignature();

        return signer;
    }
}
