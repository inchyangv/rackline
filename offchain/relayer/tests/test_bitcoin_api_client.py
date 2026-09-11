from __future__ import annotations

from typing import Any

from hashcredit_relayer.bitcoin import BitcoinApiClient


class _FakeResponse:
    def __init__(self, payload: Any = None, text: str = ""):
        self._payload = payload
        self.text = text

    def raise_for_status(self) -> None:
        return

    def json(self) -> Any:
        return self._payload


def _tx(txid: str, address: str, confirmed: bool = True, block_height: int = 100) -> dict[str, Any]:
    return {
        "txid": txid,
        "status": {
            "confirmed": confirmed,
            "block_height": block_height if confirmed else None,
            "block_time": 1_700_000_000 if confirmed else None,
        },
        "vout": [
            {
                "value": 123_456,
                "scriptpubkey": "0014" + "11" * 20,
                "scriptpubkey_type": "v0_p2wpkh",
                "scriptpubkey_address": address,
            }
        ],
    }


def test_get_address_txs_paginates_chain_endpoint() -> None:
    client = BitcoinApiClient("https://mempool.space/api")
    address = "bc1qtestaddress"

    page1 = [_tx(f"{i:064x}", address) for i in range(25)]
    page2 = [_tx(f"{1000+i:064x}", address) for i in range(5)]

    calls: list[str] = []

    def fake_get(url: str) -> _FakeResponse:
        calls.append(url)
        if url.endswith(f"/address/{address}/txs"):
            return _FakeResponse(payload=page1)
        if url.endswith(f"/address/{address}/txs/chain/{page1[-1]['txid']}"):
            return _FakeResponse(payload=page2)
        raise AssertionError(f"unexpected url: {url}")

    client.client.get = fake_get  # type: ignore[assignment]

    txs = client.get_address_txs(address)

    assert len(txs) == 30
    assert calls == [
        f"https://mempool.space/api/address/{address}/txs",
        f"https://mempool.space/api/address/{address}/txs/chain/{page1[-1]['txid']}",
    ]


def test_get_address_txs_handles_exact_multiples_of_25() -> None:
    client = BitcoinApiClient("https://mempool.space/api")
    address = "bc1qtestaddress"

    page1 = [_tx(f"{i:064x}", address) for i in range(25)]
    page2 = [_tx(f"{1000+i:064x}", address) for i in range(25)]
    page3: list[dict[str, Any]] = []

    calls: list[str] = []

    def fake_get(url: str) -> _FakeResponse:
        calls.append(url)
        if url.endswith(f"/address/{address}/txs"):
            return _FakeResponse(payload=page1)
        if url.endswith(f"/address/{address}/txs/chain/{page1[-1]['txid']}"):
            return _FakeResponse(payload=page2)
        if url.endswith(f"/address/{address}/txs/chain/{page2[-1]['txid']}"):
            return _FakeResponse(payload=page3)
        raise AssertionError(f"unexpected url: {url}")

    client.client.get = fake_get  # type: ignore[assignment]

    txs = client.get_address_txs(address)

    assert len(txs) == 50
    assert len(calls) == 3


def test_find_payouts_includes_older_paginated_history() -> None:
    client = BitcoinApiClient("https://mempool.space/api")
    address = "bc1qtarget"

    # First page has no qualifying output to the target address.
    page1 = [
        {
            "txid": "11" * 32,
            "status": {"confirmed": True, "block_height": 109, "block_time": 1_700_000_001},
            "vout": [
                {
                    "value": 50_000,
                    "scriptpubkey": "0014" + "22" * 20,
                    "scriptpubkey_type": "v0_p2wpkh",
                    "scriptpubkey_address": "bc1qother",
                }
            ],
        }
    ] + [_tx(f"{i:064x}", "bc1qother") for i in range(24)]

    # Second page contains the payout we expect to find.
    payout_txid = "aa" * 32
    page2 = [
        {
            "txid": payout_txid,
            "status": {"confirmed": True, "block_height": 100, "block_time": 1_700_000_000},
            "vout": [
                {
                    "value": 123_456,
                    "scriptpubkey": "0014" + "33" * 20,
                    "scriptpubkey_type": "v0_p2wpkh",
                    "scriptpubkey_address": address,
                }
            ],
        }
    ]

    def fake_get(url: str) -> _FakeResponse:
        if url.endswith("/blocks/tip/height"):
            return _FakeResponse(text="110")
        if url.endswith(f"/address/{address}/txs"):
            return _FakeResponse(payload=page1)
        if url.endswith(f"/address/{address}/txs/chain/{page1[-1]['txid']}"):
            return _FakeResponse(payload=page2)
        raise AssertionError(f"unexpected url: {url}")

    client.client.get = fake_get  # type: ignore[assignment]

    payouts = client.find_payouts_to_address(address, min_confirmations=6)

    assert len(payouts) == 1
    tx, output = payouts[0]
    assert tx.txid == payout_txid
    assert output.address == address
