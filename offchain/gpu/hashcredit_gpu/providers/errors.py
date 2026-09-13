"""Typed adapter errors (GPU-019). None of these is ever converted into a successful observation."""

from __future__ import annotations


class ProviderAdapterError(Exception):
    """Base class for every adapter failure."""


class UnsupportedOperation(ProviderAdapterError):
    """The provider (or this adapter) does not support the operation; UNKNOWN counts as unsupported."""


class UnsupportedChainError(ProviderAdapterError):
    """The provider reported an asset/payout on a chain we do not know or the manifest does not list."""


class MalformedResponse(ProviderAdapterError):
    """Provider payload cannot be normalized (missing field, wrong type, inconsistent revision...)."""


class MissingUnit(MalformedResponse):
    """An amount arrived without an explicit asset (chain/token/decimals) or as a float."""


class ExpiredData(ProviderAdapterError):
    """Observation is older than the caller's freshness bound (`as_of` window) — never silently used."""


class RateLimited(ProviderAdapterError):
    def __init__(self, retry_after_seconds: int | None = None):
        super().__init__(f"rate limited (retry_after={retry_after_seconds})")
        self.retry_after_seconds = retry_after_seconds


class AuthError(ProviderAdapterError):
    """Credential rejected/expired. Message must never contain the credential value."""


class NotProductionAdmissible(ProviderAdapterError):
    """Adapter/fixture cannot feed a production admission or credit decision."""


class NotNativeCapable(ProviderAdapterError):
    """A ProviderAdapter never provides official proof capability (that is the GPU-079 proof worker)."""
