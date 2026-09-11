"""
HashCredit Relayer

Watches Bitcoin blockchain for payout transactions to registered borrowers
and submits EIP-712 signed proofs to the HashCreditManager on EVM.

Hackathon MVP: Uses mempool.space API for simplicity.
Production: Can be upgraded to Bitcoin Core RPC with txindex.
"""

__version__ = "0.1.0"
__all__ = ["__version__"]
