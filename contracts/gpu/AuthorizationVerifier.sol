// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import { IERC1271 } from "./interfaces/IERC1271.sol";
import { GpuTypes } from "./types/GpuTypes.sol";
import { IAuthorizationVerifier } from "./interfaces/IAuthorizationVerifier.sol";
import { IProtocolRoles } from "./interfaces/IProtocolRoles.sol";

/**
 * @title AuthorizationVerifier
 * @notice Verifies auxiliary EIP-712 / ERC-1271 assertions (GPU-030/031; docs/gpu/permissions-and-states.md §2).
 *         Every assertion is bound to: this contract's domain (name, version, chainId, verifyingContract), one
 *         purpose, one subject, the signer, a per-(signer, purpose) nonce, issue/expiry times and a key epoch.
 *         It never establishes source facts (R2-D04): a valid assertion is an input to onboarding/underwriting,
 *         not evidence.
 * @dev Role-bound purposes (CREDIT_APPROVAL -> UNDERWRITER, TREASURY_OP -> TREASURY, RELAY -> RELAYER,
 *      CONTROL_ATTESTATION -> REGISTRAR) require the signer to hold the role and the epoch to be valid.
 *      Borrower-signed purposes (WALLET_LINK, AGREEMENT_CONSENT) require keyEpoch == 0.
 */
contract AuthorizationVerifier is IAuthorizationVerifier {
    bytes32 public constant ASSERTION_TYPEHASH = keccak256(
        "Assertion(uint8 purpose,bytes32 subject,address signer,uint64 keyEpoch,uint64 nonce,uint64 issuedAt,uint64 expiresAt)"
    );
    bytes32 private constant _DOMAIN_TYPEHASH =
        keccak256("EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)");
    bytes32 private constant _NAME_HASH = keccak256("Rackline Authorization");
    bytes32 private constant _VERSION_HASH = keccak256("1");
    /// @dev secp256k1n / 2: signatures with s above this are malleable and rejected (EIP-2).
    uint256 private constant _HALF_ORDER = 0x7FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF5D576E7357A4501DDFE92F46681B20A0;

    IProtocolRoles public immutable ROLES;
    uint64 public immutable MAX_TTL;

    mapping(address signer => mapping(GpuTypes.AssertionPurpose purpose => mapping(uint64 nonce => bool))) private
        _used;

    constructor(IProtocolRoles roles, uint64 maxTtl) {
        ROLES = roles;
        MAX_TTL = maxTtl;
    }

    /// @dev Computed on the fly so a chain fork (different chainid) invalidates old signatures.
    function domainSeparator() public view override returns (bytes32) {
        return keccak256(abi.encode(_DOMAIN_TYPEHASH, _NAME_HASH, _VERSION_HASH, block.chainid, address(this)));
    }

    function hashAssertion(GpuTypes.SupplementaryAssertion calldata a) public view override returns (bytes32) {
        bytes32 structHash = keccak256(
            abi.encode(
                ASSERTION_TYPEHASH, uint8(a.purpose), a.subject, a.signer, a.keyEpoch, a.nonce, a.issuedAt, a.expiresAt
            )
        );
        return keccak256(abi.encodePacked("\x19\x01", domainSeparator(), structHash));
    }

    function nonceUsed(address signer, GpuTypes.AssertionPurpose purpose, uint64 nonce) external view returns (bool) {
        return _used[signer][purpose][nonce];
    }

    function isValid(GpuTypes.SupplementaryAssertion calldata a, GpuTypes.AssertionPurpose purpose, bytes32 subject)
        external
        view
        override
        returns (bool)
    {
        (bool ok,) = _check(a, purpose, subject);
        return ok;
    }

    function verifyAndConsume(
        GpuTypes.SupplementaryAssertion calldata a,
        GpuTypes.AssertionPurpose purpose,
        bytes32 subject
    ) external override {
        (bool ok, bytes memory err) = _check(a, purpose, subject);
        if (!ok) {
            // bubble the specific custom error selected in _check
            assembly {
                revert(add(err, 32), mload(err))
            }
        }
        _used[a.signer][a.purpose][a.nonce] = true;
        emit NonceConsumed(a.signer, a.purpose, a.nonce);
    }

    // ------------------------------------------------------------------ internal

    function _roleFor(GpuTypes.AssertionPurpose purpose) internal view returns (bytes32 role, bool roleBound) {
        if (purpose == GpuTypes.AssertionPurpose.CREDIT_APPROVAL) return (ROLES.UNDERWRITER(), true);
        if (purpose == GpuTypes.AssertionPurpose.TREASURY_OP) return (ROLES.TREASURY(), true);
        if (purpose == GpuTypes.AssertionPurpose.RELAY) return (ROLES.RELAYER(), true);
        if (purpose == GpuTypes.AssertionPurpose.CONTROL_ATTESTATION) return (ROLES.REGISTRAR(), true);
        return (bytes32(0), false);
    }

    /// @dev Returns (true, "") or (false, abi-encoded custom error) so callers can revert with the precise reason.
    function _check(GpuTypes.SupplementaryAssertion calldata a, GpuTypes.AssertionPurpose purpose, bytes32 subject)
        internal
        view
        returns (bool, bytes memory)
    {
        if (a.purpose != purpose) return (false, abi.encodeWithSelector(WrongPurpose.selector, purpose, a.purpose));
        if (a.subject != subject) return (false, abi.encodeWithSelector(BadSignature.selector, a.signer));
        if (a.expiresAt <= block.timestamp) {
            return (false, abi.encodeWithSelector(SignatureExpired.selector, a.expiresAt, uint64(block.timestamp)));
        }
        if (a.expiresAt <= a.issuedAt || a.expiresAt - a.issuedAt > MAX_TTL) {
            return (
                false,
                abi.encodeWithSelector(
                    TtlTooLong.selector, a.expiresAt > a.issuedAt ? a.expiresAt - a.issuedAt : 0, MAX_TTL
                )
            );
        }
        if (_used[a.signer][a.purpose][a.nonce]) {
            return (false, abi.encodeWithSelector(NonceAlreadyUsed.selector, a.signer, a.purpose, a.nonce));
        }
        (bytes32 role, bool roleBound) = _roleFor(purpose);
        if (roleBound) {
            if (!ROLES.hasRole(role, a.signer) || !ROLES.isEpochValid(role, a.keyEpoch)) {
                return (false, abi.encodeWithSelector(KeyEpochInvalid.selector, a.signer, a.keyEpoch));
            }
        } else if (a.keyEpoch != 0) {
            return (false, abi.encodeWithSelector(KeyEpochInvalid.selector, a.signer, a.keyEpoch));
        }
        // EOA (ECDSA, EIP-2 low-s enforced by OZ) or ERC-1271 contract wallet; the signer field is the authority.
        if (!_isValidSignatureNow(a.signer, hashAssertion(a), a.signature)) {
            return (false, abi.encodeWithSelector(BadSignature.selector, a.signer));
        }
        return (true, "");
    }

    /// @dev EOA: 65-byte ECDSA (r,s,v) with low-s and v in {27,28}; recovered address must equal signer.
    ///      Contract wallet: ERC-1271 staticcall must return the magic value. (Self-contained: OpenZeppelin 5.5 needs
    ///      Cancun `mcopy`; this project targets the `london` EVM.)
    function _isValidSignatureNow(address signer, bytes32 digest, bytes calldata signature)
        internal
        view
        returns (bool)
    {
        if (signer.code.length == 0) {
            if (signature.length != 65) return false;
            bytes32 r = bytes32(signature[0:32]);
            bytes32 s = bytes32(signature[32:64]);
            uint8 v = uint8(signature[64]);
            if (uint256(s) > _HALF_ORDER || (v != 27 && v != 28)) return false;
            address recovered = ecrecover(digest, v, r, s);
            return recovered != address(0) && recovered == signer;
        }
        (bool ok, bytes memory ret) = signer.staticcall(abi.encodeCall(IERC1271.isValidSignature, (digest, signature)));
        return ok && ret.length == 32 && abi.decode(ret, (bytes4)) == IERC1271.isValidSignature.selector;
    }
}
