"""
Bitcoin blockchain interaction via mempool.space API.
"""

import hashlib
from dataclasses import dataclass
from typing import Optional

import httpx
import structlog

logger = structlog.get_logger()


@dataclass
class BitcoinTx:
    """Parsed Bitcoin transaction."""

    txid: str
    block_height: Optional[int]
    block_time: Optional[int]
    confirmations: int
    outputs: list["TxOutput"]


@dataclass
class TxOutput:
    """Transaction output."""

    vout: int
    value_sats: int
    script_pubkey: str
    script_pubkey_type: str
    address: Optional[str]


@dataclass
class AddressUtxo:
    """UTXO for an address."""

    txid: str
    vout: int
    value_sats: int
    status_confirmed: bool
    status_block_height: Optional[int]
    status_block_time: Optional[int]


class BitcoinApiClient:
    """Client for mempool.space API."""

    def __init__(self, base_url: str = "https://mempool.space/api"):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(timeout=30.0)

    def get_address_txs(self, address: str) -> list[dict]:
        """
        Get transactions for an address.

        mempool/esplora returns transactions in pages (latest first).
        To avoid missing older confirmed payouts, we follow the
        `/txs/chain/<last_seen_txid>` pagination until exhausted.
        """
        base = f"{self.base_url}/address/{address}/txs"
        txs: list[dict] = []
        cursor_txid: Optional[str] = None
        seen_cursors: set[str] = set()

        while True:
            if cursor_txid is None:
                url = base
            else:
                # Guard against accidental cursor loops from upstream responses.
                if cursor_txid in seen_cursors:
                    logger.warning("address_txs_cursor_loop", address=address, cursor_txid=cursor_txid)
                    break
                seen_cursors.add(cursor_txid)
                url = f"{base}/chain/{cursor_txid}"

            response = self.client.get(url)
            response.raise_for_status()
            page = response.json()

            if not page:
                break

            txs.extend(page)

            # esplora page size is 25; shorter page means end of history.
            if len(page) < 25:
                break

            last_txid = page[-1].get("txid")
            if not last_txid:
                break
            cursor_txid = last_txid

        return txs

    def get_address_utxos(self, address: str) -> list[AddressUtxo]:
        """Get UTXOs for an address."""
        url = f"{self.base_url}/address/{address}/utxo"
        response = self.client.get(url)
        response.raise_for_status()

        utxos = []
        for item in response.json():
            status = item.get("status", {})
            utxos.append(
                AddressUtxo(
                    txid=item["txid"],
                    vout=item["vout"],
                    value_sats=item["value"],
                    status_confirmed=status.get("confirmed", False),
                    status_block_height=status.get("block_height"),
                    status_block_time=status.get("block_time"),
                )
            )
        return utxos

    def get_tx(self, txid: str) -> dict:
        """Get transaction details."""
        url = f"{self.base_url}/tx/{txid}"
        response = self.client.get(url)
        response.raise_for_status()
        return response.json()

    def get_block_tip_height(self) -> int:
        """Get current block height."""
        url = f"{self.base_url}/blocks/tip/height"
        response = self.client.get(url)
        response.raise_for_status()
        return int(response.text)

    def parse_tx(self, tx_data: dict, current_height: Optional[int] = None) -> BitcoinTx:
        """Parse transaction data into BitcoinTx."""
        status = tx_data.get("status", {})
        block_height = status.get("block_height")
        block_time = status.get("block_time")

        if current_height is None:
            current_height = self.get_block_tip_height()

        confirmations = 0
        if block_height is not None and status.get("confirmed", False):
            confirmations = current_height - block_height + 1

        outputs = []
        for i, vout in enumerate(tx_data.get("vout", [])):
            outputs.append(
                TxOutput(
                    vout=i,
                    value_sats=vout.get("value", 0),
                    script_pubkey=vout.get("scriptpubkey", ""),
                    script_pubkey_type=vout.get("scriptpubkey_type", ""),
                    address=vout.get("scriptpubkey_address"),
                )
            )

        return BitcoinTx(
            txid=tx_data["txid"],
            block_height=block_height,
            block_time=block_time,
            confirmations=confirmations,
            outputs=outputs,
        )

    def find_payouts_to_address(
        self, address: str, min_confirmations: int = 6
    ) -> list[tuple[BitcoinTx, TxOutput]]:
        """Find confirmed payouts to an address."""
        current_height = self.get_block_tip_height()
        txs_data = self.get_address_txs(address)

        payouts = []
        for tx_data in txs_data:
            tx = self.parse_tx(tx_data, current_height)

            if tx.confirmations < min_confirmations:
                continue

            for output in tx.outputs:
                if output.address == address:
                    payouts.append((tx, output))

        return payouts

    def close(self) -> None:
        """Close the HTTP client."""
        self.client.close()


def address_to_script_pubkey_hash(address: str) -> str:
    """
    Convert Bitcoin address to script pubkey hash.

    Note: This is a simplified implementation.
    For production, use proper address decoding.
    """
    # For MVP, we'll use a simple hash of the address string
    # Production should decode the actual scriptPubKey
    return "0x" + hashlib.sha256(address.encode()).hexdigest()
