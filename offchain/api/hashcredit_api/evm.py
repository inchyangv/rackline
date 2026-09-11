"""
EVM client utilities for HashCredit API.

Supports read-only connectivity checks and admin transactions
(registerBorrower / grantTestnetCredit) via ADMIN_PRIVATE_KEY.
"""

from web3 import AsyncHTTPProvider, AsyncWeb3
from eth_account import Account

from .config import Settings

# Minimal ABI fragments needed for admin calls
MANAGER_ABI = [
    {
        "inputs": [
            {"name": "borrower", "type": "address"},
            {"name": "btcPayoutKeyHash", "type": "bytes32"},
        ],
        "name": "registerBorrower",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [
            {"name": "borrower", "type": "address"},
            {"name": "creditLimitAmount", "type": "uint128"},
        ],
        "name": "grantTestnetCredit",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
]


class EVMClient:
    """Async EVM client for connectivity checks and admin transactions."""

    def __init__(self, settings: Settings):
        self.w3 = AsyncWeb3(AsyncHTTPProvider(settings.evm_rpc_url))
        self.chain_id = settings.chain_id
        self.manager_address = settings.hash_credit_manager

        pk = settings.admin_private_key
        if pk:
            pk = pk.strip()
            if not pk.startswith("0x"):
                pk = "0x" + pk
            self.account = Account.from_key(pk)
        else:
            self.account = None

    @property
    def has_admin_key(self) -> bool:
        return self.account is not None

    async def check_connectivity(self) -> bool:
        """Check whether the configured EVM RPC endpoint is reachable."""
        try:
            await self.w3.eth.block_number
            return True
        except Exception:
            return False

    async def register_and_grant(
        self,
        borrower: str,
        btc_payout_key_hash: bytes,
        credit_amount: int = 1_000_000_000,
    ) -> dict:
        """
        Call registerBorrower + grantTestnetCredit from the admin wallet.

        Returns dict with tx hashes for both transactions.
        """
        if not self.account:
            raise RuntimeError("ADMIN_PRIVATE_KEY not configured")
        if not self.manager_address:
            raise RuntimeError("HASH_CREDIT_MANAGER address not configured")

        manager_addr = self.w3.to_checksum_address(self.manager_address)
        borrower_addr = self.w3.to_checksum_address(borrower)
        contract = self.w3.eth.contract(address=manager_addr, abi=MANAGER_ABI)

        # --- registerBorrower ---
        nonce = await self.w3.eth.get_transaction_count(self.account.address)
        register_tx = await contract.functions.registerBorrower(
            borrower_addr,
            btc_payout_key_hash,
        ).build_transaction({
            "from": self.account.address,
            "nonce": nonce,
            "chainId": self.chain_id,
            "gas": 200_000,
        })
        signed_register = self.account.sign_transaction(register_tx)
        register_hash = await self.w3.eth.send_raw_transaction(signed_register.raw_transaction)
        register_receipt = await self.w3.eth.wait_for_transaction_receipt(register_hash, timeout=60)
        if register_receipt["status"] != 1:
            raise RuntimeError(f"registerBorrower reverted (tx: {register_hash.hex()})")

        # --- grantTestnetCredit ---
        nonce2 = await self.w3.eth.get_transaction_count(self.account.address)
        grant_tx = await contract.functions.grantTestnetCredit(
            borrower_addr,
            credit_amount,
        ).build_transaction({
            "from": self.account.address,
            "nonce": nonce2,
            "chainId": self.chain_id,
            "gas": 200_000,
        })
        signed_grant = self.account.sign_transaction(grant_tx)
        grant_hash = await self.w3.eth.send_raw_transaction(signed_grant.raw_transaction)
        grant_receipt = await self.w3.eth.wait_for_transaction_receipt(grant_hash, timeout=60)
        if grant_receipt["status"] != 1:
            raise RuntimeError(f"grantTestnetCredit reverted (tx: {grant_hash.hex()})")

        return {
            "register_tx": register_hash.hex(),
            "grant_tx": grant_hash.hex(),
        }
