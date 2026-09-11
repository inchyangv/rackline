"""
Bitcoin address decoding utilities.

Supports:
- P2WPKH (bech32): bc1q... (mainnet), tb1q... (testnet)
- P2PKH (base58check): 1... (mainnet), m.../n... (testnet)
"""

import hashlib
from typing import Tuple

# Bech32 character set
BECH32_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


def bech32_polymod(values: list[int]) -> int:
    """Internal function for Bech32 checksum computation."""
    GEN = [0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3]
    chk = 1
    for v in values:
        b = chk >> 25
        chk = ((chk & 0x1FFFFFF) << 5) ^ v
        for i in range(5):
            chk ^= GEN[i] if ((b >> i) & 1) else 0
    return chk


def bech32_hrp_expand(hrp: str) -> list[int]:
    """Expand HRP for checksum computation."""
    return [ord(x) >> 5 for x in hrp] + [0] + [ord(x) & 31 for x in hrp]


def bech32_verify_checksum(hrp: str, data: list[int]) -> bool:
    """Verify Bech32 checksum."""
    return bech32_polymod(bech32_hrp_expand(hrp) + data) == 1


def bech32_decode(address: str) -> Tuple[str, bytes] | None:
    """
    Decode a Bech32/Bech32m address.

    Returns:
        (hrp, data) where data is the decoded witness program
        or None if invalid
    """
    # Lowercase
    address = address.lower()

    # Find separator
    pos = address.rfind("1")
    if pos < 1 or pos + 7 > len(address):
        return None

    hrp = address[:pos]
    data_part = address[pos + 1:]

    # Validate characters
    data = []
    for c in data_part:
        if c not in BECH32_CHARSET:
            return None
        data.append(BECH32_CHARSET.index(c))

    # Verify checksum
    if not bech32_verify_checksum(hrp, data):
        return None

    # Remove checksum (last 6 characters)
    data = data[:-6]

    if len(data) < 1:
        return None

    # First byte is witness version
    version = data[0]

    # Convert 5-bit to 8-bit
    converted = convert_bits(data[1:], 5, 8, False)
    if converted is None:
        return None

    # Version 0 requires 20 or 32 byte programs
    if version == 0 and len(converted) not in (20, 32):
        return None

    return (hrp, bytes([version]) + bytes(converted))


def convert_bits(data: list[int], frombits: int, tobits: int, pad: bool) -> list[int] | None:
    """Convert between bit widths."""
    acc = 0
    bits = 0
    ret = []
    maxv = (1 << tobits) - 1
    max_acc = (1 << (frombits + tobits - 1)) - 1

    for value in data:
        if value < 0 or (value >> frombits):
            return None
        acc = ((acc << frombits) | value) & max_acc
        bits += frombits
        while bits >= tobits:
            bits -= tobits
            ret.append((acc >> bits) & maxv)

    if pad:
        if bits:
            ret.append((acc << (tobits - bits)) & maxv)
    elif bits >= frombits or ((acc << (tobits - bits)) & maxv):
        return None

    return ret


# Base58 character set
BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def base58_decode(s: str) -> bytes | None:
    """Decode a Base58 string."""
    num = 0
    for c in s:
        if c not in BASE58_ALPHABET:
            return None
        num = num * 58 + BASE58_ALPHABET.index(c)

    # Convert to bytes
    result = []
    while num > 0:
        result.append(num & 0xFF)
        num >>= 8
    result = bytes(reversed(result))

    # Add leading zeros
    pad_size = len(s) - len(s.lstrip("1"))
    return b"\x00" * pad_size + result


def base58check_decode(s: str) -> Tuple[int, bytes] | None:
    """
    Decode a Base58Check encoded string.

    Returns:
        (version, payload) or None if invalid
    """
    data = base58_decode(s)
    if data is None or len(data) < 5:
        return None

    # Verify checksum (last 4 bytes)
    checksum = data[-4:]
    payload = data[:-4]

    expected_checksum = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    if checksum != expected_checksum:
        return None

    return (payload[0], payload[1:])


def decode_btc_address(address: str) -> Tuple[bytes, str] | None:
    """
    Decode a Bitcoin address and extract the pubkey hash.

    Supports:
    - P2WPKH (bech32): bc1q.../tb1q... -> 20-byte pubkey hash
    - P2PKH (base58check): 1.../m.../n... -> 20-byte pubkey hash

    Returns:
        (pubkey_hash, address_type) where address_type is "p2wpkh" or "p2pkh"
        or None if unsupported/invalid
    """
    # Try Bech32 (P2WPKH)
    if address.lower().startswith(("bc1", "tb1")):
        result = bech32_decode(address)
        if result is None:
            return None

        hrp, data = result

        # Validate HRP
        if hrp not in ("bc", "tb"):
            return None

        # Version 0, 20-byte program = P2WPKH
        if len(data) == 21 and data[0] == 0:
            return (data[1:], "p2wpkh")

        return None

    # Try Base58Check (P2PKH)
    result = base58check_decode(address)
    if result is None:
        return None

    version, payload = result

    # Version bytes for P2PKH:
    # 0x00 = mainnet
    # 0x6F (111) = testnet (m... or n...)
    if version in (0x00, 0x6F) and len(payload) == 20:
        return (payload, "p2pkh")

    return None
