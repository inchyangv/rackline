"""
Bitcoin RPC client for fetching blocks and transactions.
"""

import httpx
from typing import Any
from pydantic import BaseModel


class BitcoinRPCConfig(BaseModel):
    """Configuration for Bitcoin RPC connection."""

    url: str = "http://localhost:8332"
    user: str = ""
    password: str = ""
    timeout: float = 30.0


class BitcoinRPCError(Exception):
    """Error from Bitcoin RPC call."""

    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message
        super().__init__(f"RPC Error {code}: {message}")


class BitcoinRPC:
    """
    Async Bitcoin Core RPC client.

    Provides methods for fetching blocks, transactions, and headers
    needed for SPV proof generation.
    """

    def __init__(self, config: BitcoinRPCConfig):
        self.config = config
        self._request_id = 0

    async def _call(self, method: str, params: list[Any] | None = None) -> Any:
        """Make RPC call."""
        self._request_id += 1
        payload = {
            "jsonrpc": "1.0",
            "id": self._request_id,
            "method": method,
            "params": params or [],
        }

        auth = None
        if self.config.user and self.config.password:
            auth = (self.config.user, self.config.password)

        async with httpx.AsyncClient(timeout=self.config.timeout) as client:
            response = await client.post(
                self.config.url,
                json=payload,
                auth=auth,
            )
            response.raise_for_status()
            result = response.json()

        if result.get("error"):
            error = result["error"]
            raise BitcoinRPCError(error.get("code", -1), error.get("message", "Unknown error"))

        return result.get("result")

    async def get_block_count(self) -> int:
        """Get current block height."""
        return await self._call("getblockcount")

    async def get_block_hash(self, height: int) -> str:
        """Get block hash at height (display format, reversed)."""
        return await self._call("getblockhash", [height])

    async def get_block_header(self, block_hash: str, verbose: bool = True) -> dict[str, Any]:
        """Get block header."""
        return await self._call("getblockheader", [block_hash, verbose])

    async def get_block_header_hex(self, block_hash: str) -> str:
        """Get block header as hex string (80 bytes = 160 hex chars)."""
        return await self._call("getblockheader", [block_hash, False])

    async def get_block(self, block_hash: str, verbosity: int = 1) -> dict[str, Any]:
        """
        Get block.
        verbosity: 0=hex, 1=json, 2=json with tx details
        """
        return await self._call("getblock", [block_hash, verbosity])

    async def get_raw_transaction(self, txid: str, verbose: bool = False) -> str | dict[str, Any]:
        """
        Get raw transaction.
        If verbose=False, returns hex string.
        If verbose=True, returns decoded transaction.
        """
        return await self._call("getrawtransaction", [txid, verbose])

    async def get_tx_out(
        self, txid: str, vout: int, include_mempool: bool = True
    ) -> dict[str, Any] | None:
        """Get transaction output."""
        return await self._call("gettxout", [txid, vout, include_mempool])

    # Convenience methods for proof building

    async def get_block_txids(self, block_hash: str) -> list[str]:
        """Get list of transaction IDs in a block."""
        block = await self.get_block(block_hash, verbosity=1)
        return block.get("tx", [])

    async def get_headers_in_range(
        self, start_height: int, end_height: int
    ) -> list[tuple[int, str, str]]:
        """
        Get headers for range of blocks.
        Returns list of (height, block_hash, header_hex).
        """
        headers = []
        for height in range(start_height, end_height + 1):
            block_hash = await self.get_block_hash(height)
            header_hex = await self.get_block_header_hex(block_hash)
            headers.append((height, block_hash, header_hex))
        return headers


class MockBitcoinRPC:
    """
    Mock Bitcoin RPC for testing without a real node.
    Provides predefined test data.
    """

    def __init__(self) -> None:
        # Store mock data
        self._blocks: dict[str, dict[str, Any]] = {}
        self._headers: dict[str, str] = {}
        self._txs: dict[str, str] = {}
        self._height_to_hash: dict[int, str] = {}

    def add_block(
        self,
        height: int,
        block_hash: str,
        header_hex: str,
        txids: list[str],
    ) -> None:
        """Add a mock block."""
        self._height_to_hash[height] = block_hash
        self._headers[block_hash] = header_hex
        self._blocks[block_hash] = {
            "hash": block_hash,
            "height": height,
            "tx": txids,
        }

    def add_transaction(self, txid: str, raw_tx_hex: str) -> None:
        """Add a mock transaction."""
        self._txs[txid] = raw_tx_hex

    async def get_block_count(self) -> int:
        return max(self._height_to_hash.keys()) if self._height_to_hash else 0

    async def get_block_hash(self, height: int) -> str:
        if height not in self._height_to_hash:
            raise BitcoinRPCError(-8, f"Block height {height} not found")
        return self._height_to_hash[height]

    async def get_block_header_hex(self, block_hash: str) -> str:
        if block_hash not in self._headers:
            raise BitcoinRPCError(-5, f"Block {block_hash} not found")
        return self._headers[block_hash]

    async def get_block(self, block_hash: str, verbosity: int = 1) -> dict[str, Any]:
        if block_hash not in self._blocks:
            raise BitcoinRPCError(-5, f"Block {block_hash} not found")
        return self._blocks[block_hash]

    async def get_raw_transaction(self, txid: str, verbose: bool = False) -> str:
        if txid not in self._txs:
            raise BitcoinRPCError(-5, f"Transaction {txid} not found")
        return self._txs[txid]

    async def get_block_txids(self, block_hash: str) -> list[str]:
        block = await self.get_block(block_hash)
        return block.get("tx", [])

    async def get_headers_in_range(
        self, start_height: int, end_height: int
    ) -> list[tuple[int, str, str]]:
        headers = []
        for height in range(start_height, end_height + 1):
            block_hash = await self.get_block_hash(height)
            header_hex = await self.get_block_header_hex(block_hash)
            headers.append((height, block_hash, header_hex))
        return headers
