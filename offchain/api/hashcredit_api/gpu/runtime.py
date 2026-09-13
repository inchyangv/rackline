"""Per-app runtime state for the GPU API: stores, registries, allowlists, secrets (all injectable)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from .auth.challenge import ChallengeStore, InMemoryChallengeStore
from .auth.erc1271 import Erc1271Checker, RejectAllErc1271Checker
from .auth.roles import InMemoryRoleRegistry, RoleRegistry
from .permissions.ownership import InMemoryOwnership, OwnershipResolver
from .proofs.manifests import ManifestSummary, load_manifests
from .secrets import EnvSecretStore, Redactor, SecretStore, install_record_redaction

REPO_MANIFEST_DIR = Path(__file__).resolve().parents[4] / "config" / "attestcoin"


@dataclass
class RateLimiter:
    """Fixed-window in-memory limiter keyed by client ip / principal."""

    limit_per_minute: int
    _hits: dict[tuple[str, int], int] = field(default_factory=dict)

    def allow(self, key: str, now: float) -> bool:
        window = int(now // 60)
        k = (key, window)
        n = self._hits.get(k, 0) + 1
        self._hits[k] = n
        if len(self._hits) > 50_000:
            self._hits = {kk: v for kk, v in self._hits.items() if kk[1] >= window}
        return n <= self.limit_per_minute


@dataclass
class GpuRuntime:
    api_profile: str
    chain_id: int
    app_domain: str
    session_secret: str | None
    session_ttl_seconds: int
    challenge_ttl_seconds: int
    max_body_bytes: int
    challenges: ChallengeStore
    roles: RoleRegistry
    ownership: OwnershipResolver
    erc1271: Erc1271Checker
    secrets: SecretStore
    redactor: Redactor
    manifests: dict[str, ManifestSummary]
    allow_mock_manifests: bool
    provider_allowlist: frozenset[str]
    emitter_allowlist: dict[str, tuple[str, ...]]
    auth_rate_limiter: RateLimiter
    known_borrowers: set[str] = field(default_factory=set)


def build_gpu_runtime(settings, *, manifest_dir: Path | None = None) -> GpuRuntime:
    redactor = Redactor()
    secret_store = EnvSecretStore()
    session_secret = None
    if settings.gpu_session_secret_ref:
        session_secret = secret_store.resolve(settings.gpu_session_secret_ref)
    if settings.gpu_session_secret:  # direct value (tests / local); still redacted
        session_secret = settings.gpu_session_secret
    redactor.register(session_secret)
    install_record_redaction(redactor)
    return GpuRuntime(
        api_profile=settings.api_profile,
        chain_id=settings.chain_id,
        app_domain=settings.gpu_app_domain,
        session_secret=session_secret,
        session_ttl_seconds=settings.gpu_session_ttl_seconds,
        challenge_ttl_seconds=settings.gpu_challenge_ttl_seconds,
        max_body_bytes=settings.gpu_max_body_bytes,
        challenges=InMemoryChallengeStore(),
        roles=InMemoryRoleRegistry(),
        ownership=InMemoryOwnership(),
        erc1271=RejectAllErc1271Checker(),
        secrets=secret_store,
        redactor=redactor,
        manifests=load_manifests(manifest_dir or REPO_MANIFEST_DIR),
        allow_mock_manifests=settings.gpu_allow_mock_manifests,
        provider_allowlist=frozenset(settings.gpu_provider_allowlist),
        emitter_allowlist={k: tuple(v) for k, v in settings.gpu_emitter_allowlist.items()},
        auth_rate_limiter=RateLimiter(settings.gpu_auth_rate_limit_per_minute),
    )
