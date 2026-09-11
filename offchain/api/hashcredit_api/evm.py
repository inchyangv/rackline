"""
EVM client utilities for HashCredit API.

Wallet-only API mode does not send any on-chain transactions.
This client is used only for connectivity checks.
"""

from web3 import AsyncHTTPProvider, AsyncWeb3

from .config import Settings


class EVMClient:
    """Minimal async EVM client used for read/connectivity checks only."""

    def __init__(self, settings: Settings):
        self.w3 = AsyncWeb3(AsyncHTTPProvider(settings.evm_rpc_url))

    async def check_connectivity(self) -> bool:
        """Check whether the configured EVM RPC endpoint is reachable."""
        try:
            await self.w3.eth.block_number
            return True
        except Exception:
            return False
