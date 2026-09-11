"""
HashCredit Relayer

Watches Bitcoin blockchain for payout transactions to registered borrowers
and submits EIP-712 signed proofs to the HashCreditManager on EVM.

Hackathon MVP: Uses mempool.space API for simplicity.
Production: Can be upgraded to Bitcoin Core RPC with txindex.

Usage:
    # Check payouts to an address
    hashcredit-relayer check bc1q...

    # Run the relayer
    hashcredit-relayer run --btc-address bc1q... --evm-address 0x...

    # Run once (for testing)
    hashcredit-relayer run --once --btc-address bc1q... --evm-address 0x...
"""

__version__ = "0.1.0"

from .config import RelayerConfig, WatchedBorrower
from .relayer import HashCreditRelayer
from .bitcoin import BitcoinApiClient
from .signer import PayoutClaim, sign_payout_claim
from .evm import EvmClient
from .db import PayoutDatabase

__all__ = [
    "__version__",
    "RelayerConfig",
    "WatchedBorrower",
    "HashCreditRelayer",
    "BitcoinApiClient",
    "PayoutClaim",
    "sign_payout_claim",
    "EvmClient",
    "PayoutDatabase",
]
