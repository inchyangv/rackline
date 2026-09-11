"""
EVM client for interacting with HashCredit contracts.
"""

from typing import Any, Optional

from eth_account import Account
from web3 import AsyncWeb3, AsyncHTTPProvider
from web3.types import TxReceipt

from .config import Settings


# Contract ABIs (minimal)
CHECKPOINT_MANAGER_ABI = [
    {
        "inputs": [
            {"name": "height", "type": "uint32"},
            {"name": "blockHash", "type": "bytes32"},
            {"name": "chainWork", "type": "uint256"},
            {"name": "timestamp", "type": "uint32"},
            {"name": "bits", "type": "uint32"},
        ],
        "name": "setCheckpoint",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "latestCheckpointHeight",
        "outputs": [{"name": "", "type": "uint32"}],
        "stateMutability": "view",
        "type": "function",
    },
]

BTC_SPV_VERIFIER_ABI = [
    {
        "inputs": [
            {"name": "borrower", "type": "address"},
            {"name": "pubkeyHash", "type": "bytes20"},
        ],
        "name": "setBorrowerPubkeyHash",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
]

HASH_CREDIT_MANAGER_ABI = [
    {
        "inputs": [{"name": "proof", "type": "bytes"}],
        "name": "submitPayout",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
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
]


class EVMClient:
    """
    Async EVM client for contract interactions.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.w3 = AsyncWeb3(AsyncHTTPProvider(settings.evm_rpc_url))
        self.account = (
            Account.from_key(settings.private_key) if settings.private_key else None
        )

    @property
    def address(self) -> str:
        """Get account address."""
        if not self.account:
            raise ValueError("No private key configured")
        return self.account.address

    async def check_connectivity(self) -> bool:
        """Check if EVM RPC is reachable."""
        try:
            await self.w3.eth.block_number
            return True
        except Exception:
            return False

    async def get_nonce(self) -> int:
        """Get next nonce for account."""
        return await self.w3.eth.get_transaction_count(self.address)

    async def get_gas_price(self) -> int:
        """Get current gas price."""
        return await self.w3.eth.gas_price

    async def send_transaction(
        self,
        to: str,
        data: bytes,
        gas_limit: int = 500000,
        value: int = 0,
    ) -> TxReceipt:
        """Send a transaction and wait for receipt."""
        if not self.account:
            raise ValueError("No private key configured")

        nonce = await self.get_nonce()
        gas_price = await self.get_gas_price()

        tx = {
            "chainId": self.settings.chain_id,
            "nonce": nonce,
            "to": to,
            "value": value,
            "gas": gas_limit,
            "gasPrice": gas_price,
            "data": data,
        }

        signed = self.account.sign_transaction(tx)
        tx_hash = await self.w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = await self.w3.eth.wait_for_transaction_receipt(tx_hash)

        return receipt

    def get_checkpoint_manager(self) -> Any:
        """Get CheckpointManager contract instance."""
        if not self.settings.checkpoint_manager:
            raise ValueError("CHECKPOINT_MANAGER not configured")
        return self.w3.eth.contract(
            address=self.w3.to_checksum_address(self.settings.checkpoint_manager),
            abi=CHECKPOINT_MANAGER_ABI,
        )

    def get_spv_verifier(self) -> Any:
        """Get BtcSpvVerifier contract instance."""
        if not self.settings.btc_spv_verifier:
            raise ValueError("BTC_SPV_VERIFIER not configured")
        return self.w3.eth.contract(
            address=self.w3.to_checksum_address(self.settings.btc_spv_verifier),
            abi=BTC_SPV_VERIFIER_ABI,
        )

    def get_hash_credit_manager(self) -> Any:
        """Get HashCreditManager contract instance."""
        if not self.settings.hash_credit_manager:
            raise ValueError("HASH_CREDIT_MANAGER not configured")
        return self.w3.eth.contract(
            address=self.w3.to_checksum_address(self.settings.hash_credit_manager),
            abi=HASH_CREDIT_MANAGER_ABI,
        )

    async def set_checkpoint(
        self,
        height: int,
        block_hash: bytes,
        chain_work: int,
        timestamp: int,
        bits: int,
    ) -> TxReceipt:
        """Call CheckpointManager.setCheckpoint()."""
        contract = self.get_checkpoint_manager()
        data = contract.encodeABI(
            fn_name="setCheckpoint",
            args=[height, block_hash, chain_work, timestamp, bits],
        )
        return await self.send_transaction(
            self.settings.checkpoint_manager or "",
            bytes.fromhex(data[2:]),
        )

    async def set_borrower_pubkey_hash(
        self,
        borrower: str,
        pubkey_hash: bytes,
    ) -> TxReceipt:
        """Call BtcSpvVerifier.setBorrowerPubkeyHash()."""
        contract = self.get_spv_verifier()
        data = contract.encodeABI(
            fn_name="setBorrowerPubkeyHash",
            args=[self.w3.to_checksum_address(borrower), pubkey_hash],
        )
        return await self.send_transaction(
            self.settings.btc_spv_verifier or "",
            bytes.fromhex(data[2:]),
        )

    async def submit_payout(self, proof: bytes) -> TxReceipt:
        """Call HashCreditManager.submitPayout()."""
        contract = self.get_hash_credit_manager()
        data = contract.encodeABI(
            fn_name="submitPayout",
            args=[proof],
        )
        return await self.send_transaction(
            self.settings.hash_credit_manager or "",
            bytes.fromhex(data[2:]),
            gas_limit=800000,
        )

    async def register_borrower(self, borrower: str, btc_payout_key_hash: bytes) -> TxReceipt:
        """Call HashCreditManager.registerBorrower()."""
        contract = self.get_hash_credit_manager()
        data = contract.encodeABI(
            fn_name="registerBorrower",
            args=[self.w3.to_checksum_address(borrower), btc_payout_key_hash],
        )
        return await self.send_transaction(
            self.settings.hash_credit_manager or "",
            bytes.fromhex(data[2:]),
            gas_limit=500000,
        )
