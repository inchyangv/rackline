"""
EVM interaction for submitting payout proofs.
"""

from dataclasses import dataclass
from typing import Optional

from eth_account import Account
from web3 import Web3
from web3.types import TxReceipt
import structlog

from .signer import PayoutClaim

logger = structlog.get_logger()


# HashCreditManager ABI (minimal for submitPayout)
MANAGER_ABI = [
    {
        "inputs": [{"name": "proof", "type": "bytes"}],
        "name": "submitPayout",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [
            {"name": "txid", "type": "bytes32"},
            {"name": "vout", "type": "uint32"},
        ],
        "name": "isPayoutProcessed",
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
]


@dataclass
class SubmitResult:
    """Result of submitting a payout proof."""

    success: bool
    tx_hash: Optional[str] = None
    error: Optional[str] = None
    gas_used: Optional[int] = None


class EvmClient:
    """Client for EVM interactions."""

    def __init__(self, rpc_url: str, private_key: str, manager_address: str):
        self.w3 = Web3(Web3.HTTPProvider(rpc_url))
        self.account = Account.from_key(private_key)
        self.manager = self.w3.eth.contract(
            address=Web3.to_checksum_address(manager_address),
            abi=MANAGER_ABI,
        )

        logger.info(
            "evm_client_initialized",
            rpc_url=rpc_url,
            manager=manager_address,
            sender=self.account.address,
        )

    def is_payout_processed(self, txid: bytes, vout: int) -> bool:
        """Check if a payout has already been processed."""
        return self.manager.functions.isPayoutProcessed(txid, vout).call()

    def encode_proof(self, claim: PayoutClaim, signature: bytes) -> bytes:
        """
        Encode payout claim and signature into proof bytes.

        Format: abi.encode(borrower, txid, vout, amountSats, blockHeight, blockTimestamp, deadline, signature)
        """
        # Ensure txid is bytes32
        txid_bytes = claim.txid if isinstance(claim.txid, bytes) else bytes.fromhex(
            claim.txid.replace("0x", "")
        )

        return self.w3.codec.encode(
            ["address", "bytes32", "uint32", "uint64", "uint32", "uint32", "uint256", "bytes"],
            [
                claim.borrower,
                txid_bytes,
                claim.vout,
                claim.amount_sats,
                claim.block_height,
                claim.block_timestamp,
                claim.deadline,
                signature,
            ],
        )

    def submit_payout(self, claim: PayoutClaim, signature: bytes) -> SubmitResult:
        """Submit a payout proof to the manager contract."""
        try:
            # Check if already processed
            txid_bytes = claim.txid if isinstance(claim.txid, bytes) else bytes.fromhex(
                claim.txid.replace("0x", "")
            )
            if self.is_payout_processed(txid_bytes, claim.vout):
                logger.info(
                    "payout_already_processed",
                    txid=txid_bytes.hex(),
                    vout=claim.vout,
                )
                return SubmitResult(
                    success=False,
                    error="Payout already processed",
                )

            # Encode proof
            proof = self.encode_proof(claim, signature)

            # Build transaction
            nonce = self.w3.eth.get_transaction_count(self.account.address)
            gas_price = self.w3.eth.gas_price

            tx = self.manager.functions.submitPayout(proof).build_transaction(
                {
                    "from": self.account.address,
                    "nonce": nonce,
                    "gasPrice": gas_price,
                    "gas": 500_000,  # Estimate
                }
            )

            # Sign and send
            signed_tx = self.account.sign_transaction(tx)
            tx_hash = self.w3.eth.send_raw_transaction(signed_tx.raw_transaction)

            logger.info(
                "payout_tx_sent",
                tx_hash=tx_hash.hex(),
                borrower=claim.borrower,
                txid=txid_bytes.hex(),
                vout=claim.vout,
                amount_sats=claim.amount_sats,
            )

            # Wait for receipt
            receipt: TxReceipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

            if receipt["status"] == 1:
                logger.info(
                    "payout_tx_confirmed",
                    tx_hash=tx_hash.hex(),
                    gas_used=receipt["gasUsed"],
                )
                return SubmitResult(
                    success=True,
                    tx_hash=tx_hash.hex(),
                    gas_used=receipt["gasUsed"],
                )
            else:
                logger.error(
                    "payout_tx_reverted",
                    tx_hash=tx_hash.hex(),
                )
                return SubmitResult(
                    success=False,
                    tx_hash=tx_hash.hex(),
                    error="Transaction reverted",
                )

        except Exception as e:
            logger.error("payout_submission_error", error=str(e))
            return SubmitResult(success=False, error=str(e))
