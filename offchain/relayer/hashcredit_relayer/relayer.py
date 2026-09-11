"""
Main relayer logic - watches Bitcoin, signs, and submits to EVM.
"""

import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

import structlog

from .bitcoin import BitcoinApiClient, BitcoinTx, TxOutput
from .config import RelayerConfig, WatchedBorrower
from .db import PayoutDatabase
from .evm import EvmClient, SubmitResult
from .signer import PayoutClaim, sign_payout_claim, txid_to_bytes32

logger = structlog.get_logger()


@dataclass
class RelayerState:
    """Current relayer state."""

    is_running: bool = False
    last_poll_time: Optional[datetime] = None
    payouts_submitted: int = 0
    payouts_failed: int = 0


class HashCreditRelayer:
    """
    Main relayer that:
    1. Watches Bitcoin addresses for incoming payouts
    2. Signs payout claims using EIP-712
    3. Submits proofs to HashCreditManager on EVM
    """

    def __init__(
        self,
        config: RelayerConfig,
        bitcoin_client: Optional[BitcoinApiClient] = None,
        evm_client: Optional[EvmClient] = None,
        database: Optional[PayoutDatabase] = None,
    ):
        self.config = config
        self.state = RelayerState()

        # Initialize clients
        settings = config.settings

        self.bitcoin = bitcoin_client or BitcoinApiClient(settings.bitcoin_api_url)

        if settings.private_key and settings.hash_credit_manager:
            self.evm = evm_client or EvmClient(
                rpc_url=settings.rpc_url,
                private_key=settings.private_key,
                manager_address=settings.hash_credit_manager,
            )
        else:
            self.evm = None
            logger.warning("EVM client not configured - dry run mode")

        # Use database URL directly (supports SQLite and PostgreSQL)
        self.db = database or PayoutDatabase(settings.database_url)

        logger.info(
            "relayer_initialized",
            bitcoin_api=settings.bitcoin_api_url,
            confirmations_required=settings.confirmations_required,
            poll_interval=settings.poll_interval_seconds,
            watched_borrowers=len(config.watched_borrowers),
        )

    def run_once(self) -> list[SubmitResult]:
        """
        Run one cycle of the relayer.

        Returns list of submission results.
        """
        results = []
        settings = self.config.settings

        for borrower in self.config.watched_borrowers:
            try:
                borrower_results = self._process_borrower(borrower)
                results.extend(borrower_results)
            except Exception as e:
                logger.error(
                    "borrower_processing_error",
                    borrower=borrower.evm_address,
                    btc_address=borrower.btc_address,
                    error=str(e),
                )

        self.state.last_poll_time = datetime.now()
        return results

    def run(self) -> None:
        """Run the relayer continuously."""
        self.state.is_running = True
        settings = self.config.settings

        logger.info("relayer_starting", poll_interval=settings.poll_interval_seconds)

        while self.state.is_running:
            try:
                results = self.run_once()

                for result in results:
                    if result.success:
                        self.state.payouts_submitted += 1
                    else:
                        self.state.payouts_failed += 1

                logger.info(
                    "poll_cycle_complete",
                    submitted=self.state.payouts_submitted,
                    failed=self.state.payouts_failed,
                )

            except Exception as e:
                logger.error("poll_cycle_error", error=str(e))

            time.sleep(settings.poll_interval_seconds)

    def stop(self) -> None:
        """Stop the relayer."""
        self.state.is_running = False
        logger.info("relayer_stopping")

    def _process_borrower(self, borrower: WatchedBorrower) -> list[SubmitResult]:
        """Process payouts for a single borrower."""
        settings = self.config.settings
        results = []

        logger.debug(
            "checking_borrower",
            evm_address=borrower.evm_address,
            btc_address=borrower.btc_address,
        )

        # Find confirmed payouts
        payouts = self.bitcoin.find_payouts_to_address(
            borrower.btc_address,
            min_confirmations=settings.confirmations_required,
        )

        for tx, output in payouts:
            # Check if already processed locally
            if self.db.is_processed(tx.txid, output.vout):
                continue

            # Check if already processed on-chain
            txid_bytes = txid_to_bytes32(tx.txid)
            if self.evm and self.evm.is_payout_processed(txid_bytes, output.vout):
                # Mark in local DB too
                self.db.mark_processed(
                    txid=tx.txid,
                    vout=output.vout,
                    borrower=borrower.evm_address,
                    amount_sats=output.value_sats,
                    block_height=tx.block_height or 0,
                    status="confirmed",
                )
                continue

            # Create and submit payout claim
            result = self._submit_payout(borrower, tx, output)
            results.append(result)

        return results

    def _submit_payout(
        self,
        borrower: WatchedBorrower,
        tx: BitcoinTx,
        output: TxOutput,
    ) -> SubmitResult:
        """Create, sign, and submit a payout claim."""
        settings = self.config.settings

        # Mark as pending in DB
        self.db.mark_processed(
            txid=tx.txid,
            vout=output.vout,
            borrower=borrower.evm_address,
            amount_sats=output.value_sats,
            block_height=tx.block_height or 0,
            status="pending",
        )

        # Create claim
        deadline = int((datetime.now() + timedelta(hours=1)).timestamp())
        claim = PayoutClaim(
            borrower=borrower.evm_address,
            txid=txid_to_bytes32(tx.txid),
            vout=output.vout,
            amount_sats=output.value_sats,
            block_height=tx.block_height or 0,
            block_timestamp=tx.block_time or int(datetime.now().timestamp()),
            deadline=deadline,
        )

        # Sign claim
        signature = sign_payout_claim(
            claim=claim,
            private_key=settings.relayer_private_key,
            chain_id=settings.chain_id,
            verifying_contract=settings.verifier,
        )

        logger.info(
            "payout_claim_signed",
            borrower=borrower.evm_address,
            txid=tx.txid,
            vout=output.vout,
            amount_sats=output.value_sats,
            block_height=tx.block_height,
        )

        # Submit to EVM
        if self.evm is None:
            logger.warning("dry_run_mode", message="EVM client not configured")
            return SubmitResult(success=True, error="Dry run - not submitted")

        result = self.evm.submit_payout(claim, signature)

        # Update DB status
        if result.success:
            self.db.update_status(tx.txid, output.vout, "confirmed", result.tx_hash)
        else:
            self.db.update_status(tx.txid, output.vout, "failed")

        return result
