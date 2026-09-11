"""
Bitcoin address decoding utilities.

Supports P2PKH (base58check) and P2WPKH (bech32) addresses.
"""

from typing import Optional

# Bech32 charset
BECH32_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"

# Base58 charset
BASE58_CHARSET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def _bech32_polymod(values: list[int]) -> int:
    """Internal Bech32 polymod calculation."""
    GEN = [0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3]
    chk = 1
    for v in values:
        b = chk >> 25
        chk = ((chk & 0x1FFFFFF) << 5) ^ v
        for i in range(5):
            if (b >> i) & 1:
                chk ^= GEN[i]
    return chk


def _bech32_hrp_expand(hrp: str) -> list[int]:
    """Expand HRP for checksum calculation."""
    return [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp]


def _bech32_verify_checksum(hrp: str, data: list[int]) -> bool:
    """Verify Bech32 checksum."""
    return _bech32_polymod(_bech32_hrp_expand(hrp) + data) == 1


def decode_bech32(addr: str) -> Optional[tuple[str, list[int]]]:
    """
    Decode a bech32 address.

    Returns (hrp, data) or None if invalid.
    """
    if any(ord(c) < 33 or ord(c) > 126 for c in addr):
        return None

    addr = addr.lower()
    pos = addr.rfind("1")
    if pos < 1 or pos + 7 > len(addr):
        return None

    hrp = addr[:pos]
    data_part = addr[pos + 1 :]

    if not all(c in BECH32_CHARSET for c in data_part):
        return None

    data = [BECH32_CHARSET.index(c) for c in data_part]

    if not _bech32_verify_checksum(hrp, data):
        return None

    return hrp, data[:-6]  # Remove checksum


def _convertbits(data: list[int], frombits: int, tobits: int, pad: bool = True) -> Optional[list[int]]:
    """Convert between bit sizes."""
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


def decode_bech32_address(addr: str) -> Optional[tuple[bytes, str]]:
    """
    Decode a bech32 Bitcoin address (P2WPKH).

    Returns (pubkey_hash, address_type) or None if invalid.
    Supports:
    - bc1q... (mainnet P2WPKH)
    - tb1q... (testnet P2WPKH)
    """
    result = decode_bech32(addr)
    if result is None:
        return None

    hrp, data = result

    # Check HRP
    if hrp not in ("bc", "tb", "bcrt"):
        return None

    if len(data) < 1:
        return None

    # Witness version
    witness_version = data[0]
    if witness_version != 0:
        # Only support v0 (P2WPKH)
        return None

    # Convert from 5-bit to 8-bit
    decoded = _convertbits(data[1:], 5, 8, False)
    if decoded is None:
        return None

    program = bytes(decoded)

    # P2WPKH: 20 bytes
    if len(program) == 20:
        return program, "p2wpkh"

    return None


def decode_base58check(addr: str) -> Optional[bytes]:
    """
    Decode a base58check encoded string.

    Returns payload (without version/checksum) or None if invalid.
    """
    import hashlib

    # Decode base58
    num = 0
    for c in addr:
        if c not in BASE58_CHARSET:
            return None
        num = num * 58 + BASE58_CHARSET.index(c)

    # Convert to bytes
    combined = num.to_bytes(25, "big")

    # Split: version (1) + payload (20) + checksum (4)
    checksum = combined[-4:]
    data = combined[:-4]

    # Verify checksum
    expected = hashlib.sha256(hashlib.sha256(data).digest()).digest()[:4]
    if checksum != expected:
        return None

    return data[1:]  # Remove version byte


def decode_p2pkh_address(addr: str) -> Optional[tuple[bytes, str]]:
    """
    Decode a P2PKH Bitcoin address (base58check).

    Returns (pubkey_hash, address_type) or None if invalid.
    Supports:
    - 1... (mainnet)
    - m.../n... (testnet)
    """
    # Check first character for network
    if not addr:
        return None

    first = addr[0]
    if first not in ("1", "m", "n"):
        return None

    payload = decode_base58check(addr)
    if payload is None or len(payload) != 20:
        return None

    return payload, "p2pkh"


def decode_btc_address(addr: str) -> Optional[tuple[bytes, str]]:
    """
    Decode a Bitcoin address and extract the pubkey hash.

    Supports:
    - P2WPKH (bech32): bc1q... / tb1q...
    - P2PKH (base58check): 1... / m... / n...

    Returns (pubkey_hash, address_type) or None if invalid.
    """
    # Try bech32 first
    if addr.lower().startswith(("bc1", "tb1", "bcrt1")):
        return decode_bech32_address(addr)

    # Try base58check
    return decode_p2pkh_address(addr)
