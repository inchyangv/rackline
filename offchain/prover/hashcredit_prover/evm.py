"""
EVM utilities for interacting with Creditcoin/Ethereum contracts.
"""

import os
from typing import Any

from eth_account import Account
from pydantic import BaseModel
from web3 import AsyncWeb3, AsyncHTTPProvider
from web3.types import TxReceipt


class EVMConfig(BaseModel):
    """Configuration for EVM connection."""

    rpc_url: str = "http://localhost:8545"
    chain_id: int = 102031  # Creditcoin testnet
    private_key: str = ""


# Minimal ABIs for contracts we interact with
CHECKPOINT_MANAGER_ABI = [
    {
        "inputs": [
            {"name": "height", "type": "uint32"},
            {"name": "blockHash", "type": "bytes32"},
            {"name": "chainWork", "type": "uint256"},
            {"name": "timestamp", "type": "uint32"},
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
    {
        "inputs": [{"name": "height", "type": "uint32"}],
        "name": "getCheckpoint",
        "outputs": [
            {
                "components": [
                    {"name": "blockHash", "type": "bytes32"},
                    {"name": "height", "type": "uint32"},
                    {"name": "chainWork", "type": "uint256"},
                    {"name": "timestamp", "type": "uint32"},
                ],
                "name": "",
                "type": "tuple",
            }
        ],
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
    {
        "inputs": [{"name": "borrower", "type": "address"}],
        "name": "getBorrowerPubkeyHash",
        "outputs": [{"name": "", "type": "bytes20"}],
        "stateMutability": "view",
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
    {
        "inputs": [{"name": "borrower", "type": "address"}],
        "name": "getBorrowerInfo",
        "outputs": [
            {
                "components": [
                    {"name": "status", "type": "uint8"},
                    {"name": "btcPayoutKeyHash", "type": "bytes32"},
                    {"name": "totalRevenueSats", "type": "uint128"},
                    {"name": "trailingRevenueSats", "type": "uint128"},
                    {"name": "creditLimit", "type": "uint128"},
                    {"name": "currentDebt", "type": "uint128"},
                    {"name": "lastPayoutTimestamp", "type": "uint64"},
                    {"name": "registeredAt", "type": "uint64"},
                    {"name": "payoutCount", "type": "uint32"},
                ],
                "name": "",
                "type": "tuple",
            }
        ],
        "stateMutability": "view",
        "type": "function",
    },
]


class EVMClient:
    """
    Async EVM client for interacting with HashCredit contracts.
    """

    def __init__(self, config: EVMConfig):
        self.config = config
        self.w3 = AsyncWeb3(AsyncHTTPProvider(config.rpc_url))
        self.account = Account.from_key(config.private_key) if config.private_key else None

    @property
    def address(self) -> str:
        """Get account address."""
        if not self.account:
            raise ValueError("No private key configured")
        return self.account.address

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
        """
        Send a transaction and wait for receipt.
        """
        if not self.account:
            raise ValueError("No private key configured")

        nonce = await self.get_nonce()
        gas_price = await self.get_gas_price()

        tx = {
            "chainId": self.config.chain_id,
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

    def get_checkpoint_manager(self, address: str) -> Any:
        """Get CheckpointManager contract instance."""
        return self.w3.eth.contract(
            address=self.w3.to_checksum_address(address),
            abi=CHECKPOINT_MANAGER_ABI,
        )

    def get_spv_verifier(self, address: str) -> Any:
        """Get BtcSpvVerifier contract instance."""
        return self.w3.eth.contract(
            address=self.w3.to_checksum_address(address),
            abi=BTC_SPV_VERIFIER_ABI,
        )

    def get_hash_credit_manager(self, address: str) -> Any:
        """Get HashCreditManager contract instance."""
        return self.w3.eth.contract(
            address=self.w3.to_checksum_address(address),
            abi=HASH_CREDIT_MANAGER_ABI,
        )

    async def set_checkpoint(
        self,
        contract_address: str,
        height: int,
        block_hash: bytes,
        chain_work: int,
        timestamp: int,
    ) -> TxReceipt:
        """
        Call CheckpointManager.setCheckpoint().

        Args:
            contract_address: CheckpointManager address
            height: Bitcoin block height
            block_hash: 32-byte block hash (internal byte order)
            chain_work: Cumulative chain work
            timestamp: Block timestamp
        """
        contract = self.get_checkpoint_manager(contract_address)
        data = contract.encodeABI(
            fn_name="setCheckpoint",
            args=[height, block_hash, chain_work, timestamp],
        )
        return await self.send_transaction(contract_address, bytes.fromhex(data[2:]))

    async def get_latest_checkpoint_height(self, contract_address: str) -> int:
        """Get the latest checkpoint height."""
        contract = self.get_checkpoint_manager(contract_address)
        return await contract.functions.latestCheckpointHeight().call()

    async def get_checkpoint(self, contract_address: str, height: int) -> dict[str, Any]:
        """Get checkpoint at height."""
        contract = self.get_checkpoint_manager(contract_address)
        result = await contract.functions.getCheckpoint(height).call()
        return {
            "blockHash": result[0].hex(),
            "height": result[1],
            "chainWork": result[2],
            "timestamp": result[3],
        }

    async def set_borrower_pubkey_hash(
        self,
        contract_address: str,
        borrower: str,
        pubkey_hash: bytes,
    ) -> TxReceipt:
        """
        Call BtcSpvVerifier.setBorrowerPubkeyHash().
        """
        contract = self.get_spv_verifier(contract_address)
        data = contract.encodeABI(
            fn_name="setBorrowerPubkeyHash",
            args=[self.w3.to_checksum_address(borrower), pubkey_hash],
        )
        return await self.send_transaction(contract_address, bytes.fromhex(data[2:]))

    async def get_borrower_pubkey_hash(
        self, contract_address: str, borrower: str
    ) -> bytes:
        """Get borrower's registered pubkey hash."""
        contract = self.get_spv_verifier(contract_address)
        return await contract.functions.getBorrowerPubkeyHash(
            self.w3.to_checksum_address(borrower)
        ).call()

    async def submit_payout(
        self,
        contract_address: str,
        proof: bytes,
    ) -> TxReceipt:
        """
        Call HashCreditManager.submitPayout().
        """
        contract = self.get_hash_credit_manager(contract_address)
        data = contract.encodeABI(
            fn_name="submitPayout",
            args=[proof],
        )
        return await self.send_transaction(
            contract_address, bytes.fromhex(data[2:]), gas_limit=800000
        )


def create_evm_client_from_env() -> EVMClient:
    """Create EVM client from environment variables."""
    config = EVMConfig(
        rpc_url=os.getenv("EVM_RPC_URL", os.getenv("RPC_URL", "http://localhost:8545")),
        chain_id=int(os.getenv("CHAIN_ID", "102031")),
        private_key=os.getenv("PRIVATE_KEY", ""),
    )
    return EVMClient(config)
