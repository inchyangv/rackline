// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import { INativeQueryVerifier } from "@gluwa/asc-contracts/contracts/write-ability/common/INativeQueryVerifier.sol";

/**
 * @title MockBlockProver (TEST_ONLY, LOCAL_MOCK)
 * @notice Records the selector of every call and returns a configurable result. It implements the vendored official
 *         interface exactly (compilation proves the overload set). It is a LOCAL test double: a NATIVE_TESTNET or
 *         PRODUCTION manifest can never point at it (docs/gpu/attestcoin/environment.md, R2-D12).
 */
contract MockBlockProver is INativeQueryVerifier {
    bytes4 public lastSelector;
    bool public result = true;
    bool public revertOnVerify;
    uint64 public txIndexToReturn;

    function setResult(bool r) external {
        result = r;
    }

    function setRevert(bool r) external {
        revertOnVerify = r;
    }

    function setTxIndex(uint64 i) external {
        txIndexToReturn = i;
    }

    function verifyAndEmit(
        uint64 chainKey,
        uint64 height,
        bytes calldata,
        MerkleProof calldata merkleProof,
        ContinuityProof calldata
    ) external override returns (bool) {
        lastSelector = msg.sig;
        if (revertOnVerify) revert("Merkle proof validation failed");
        if (result) emit TransactionVerified(chainKey, height, uint64(_indexOf(merkleProof)));
        return result;
    }

    function verifyAndEmit(
        uint64,
        uint64[] calldata,
        bytes[] calldata,
        MerkleProof[] calldata,
        ContinuityProof calldata
    ) external override returns (bool) {
        lastSelector = msg.sig;
        if (revertOnVerify) revert("Merkle proof validation failed");
        return result;
    }

    function verify(uint64, uint64, bytes calldata, MerkleProof calldata, ContinuityProof calldata)
        external
        view
        override
        returns (bool)
    {
        if (revertOnVerify) revert("Merkle proof validation failed");
        return result;
    }

    function verify(uint64, uint64[] calldata, bytes[] calldata, MerkleProof[] calldata, ContinuityProof calldata)
        external
        view
        override
        returns (bool)
    {
        if (revertOnVerify) revert("Merkle proof validation failed");
        return result;
    }

    /// @dev Official semantics (BlockProverTypes): isLeft => current node is the right child => bit set.
    function calculateTxIndex(MerkleProof calldata merkleProof) external pure override returns (uint64) {
        return uint64(_indexOf(merkleProof));
    }

    function _indexOf(MerkleProof calldata merkleProof) internal pure returns (uint256 idx) {
        for (uint256 i = 0; i < merkleProof.siblings.length; i++) {
            if (merkleProof.siblings[i].isLeft) idx |= (1 << i);
        }
    }
}
