"""
Bitcoin RPC client for the API.

Simplified async client for interacting with Bitcoin Core.
"""

import hashlib
from dataclasses import dataclass
from typing import Any, Optional

import httpx


def sha256d(data: bytes) -> bytes:
    """Double SHA256 hash."""
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


@dataclass
class BitcoinRPCConfig:
    """Bitcoin RPC configuration."""

    url: str = "http://localhost:18332"
    user: str = ""
    password: str = ""
    timeout: float = 30.0


class BitcoinRPC:
    """
    Async Bitcoin Core RPC client.
    """

    def __init__(self, config: BitcoinRPCConfig):
        self.config = config
        self._client: Optional[httpx.AsyncClient] = None
        self._request_id = 0

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            auth = None
            if self.config.user and self.config.password:
                auth = httpx.BasicAuth(self.config.user, self.config.password)
            self._client = httpx.AsyncClient(
                base_url=self.config.url,
                auth=auth,
                timeout=self.config.timeout,
            )
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def call(self, method: str, params: list[Any] | None = None) -> Any:
        """Make an RPC call."""
        self._request_id += 1
        payload = {
            "jsonrpc": "1.0",
            "id": self._request_id,
            "method": method,
            "params": params or [],
        }

        client = await self._get_client()
        response = await client.post("/", json=payload)
        response.raise_for_status()

        result = response.json()
        if "error" in result and result["error"]:
            raise Exception(f"RPC error: {result['error']}")

        return result.get("result")

    async def get_block_hash(self, height: int) -> str:
        """Get block hash at height."""
        return await self.call("getblockhash", [height])

    async def get_block_header(self, block_hash: str, verbose: bool = True) -> dict[str, Any]:
        """Get block header (verbose mode returns dict)."""
        return await self.call("getblockheader", [block_hash, verbose])

    async def get_block_header_hex(self, block_hash: str) -> str:
        """Get block header as hex string."""
        return await self.call("getblockheader", [block_hash, False])

    async def get_block_count(self) -> int:
        """Get current block height."""
        return await self.call("getblockcount")

    async def get_block_txids(self, block_hash: str) -> list[str]:
        """Get list of transaction IDs in a block."""
        block = await self.call("getblock", [block_hash, 1])  # verbosity=1
        return block["tx"]

    async def get_raw_transaction(self, txid: str, verbose: bool = False) -> str | dict[str, Any]:
        """Get raw transaction (hex or decoded)."""
        return await self.call("getrawtransaction", [txid, verbose])

    async def get_headers_in_range(
        self, start_height: int, end_height: int
    ) -> list[tuple[int, str, str]]:
        """
        Get headers for a range of blocks.

        Returns list of (height, block_hash, header_hex) tuples.
        """
        headers = []
        for height in range(start_height, end_height + 1):
            block_hash = await self.get_block_hash(height)
            header_hex = await self.get_block_header_hex(block_hash)
            headers.append((height, block_hash, header_hex))
        return headers

    async def check_connectivity(self) -> bool:
        """Check if Bitcoin RPC is reachable."""
        try:
            await self.get_block_count()
            return True
        except Exception:
            return False
