// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * @title BitcoinLib
 * @notice Library for Bitcoin data parsing and verification
 * @dev All Bitcoin data is little-endian unless otherwise noted
 *
 * Key functions:
 * - sha256d: Double SHA256 hash
 * - parseHeader: Extract fields from 80-byte block header
 * - verifyPoW: Check if block hash meets difficulty target
 * - verifyMerkleProof: Verify transaction inclusion
 * - parseTxOutputs: Extract outputs from raw transaction
 */
library BitcoinLib {
    /// @notice Bitcoin block header size
    uint256 constant HEADER_SIZE = 80;

    /// @notice Maximum difficulty target (lowest difficulty)
    uint256 constant MAX_TARGET = 0x00000000FFFF0000000000000000000000000000000000000000000000000000;

    /// @notice Error codes
    error InvalidHeaderSize(uint256 size);
    error InvalidProofLength();
    error InvalidTxData();
    error InvalidVarInt();
    error UnsupportedScriptType();

    /**
     * @notice Parsed Bitcoin block header
     */
    struct BlockHeader {
        uint32 version;
        bytes32 prevBlockHash;
        bytes32 merkleRoot;
        uint32 timestamp;
        uint32 bits;
        uint32 nonce;
    }

    /**
     * @notice Parsed transaction output
     */
    struct TxOutput {
        uint64 value;
        bytes scriptPubKey;
    }

    /**
     * @notice Double SHA256 hash (sha256d)
     * @param data Data to hash
     * @return The double SHA256 hash
     */
    function sha256d(bytes memory data) internal pure returns (bytes32) {
        return sha256(abi.encodePacked(sha256(data)));
    }

    /**
     * @notice Double SHA256 hash for 80-byte header (optimized)
     * @param header 80-byte block header
     * @return The block hash (little-endian, as stored in Bitcoin)
     */
    function hashHeader(bytes memory header) internal pure returns (bytes32) {
        if (header.length != HEADER_SIZE) {
            revert InvalidHeaderSize(header.length);
        }
        return sha256d(header);
    }

    /**
     * @notice Parse 80-byte block header
     * @param header Raw header bytes
     * @return parsed Parsed header struct
     */
    function parseHeader(bytes memory header) internal pure returns (BlockHeader memory parsed) {
        if (header.length != HEADER_SIZE) {
            revert InvalidHeaderSize(header.length);
        }

        // Version: bytes 0-3 (little-endian)
        parsed.version = readUint32LE(header, 0);

        // Previous block hash: bytes 4-35 (already little-endian in Bitcoin)
        parsed.prevBlockHash = readBytes32(header, 4);

        // Merkle root: bytes 36-67
        parsed.merkleRoot = readBytes32(header, 36);

        // Timestamp: bytes 68-71
        parsed.timestamp = readUint32LE(header, 68);

        // Bits (difficulty target): bytes 72-75
        parsed.bits = readUint32LE(header, 72);

        // Nonce: bytes 76-79
        parsed.nonce = readUint32LE(header, 76);
    }

    /**
     * @notice Convert bits field to target
     * @param bits Compact target representation
     * @return target 256-bit target value
     */
    function bitsToTarget(uint32 bits) internal pure returns (uint256 target) {
        uint256 exponent = bits >> 24;
        uint256 mantissa = bits & 0x007fffff;

        if (exponent <= 3) {
            target = mantissa >> (8 * (3 - exponent));
        } else {
            target = mantissa << (8 * (exponent - 3));
        }

        // Cap at max target
        if (target > MAX_TARGET) {
            target = MAX_TARGET;
        }
    }

    /**
     * @notice Verify block hash meets difficulty target
     * @param blockHash The block hash (from sha256d of header)
     * @param bits The difficulty bits from header
     * @return True if hash meets target (hash <= target)
     */
    function verifyPoW(bytes32 blockHash, uint32 bits) internal pure returns (bool) {
        uint256 target = bitsToTarget(bits);
        // Block hash is little-endian, need to reverse for comparison
        uint256 hashValue = reverseBytes32ToUint(blockHash);
        return hashValue <= target;
    }

    /**
     * @notice Verify Merkle inclusion proof (Bitcoin double-SHA256 Merkle tree)
     * @param txid Transaction ID (sha256d of raw tx, little-endian)
     * @param merkleRoot Expected Merkle root from block header
     * @param proof Array of sibling hashes
     * @param txIndex Transaction index in block (determines left/right)
     * @return True if proof is valid
     */
    function verifyMerkleProof(bytes32 txid, bytes32 merkleRoot, bytes32[] memory proof, uint256 txIndex)
        internal
        pure
        returns (bool)
    {
        bytes32 current = txid;

        for (uint256 i = 0; i < proof.length; i++) {
            bytes32 sibling = proof[i];

            // Determine if current is left or right based on txIndex bit
            if (txIndex & 1 == 0) {
                // Current is left
                current = sha256d(abi.encodePacked(current, sibling));
            } else {
                // Current is right
                current = sha256d(abi.encodePacked(sibling, current));
            }

            txIndex >>= 1;
        }

        return current == merkleRoot;
    }

    /**
     * @notice Parse transaction outputs
     * @param rawTx Raw transaction bytes
     * @param outputIndex Which output to extract
     * @return output The parsed output
     */
    function parseTxOutput(bytes memory rawTx, uint32 outputIndex) internal pure returns (TxOutput memory output) {
        uint256 offset = 4; // Skip version (4 bytes)

        // Check for witness marker
        bool hasWitness = false;
        if (rawTx[offset] == 0x00 && rawTx[offset + 1] == 0x01) {
            hasWitness = true;
            offset += 2; // Skip marker and flag
        }

        // Parse input count
        uint256 inputCount;
        (inputCount, offset) = readVarInt(rawTx, offset);

        // Skip inputs
        for (uint256 i = 0; i < inputCount; i++) {
            offset += 32; // Previous txid
            offset += 4; // Previous vout

            // Script length and script
            uint256 inputScriptLen;
            (inputScriptLen, offset) = readVarInt(rawTx, offset);
            offset += inputScriptLen;

            offset += 4; // Sequence
        }

        // Parse output count
        uint256 outputCount;
        (outputCount, offset) = readVarInt(rawTx, offset);

        if (outputIndex >= outputCount) {
            revert InvalidTxData();
        }

        // Skip to desired output
        for (uint256 i = 0; i < outputIndex; i++) {
            offset += 8; // Value

            uint256 skipScriptLen;
            (skipScriptLen, offset) = readVarInt(rawTx, offset);
            offset += skipScriptLen;
        }

        // Parse target output
        output.value = readUint64LE(rawTx, offset);
        offset += 8;

        uint256 scriptLen;
        (scriptLen, offset) = readVarInt(rawTx, offset);

        output.scriptPubKey = new bytes(scriptLen);
        for (uint256 i = 0; i < scriptLen; i++) {
            output.scriptPubKey[i] = rawTx[offset + i];
        }
    }

    /**
     * @notice Extract pubkey hash from scriptPubKey (P2WPKH or P2PKH)
     * @param scriptPubKey The output script
     * @return pubkeyHash 20-byte pubkey hash
     * @return scriptType 0=P2WPKH, 1=P2PKH, 2=other
     */
    function extractPubkeyHash(bytes memory scriptPubKey) internal pure returns (bytes20 pubkeyHash, uint8 scriptType) {
        // P2WPKH: OP_0 <20 bytes> = 0x0014{20 bytes}
        if (scriptPubKey.length == 22 && scriptPubKey[0] == 0x00 && scriptPubKey[1] == 0x14) {
            pubkeyHash = readBytes20(scriptPubKey, 2);
            scriptType = 0; // P2WPKH
            return (pubkeyHash, scriptType);
        }

        // P2PKH: OP_DUP OP_HASH160 <20 bytes> OP_EQUALVERIFY OP_CHECKSIG
        // = 0x76a914{20 bytes}88ac
        if (
            scriptPubKey.length == 25 && scriptPubKey[0] == 0x76 && scriptPubKey[1] == 0xa9 && scriptPubKey[2] == 0x14
                && scriptPubKey[23] == 0x88 && scriptPubKey[24] == 0xac
        ) {
            pubkeyHash = readBytes20(scriptPubKey, 3);
            scriptType = 1; // P2PKH
            return (pubkeyHash, scriptType);
        }

        // Unsupported script type
        scriptType = 2;
    }

    // ============ Internal Helper Functions ============

    /**
     * @notice Read uint32 little-endian
     */
    function readUint32LE(bytes memory data, uint256 offset) internal pure returns (uint32) {
        return uint32(uint8(data[offset])) | (uint32(uint8(data[offset + 1])) << 8)
            | (uint32(uint8(data[offset + 2])) << 16) | (uint32(uint8(data[offset + 3])) << 24);
    }

    /**
     * @notice Read uint64 little-endian
     */
    function readUint64LE(bytes memory data, uint256 offset) internal pure returns (uint64) {
        return uint64(uint8(data[offset])) | (uint64(uint8(data[offset + 1])) << 8)
            | (uint64(uint8(data[offset + 2])) << 16) | (uint64(uint8(data[offset + 3])) << 24)
            | (uint64(uint8(data[offset + 4])) << 32) | (uint64(uint8(data[offset + 5])) << 40)
            | (uint64(uint8(data[offset + 6])) << 48) | (uint64(uint8(data[offset + 7])) << 56);
    }

    /**
     * @notice Read 32 bytes
     */
    function readBytes32(bytes memory data, uint256 offset) internal pure returns (bytes32 result) {
        assembly {
            result := mload(add(add(data, 32), offset))
        }
    }

    /**
     * @notice Read 20 bytes
     */
    function readBytes20(bytes memory data, uint256 offset) internal pure returns (bytes20 result) {
        for (uint256 i = 0; i < 20; i++) {
            result |= bytes20(data[offset + i]) >> (i * 8);
        }
    }

    /**
     * @notice Read VarInt (Bitcoin variable length integer)
     * @param data Raw bytes
     * @param offset Starting offset
     * @return value The integer value
     * @return newOffset Offset after reading
     */
    function readVarInt(bytes memory data, uint256 offset) internal pure returns (uint256 value, uint256 newOffset) {
        uint8 first = uint8(data[offset]);

        if (first < 0xfd) {
            return (first, offset + 1);
        } else if (first == 0xfd) {
            return (uint16(uint8(data[offset + 1])) | (uint16(uint8(data[offset + 2])) << 8), offset + 3);
        } else if (first == 0xfe) {
            return (readUint32LE(data, offset + 1), offset + 5);
        } else {
            return (readUint64LE(data, offset + 1), offset + 9);
        }
    }

    /**
     * @notice Reverse bytes32 and convert to uint256 for comparison
     * @dev Bitcoin stores hashes in little-endian, but targets are big-endian
     */
    function reverseBytes32ToUint(bytes32 input) internal pure returns (uint256 result) {
        for (uint256 i = 0; i < 32; i++) {
            result |= uint256(uint8(input[i])) << ((31 - i) * 8);
        }
    }
}
