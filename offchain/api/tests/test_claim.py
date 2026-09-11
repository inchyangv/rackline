import time

import pytest

from hashcredit_api.claim import build_claim_message, issue_claim_token, verify_claim_token


def test_claim_token_roundtrip() -> None:
    secret = "test-secret"
    token, payload = issue_claim_token(
        secret=secret,
        borrower="0x0000000000000000000000000000000000000001",
        btc_address="tb1qw508d6qejxtdg4y5r3zarvary0c5xw7kxpjzsx",
        chain_id=102031,
        ttl_seconds=120,
    )

    assert "." in token
    msg = build_claim_message(payload)
    assert "HashCredit Borrower Claim" in msg
    assert payload.borrower in msg

    verified = verify_claim_token(secret=secret, token=token, now=payload.issued_at + 1)
    assert verified.borrower == payload.borrower
    assert verified.btc_address == payload.btc_address


def test_claim_token_expired() -> None:
    secret = "test-secret"
    token, payload = issue_claim_token(
        secret=secret,
        borrower="0x0000000000000000000000000000000000000001",
        btc_address="tb1qw508d6qejxtdg4y5r3zarvary0c5xw7kxpjzsx",
        chain_id=102031,
        ttl_seconds=60,
    )
    with pytest.raises(ValueError):
        verify_claim_token(secret=secret, token=token, now=payload.expires_at + 1)

