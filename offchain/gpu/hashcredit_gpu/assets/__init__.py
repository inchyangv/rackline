"""
GPU-017 — legal entity / provider account / GPU asset rights services.

Registration is never approval: linking an account or registering an asset creates history rows and review
states only. Eligibility (`encumbrance.eligibility`) is false until an underwriter has verified ownership,
lease consent (if leased) and priority, and no review flag is open. Native evidence of an NFT mint, a hash
anchor or a token transfer is stored as a document reference and can never flip ownership, encumbrance or
control fields (`evidence.attach_native_evidence`, R2-D04/D05).
"""

from . import encumbrance, entities, evidence, registry
from .errors import AssetsError, Forbidden, InvalidState, NotFound, NotOwnershipEvidence

__all__ = [
    "AssetsError",
    "Forbidden",
    "InvalidState",
    "NotFound",
    "NotOwnershipEvidence",
    "encumbrance",
    "entities",
    "evidence",
    "registry",
]
