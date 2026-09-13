"""
Read-only EVM client for HashCredit API.

This client never holds a signing key. Health checks and on-chain reads live here; the testnet
demo admin path (the only place the API ever signs) is in `demo.py` and is mounted only when
`API_PROFILE=testnet_demo` (GPU-001).
"""

from web3 import AsyncHTTPProvider, AsyncWeb3

from .config import Settings

# Read-only ABI fragments used by the API.
MANAGER_READ_ABI = [
    {
        "inputs": [],
        "name": "stablecoin",
        "outputs": [{"name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
]

VERIFIER_READ_ABI = [
    {
        "inputs": [{"name": "", "type": "address"}],
        "name": "borrowerPubkeyHash",
        "outputs": [{"name": "", "type": "bytes20"}],
        "stateMutability": "view",
        "type": "function",
    },
]


class EVMClient:
    """Async EVM client for connectivity checks and read-only contract queries."""

    def __init__(self, settings: Settings):
        self.w3 = AsyncWeb3(AsyncHTTPProvider(settings.evm_rpc_url))
        self.chain_id = settings.chain_id
        self.manager_address = settings.hash_credit_manager
        self.verifier_address = settings.btc_spv_verifier

    @property
    def has_admin_key(self) -> bool:
        """The read-only client never has a key (kept for callers that used to check it)."""
        return False

    async def check_connectivity(self) -> bool:
        """Check whether the configured EVM RPC endpoint is reachable."""
        try:
            await self.w3.eth.block_number
            return True
        except Exception:
            return False

    async def get_chain_id(self) -> int:
        return int(await self.w3.eth.chain_id)

    async def read_manager_stablecoin(self) -> str:
        if not self.manager_address:
            raise RuntimeError("HASH_CREDIT_MANAGER address not configured")
        contract = self.w3.eth.contract(
            address=self.w3.to_checksum_address(self.manager_address), abi=MANAGER_READ_ABI
        )
        return str(await contract.functions.stablecoin().call())

    async def read_verifier_pubkey_hash(self, borrower: str) -> bytes:
        if not self.verifier_address:
            raise RuntimeError("BTC_SPV_VERIFIER address not configured")
        contract = self.w3.eth.contract(
            address=self.w3.to_checksum_address(self.verifier_address), abi=VERIFIER_READ_ABI
        )
        raw = await contract.functions.borrowerPubkeyHash(self.w3.to_checksum_address(borrower)).call()
        return bytes(raw)
