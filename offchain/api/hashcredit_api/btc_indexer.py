"""
External Bitcoin indexer client (Esplora-compatible).

Used for read-only address history in demos/ops UI.
"""

from dataclasses import dataclass
from typing import Any, Optional

import httpx


@dataclass
class BtcIndexerConfig:
    """Bitcoin indexer configuration."""

    base_url: str
    timeout: float = 20.0


class BtcIndexer:
    """Async client for Esplora-compatible Bitcoin indexers."""

    def __init__(self, config: BtcIndexerConfig):
        self.config = config
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.config.base_url.rstrip("/"),
                timeout=self.config.timeout,
            )
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _get_json(self, path: str) -> Any:
        client = await self._get_client()
        response = await client.get(path)
        response.raise_for_status()
        return response.json()

    async def get_tip_height(self) -> int:
        client = await self._get_client()
        response = await client.get("/blocks/tip/height")
        response.raise_for_status()
        return int(response.text)

    async def get_address_info(self, address: str) -> dict[str, Any]:
        data = await self._get_json(f"/address/{address}")
        if not isinstance(data, dict):
            raise ValueError("Invalid response from indexer /address endpoint")
        return data

    async def get_address_txs(self, address: str) -> list[dict[str, Any]]:
        data = await self._get_json(f"/address/{address}/txs")
        if not isinstance(data, list):
            raise ValueError("Invalid response from indexer /address/txs endpoint")
        return [x for x in data if isinstance(x, dict)]

    async def get_address_txs_chain(self, address: str, last_seen_txid: str) -> list[dict[str, Any]]:
        data = await self._get_json(f"/address/{address}/txs/chain/{last_seen_txid}")
        if not isinstance(data, list):
            raise ValueError("Invalid response from indexer /address/txs/chain endpoint")
        return [x for x in data if isinstance(x, dict)]

    @staticmethod
    def _sum_address_inputs(tx: dict[str, Any], address: str) -> int:
        total = 0
        vin = tx.get("vin")
        if not isinstance(vin, list):
            return 0
        for entry in vin:
            if not isinstance(entry, dict):
                continue
            prevout = entry.get("prevout")
            if not isinstance(prevout, dict):
                continue
            if prevout.get("scriptpubkey_address") != address:
                continue
            value = prevout.get("value")
            if isinstance(value, int):
                total += value
        return total

    @staticmethod
    def _sum_address_outputs(tx: dict[str, Any], address: str) -> int:
        total = 0
        vout = tx.get("vout")
        if not isinstance(vout, list):
            return 0
        for entry in vout:
            if not isinstance(entry, dict):
                continue
            if entry.get("scriptpubkey_address") != address:
                continue
            value = entry.get("value")
            if isinstance(value, int):
                total += value
        return total

    @staticmethod
    def _has_coinbase_input(tx: dict[str, Any]) -> bool:
        vin = tx.get("vin")
        if not isinstance(vin, list):
            return False
        for entry in vin:
            if isinstance(entry, dict) and bool(entry.get("is_coinbase")):
                return True
        return False

    @staticmethod
    def _status(tx: dict[str, Any]) -> tuple[bool, Optional[int], Optional[int], Optional[str]]:
        status = tx.get("status")
        if not isinstance(status, dict):
            return False, None, None, None
        confirmed = bool(status.get("confirmed"))
        block_height = status.get("block_height")
        block_time = status.get("block_time")
        block_hash = status.get("block_hash")
        return (
            confirmed,
            block_height if isinstance(block_height, int) else None,
            block_time if isinstance(block_time, int) else None,
            block_hash if isinstance(block_hash, str) else None,
        )

    def _build_tx_item(self, tx: dict[str, Any], address: str, tip_height: int) -> Optional[dict[str, Any]]:
        txid = tx.get("txid")
        if not isinstance(txid, str):
            return None

        sent_sats = self._sum_address_inputs(tx, address)
        received_sats = self._sum_address_outputs(tx, address)
        net_sats = received_sats - sent_sats
        has_coinbase_input = self._has_coinbase_input(tx)
        is_mining_reward = has_coinbase_input and received_sats > 0

        direction = "self"
        if is_mining_reward:
            direction = "mining"
        elif received_sats > 0 and sent_sats == 0:
            direction = "in"
        elif sent_sats > 0 and received_sats == 0:
            direction = "out"

        confirmed, block_height, block_time, block_hash = self._status(tx)
        confirmations = None
        if confirmed and isinstance(block_height, int):
            confirmations = max(1, tip_height - block_height + 1)

        fee = tx.get("fee")
        return {
            "txid": txid,
            "confirmed": confirmed,
            "block_height": block_height,
            "block_time": block_time,
            "block_hash": block_hash,
            "confirmations": confirmations,
            "fee_sats": fee if isinstance(fee, int) else None,
            "sent_sats": sent_sats,
            "received_sats": received_sats,
            "net_sats": net_sats,
            "direction": direction,
            "has_coinbase_input": has_coinbase_input,
            "is_mining_reward": is_mining_reward,
        }

    async def get_address_history(self, address: str, limit: int = 25, mining_only: bool = False) -> dict[str, Any]:
        limit = max(1, min(limit, 100))
        tip_height = await self.get_tip_height()
        address_info = await self.get_address_info(address)

        tx_items: list[dict[str, Any]] = []
        batch = await self.get_address_txs(address)
        page_count = 1
        max_pages = 12 if mining_only else max(1, (limit + 24) // 25)
        while batch and len(tx_items) < limit:
            for tx in batch:
                tx_item = self._build_tx_item(tx, address, tip_height)
                if tx_item is None:
                    continue
                if mining_only and not tx_item["is_mining_reward"]:
                    continue
                tx_items.append(tx_item)
                if len(tx_items) >= limit:
                    break

            if len(tx_items) >= limit:
                break
            if page_count >= max_pages:
                break

            # Confirmed pagination (25 per request on Esplora)
            last_seen_txid = batch[-1].get("txid")
            if not isinstance(last_seen_txid, str) or not last_seen_txid:
                break
            batch = await self.get_address_txs_chain(address, last_seen_txid)
            page_count += 1

        chain_stats = address_info.get("chain_stats") if isinstance(address_info.get("chain_stats"), dict) else {}
        mempool_stats = address_info.get("mempool_stats") if isinstance(address_info.get("mempool_stats"), dict) else {}

        funded_chain = chain_stats.get("funded_txo_sum")
        spent_chain = chain_stats.get("spent_txo_sum")
        funded_mempool = mempool_stats.get("funded_txo_sum")
        spent_mempool = mempool_stats.get("spent_txo_sum")

        funded_chain_int = funded_chain if isinstance(funded_chain, int) else 0
        spent_chain_int = spent_chain if isinstance(spent_chain, int) else 0
        funded_mempool_int = funded_mempool if isinstance(funded_mempool, int) else 0
        spent_mempool_int = spent_mempool if isinstance(spent_mempool, int) else 0

        return {
            "address": address,
            "tip_height": tip_height,
            "balance_chain_sats": funded_chain_int - spent_chain_int,
            "balance_mempool_delta_sats": funded_mempool_int - spent_mempool_int,
            "tx_count_chain": chain_stats.get("tx_count") if isinstance(chain_stats.get("tx_count"), int) else 0,
            "tx_count_mempool": mempool_stats.get("tx_count") if isinstance(mempool_stats.get("tx_count"), int) else 0,
            "items": tx_items,
        }
