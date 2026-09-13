from __future__ import annotations


class AssetsError(Exception):
    """Base class for GPU-017 service errors (never swallowed into a success)."""


class NotFound(AssetsError):
    pass


class Forbidden(AssetsError):
    """Caller role may not perform this transition (docs/gpu/permissions-and-states.md)."""


class InvalidState(AssetsError):
    """The requested transition contradicts recorded history or an open right."""


class NotOwnershipEvidence(AssetsError):
    """Native proof of a mint/anchor/transfer is not ownership, unencumbrance or control evidence (R2-D05)."""
