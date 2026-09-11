"""
SPV Relayer for HashCredit.

Automatically watches Bitcoin addresses, builds SPV proofs,
and submits them to HashCreditManager when confirmations are met.
"""

import asyncio
from dataclasses import dataclass
from typing import List, Optional
import structlog

from .rpc import BitcoinRPC, BitcoinRPCConfig
from .evm import EVMClient, EVMConfig
from .watcher import AddressWatcher, PayoutStore, PendingPayout, WatchedAddress
from .proof_builder import ProofBuilder

logger = structlog.get_logger()


@dataclass
class RelayerConfig:
    """Configuration for SPV relayer."""

    # Bitcoin RPC
    bitcoin_rpc: BitcoinRPCConfig

    # EVM
    evm: EVMConfig
    hash_credit_manager: str
    checkpoint_manager: str

    # Watched addresses
    watched_addresses: List[WatchedAddress]

    # Database URL (sqlite:///path or postgresql://...)
    database_url: str = "sqlite:///./spv_relayer.db"

    # Operational params
    required_confirmations: int = 6
    max_header_chain: int = 144  # Must match contract constant
    poll_interval_seconds: int = 60
    scan_batch_size: int = 10  # Blocks to scan per iteration


class SPVRelayer:
    """
    SPV Relayer that watches Bitcoin addresses and submits proofs.

    Workflow:
    1. Scan blocks for transactions to watched addresses
    2. Wait for required confirmations
    3. Select appropriate checkpoint
    4. Build SPV proof
    5. Submit to HashCreditManager
    6. Mark as submitted (dedupe)
    """

    def __init__(self, config: RelayerConfig):
        self.config = config
        self.btc_rpc = BitcoinRPC(config.bitcoin_rpc)
        self.evm_client = EVMClient(config.evm)
        self.store = PayoutStore(config.database_url)
        self.watcher = AddressWatcher(
            self.btc_rpc, config.watched_addresses, self.store
        )
        self.proof_builder = ProofBuilder(self.btc_rpc)
        self._running = False
        self._last_scanned_height: Optional[int] = None

    async def get_latest_checkpoint_height(self) -> int:
        """Get the latest checkpoint height from CheckpointManager."""
        return await self.evm_client.get_latest_checkpoint_height(
            self.config.checkpoint_manager
        )

    async def select_checkpoint(self, target_height: int) -> Optional[int]:
        """
        Select appropriate checkpoint for proof.

        The checkpoint must be:
        - Before target_height
        - Within max_header_chain blocks of target

        Returns checkpoint height or None if no suitable checkpoint.
        """
        latest_checkpoint = await self.get_latest_checkpoint_height()

        if latest_checkpoint == 0:
            logger.warning("No checkpoints registered")
            return None

        # Check if checkpoint is suitable
        chain_length = target_height - latest_checkpoint
        if chain_length <= 0:
            logger.warning(
                "Target height is before checkpoint",
                target=target_height,
                checkpoint=latest_checkpoint,
            )
            return None

        if chain_length > self.config.max_header_chain:
            logger.warning(
                "Header chain would be too long",
                chain_length=chain_length,
                max_allowed=self.config.max_header_chain,
            )
            return None

        return latest_checkpoint

    async def process_pending(self) -> int:
        """
        Process pending payouts that have enough confirmations.

        Returns number of payouts processed.
        """
        current_height = await self.btc_rpc.get_block_count()
        pending = self.store.get_pending()
        processed = 0

        for payout in pending:
            confirmations = current_height - payout.block_height + 1

            if confirmations < self.config.required_confirmations:
                logger.debug(
                    "Waiting for confirmations",
                    txid=payout.txid,
                    confirmations=confirmations,
                    required=self.config.required_confirmations,
                )
                continue

            # Select checkpoint
            checkpoint = await self.select_checkpoint(payout.block_height)
            if checkpoint is None:
                logger.warning(
                    "No suitable checkpoint for payout",
                    txid=payout.txid,
                    block_height=payout.block_height,
                )
                continue

            try:
                # Build and submit proof
                await self._submit_payout(payout, checkpoint)
                processed += 1
            except Exception as e:
                logger.error(
                    "Failed to submit payout",
                    txid=payout.txid,
                    error=str(e),
                )

        return processed

    async def _submit_payout(
        self, payout: PendingPayout, checkpoint_height: int
    ) -> None:
        """Build and submit proof for a payout."""
        logger.info(
            "Building proof",
            txid=payout.txid,
            vout=payout.output_index,
            checkpoint=checkpoint_height,
            target=payout.block_height,
        )

        # Build proof
        result = await self.proof_builder.build_proof(
            txid=payout.txid,
            output_index=payout.output_index,
            checkpoint_height=checkpoint_height,
            target_height=payout.block_height,
            borrower=payout.borrower,
        )

        # Encode and submit
        encoded = result.proof.encode_for_contract()

        logger.info(
            "Submitting proof",
            txid=payout.txid,
            borrower=payout.borrower,
            amount_sats=result.amount_sats,
            proof_size=len(encoded),
        )

        receipt = await self.evm_client.submit_payout(
            self.config.hash_credit_manager,
            encoded,
        )

        evm_tx_hash = receipt["transactionHash"].hex()
        logger.info(
            "Proof submitted successfully",
            txid=payout.txid,
            evm_tx_hash=evm_tx_hash,
            gas_used=receipt["gasUsed"],
        )

        # Mark as submitted
        self.store.mark_submitted(payout.txid, payout.output_index, evm_tx_hash)

    async def scan_new_blocks(self) -> List[PendingPayout]:
        """Scan for new blocks and transactions."""
        current_height = await self.btc_rpc.get_block_count()

        if self._last_scanned_height is None:
            # Start from a recent block
            self._last_scanned_height = max(
                current_height - self.config.scan_batch_size, 0
            )

        if current_height <= self._last_scanned_height:
            return []

        # Scan new blocks
        start = self._last_scanned_height + 1
        end = min(start + self.config.scan_batch_size - 1, current_height)

        logger.debug("Scanning blocks", start=start, end=end)

        payouts = await self.watcher.scan_range(start, end)
        self._last_scanned_height = end

        return payouts

    async def run_once(self) -> None:
        """Run one iteration of the relayer loop."""
        # Scan for new transactions
        new_payouts = await self.scan_new_blocks()
        if new_payouts:
            logger.info("Found new payouts", count=len(new_payouts))

        # Process pending payouts
        processed = await self.process_pending()
        if processed:
            logger.info("Processed payouts", count=processed)

    async def run(self) -> None:
        """Run the relayer loop."""
        self._running = True
        logger.info("Starting SPV relayer", addresses=len(self.config.watched_addresses))

        while self._running:
            try:
                await self.run_once()
            except Exception as e:
                logger.error("Error in relayer loop", error=str(e))

            await asyncio.sleep(self.config.poll_interval_seconds)

    def stop(self) -> None:
        """Stop the relayer."""
        self._running = False
        logger.info("Stopping SPV relayer")
