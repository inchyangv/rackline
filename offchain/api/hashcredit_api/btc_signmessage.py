"""
Bitcoin message signature verification (BIP-137 style).

We verify a base64 signature produced by common wallets for the message:
  "Bitcoin Signed Message:\n" + varint(len(message)) + message

Signature format (base64):
  header(1) + r(32) + s(32)  (compact recoverable signature)

Header ranges per BIP-137 (Bitcoin Wiki):
  - 27-30: P2PKH uncompressed
  - 31-34: P2PKH compressed
  - 35-38: Segwit P2SH (not supported here)
  - 39-42: Segwit Bech32 (P2WPKH v0)

recId is obtained by subtracting the base constant from the header byte.

We currently support address types present in this repo:
  - p2pkh (base58)
  - p2wpkh (bech32 v0)
"""

from __future__ import annotations

import base64
import hashlib

from coincurve import PublicKey

from .address import decode_btc_address
from .bitcoin import sha256d


def _encode_varint(n: int) -> bytes:
    if n < 0:
        raise ValueError("varint must be non-negative")
    if n < 0xFD:
        return bytes([n])
    if n <= 0xFFFF:
        return b"\xFD" + n.to_bytes(2, "little")
    if n <= 0xFFFFFFFF:
        return b"\xFE" + n.to_bytes(4, "little")
    return b"\xFF" + n.to_bytes(8, "little")


def _hash160(data: bytes) -> bytes:
    h = hashlib.sha256(data).digest()
    r = hashlib.new("ripemd160")
    r.update(h)
    return r.digest()


def bitcoin_message_hash(message: str) -> bytes:
    msg = message.encode("utf-8")
    prefix = b"\x18Bitcoin Signed Message:\n"
    payload = prefix + _encode_varint(len(msg)) + msg
    return sha256d(payload)


def verify_bip137_signature(*, btc_address: str, message: str, signature_b64: str) -> bool:
    decoded = decode_btc_address(btc_address)
    if decoded is None:
        return False
    expected_hash, addr_type = decoded

    sig = base64.b64decode(signature_b64)
    if len(sig) != 65:
        return False

    header = sig[0]
    if header < 27 or header > 42:
        return False

    recid: int
    compressed: bool

    if 27 <= header <= 30:
        # p2pkh (uncompressed)
        recid = header - 27
        compressed = False
        if addr_type != "p2pkh":
            return False
    elif 31 <= header <= 34:
        # p2pkh (compressed)
        recid = header - 31
        compressed = True
        if addr_type != "p2pkh":
            return False
    elif 39 <= header <= 42:
        # bech32 segwit (p2wpkh v0) - always compressed pubkey
        recid = header - 39
        compressed = True
        if addr_type != "p2wpkh":
            return False
    else:
        # 35-38 (p2sh-segwit) or other: not supported
        return False

    msg_hash = bitcoin_message_hash(message)

    # coincurve expects the recovery id as the last byte.
    recoverable = sig[1:] + bytes([recid])
    pubkey = PublicKey.from_signature_and_message(recoverable, msg_hash, hasher=None)
    pubkey_bytes = pubkey.format(compressed=compressed)

    got = _hash160(pubkey_bytes)
    return got == expected_hash
