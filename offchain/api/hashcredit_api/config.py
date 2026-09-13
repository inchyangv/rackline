"""
Configuration for HashCredit API.
"""

from functools import lru_cache
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

API_PROFILES = ("production", "testnet_demo")

# Chain ids on which demo admin transactions are never allowed, whatever the allowlist says.
# 102030 = Creditcoin CC3 mainnet, 1 = Ethereum mainnet.
MAINNET_CHAIN_IDS = frozenset({102030, 1})


class Settings(BaseSettings):
    """
    API configuration settings.

    All settings can be overridden via environment variables.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # API Server
    host: str = Field(
        default="127.0.0.1",
        description="API host (127.0.0.1 for local only, 0.0.0.0 for external)",
        alias="HOST",
    )
    # Railway injects PORT env var; we support both PORT and API_PORT
    port: int = Field(
        default=8000,
        description="API port (Railway sets PORT automatically)",
        validation_alias="PORT",
    )
    debug: bool = Field(default=False, description="Enable debug mode")

    allowed_origins: list[str] = Field(
        default=["http://localhost:3000", "http://127.0.0.1:3000"],
        description="CORS allowed origins"
    )

    # Borrower mapping mode
    # - demo: operator sets mappings directly (testnet/demo)
    # - claim: borrower must prove control (mainnet-grade)
    borrower_mapping_mode: str = Field(
        default="demo",
        description="Borrower mapping mode: demo or claim",
        alias="BORROWER_MAPPING_MODE",
    )

    # Claim flow (mainnet-grade mapping)
    claim_secret: str | None = Field(
        default=None,
        description="HMAC secret used to sign claim tokens (required for claim mode)",
        alias="CLAIM_SECRET",
    )
    claim_ttl_seconds: int = Field(
        default=900,
        description="Claim token TTL in seconds",
        alias="CLAIM_TTL_SECONDS",
    )
    # Bitcoin RPC
    bitcoin_rpc_url: str = Field(
        default="http://localhost:18332",
        description="Bitcoin Core RPC URL"
    )
    bitcoin_rpc_user: str = Field(default="", description="Bitcoin RPC username")
    bitcoin_rpc_password: str = Field(default="", description="Bitcoin RPC password")
    btc_indexer_base_url: str = Field(
        default="https://blockstream.info/testnet/api",
        description="External Bitcoin indexer base URL (Esplora-compatible)"
    )
    btc_indexer_timeout_seconds: float = Field(
        default=20.0,
        description="Timeout for external Bitcoin indexer requests"
    )

    # EVM
    evm_rpc_url: str = Field(
        default="http://localhost:8545",
        description="EVM RPC URL (Creditcoin testnet)"
    )
    chain_id: int = Field(default=102031, description="EVM chain ID")

    # Execution profile (GPU-001). The production API never holds an owner/admin key and does not
    # expose the register-and-grant route. The testnet demo path is a separate profile with its own
    # key name, a chain allowlist, a TEST_ONLY stablecoin allowlist, and a grant cap.
    api_profile: str = Field(
        default="production",
        description="production | testnet_demo",
        alias="API_PROFILE",
    )
    # Legacy variable: rejected in every profile so an owner key can never be loaded by mistake.
    admin_private_key: str | None = Field(
        default=None,
        description="DEPRECATED - must be unset. Use DEMO_ADMIN_PRIVATE_KEY only with API_PROFILE=testnet_demo",
        alias="ADMIN_PRIVATE_KEY",
    )
    demo_admin_private_key: str | None = Field(
        default=None,
        description="Demo-only signer for registerBorrower/grantTestnetCredit (testnet_demo profile)",
        alias="DEMO_ADMIN_PRIVATE_KEY",
    )
    demo_allowed_chain_ids: list[int] = Field(
        default=[102031, 31337],
        description="Chain ids on which the demo admin path may send transactions (JSON list)",
        alias="DEMO_ALLOWED_CHAIN_IDS",
    )
    demo_allowed_stablecoins: list[str] = Field(
        default=[],
        description="TEST_ONLY stablecoin addresses the manager must use for demo grants (JSON list)",
        alias="DEMO_ALLOWED_STABLECOINS",
    )
    demo_grant_cap: int = Field(
        default=1_000_000_000,
        description="Maximum demo credit grant in stablecoin base units (1000e6 = 1,000 mUSDT)",
        alias="DEMO_GRANT_CAP",
    )
    demo_auth_ttl_seconds: int = Field(
        default=300,
        description="Validity window of the borrower's demo authorization signature",
        alias="DEMO_AUTH_TTL_SECONDS",
    )

    # GPU API (GPU-018). Bearer sessions only; the secret comes from a secret ref or a direct value that is
    # never logged. Proof queries are restricted to repo manifests and explicit provider/emitter allowlists.
    gpu_session_secret_ref: str | None = Field(
        default=None,
        description="Secret ref for the session HMAC key, e.g. env://GPU_SESSION_SECRET_VALUE",
        alias="GPU_SESSION_SECRET_REF",
    )
    gpu_session_secret: str | None = Field(
        default=None,
        description="Direct session HMAC secret (local/tests); prefer GPU_SESSION_SECRET_REF",
        alias="GPU_SESSION_SECRET",
    )
    gpu_session_ttl_seconds: int = Field(default=900, alias="GPU_SESSION_TTL_SECONDS")
    gpu_challenge_ttl_seconds: int = Field(default=300, alias="GPU_CHALLENGE_TTL_SECONDS")
    gpu_app_domain: str = Field(default="app.rackline.local", alias="GPU_APP_DOMAIN")
    gpu_auth_rate_limit_per_minute: int = Field(default=30, alias="GPU_AUTH_RATE_LIMIT_PER_MINUTE")
    gpu_max_body_bytes: int = Field(default=65_536, alias="GPU_MAX_BODY_BYTES")
    gpu_provider_allowlist: list[str] = Field(default=[], alias="GPU_PROVIDER_ALLOWLIST")
    gpu_allow_mock_manifests: bool = Field(
        default=False,
        description="Allow LOCAL_MOCK manifests in proof-query plans (never honoured on production)",
        alias="GPU_ALLOW_MOCK_MANIFESTS",
    )
    gpu_emitter_allowlist: dict[str, list[str]] = Field(
        default={},
        description="manifestId -> registered emitter addresses (JSON object)",
        alias="GPU_EMITTER_ALLOWLIST",
    )

    # Contracts (for UI hints/health metadata)
    hash_credit_manager: str | None = Field(
        default=None,
        description="HashCreditManager contract address"
    )
    checkpoint_manager: str | None = Field(
        default=None,
        description="CheckpointManager contract address"
    )
    btc_spv_verifier: str | None = Field(
        default=None,
        description="BtcSpvVerifier contract address"
    )

    @property
    def is_demo(self) -> bool:
        return self.api_profile == "testnet_demo"

    @model_validator(mode="after")
    def _enforce_profile(self) -> "Settings":
        if self.api_profile not in API_PROFILES:
            raise ValueError(f"API_PROFILE must be one of {API_PROFILES}, got {self.api_profile!r}")
        if self.admin_private_key:
            raise ValueError(
                "ADMIN_PRIVATE_KEY is no longer accepted by the API. Unset it. "
                "Demo deployments use DEMO_ADMIN_PRIVATE_KEY with API_PROFILE=testnet_demo."
            )
        if self.gpu_session_ttl_seconds <= 0 or self.gpu_challenge_ttl_seconds <= 0:
            raise ValueError("GPU session/challenge TTLs must be positive")
        if self.api_profile == "production":
            if self.demo_admin_private_key:
                raise ValueError("DEMO_ADMIN_PRIVATE_KEY must not be set on a production API process")
            if any(o.strip() == "*" for o in self.allowed_origins):
                raise ValueError("allowed_origins must not contain '*' on a production API process")
            if self.gpu_allow_mock_manifests:
                raise ValueError("GPU_ALLOW_MOCK_MANIFESTS must be false on a production API process")
            return self
        # testnet_demo
        blocked = MAINNET_CHAIN_IDS.intersection(self.demo_allowed_chain_ids)
        if blocked:
            raise ValueError(f"DEMO_ALLOWED_CHAIN_IDS contains mainnet chain ids {sorted(blocked)}")
        if self.chain_id in MAINNET_CHAIN_IDS:
            raise ValueError(f"CHAIN_ID {self.chain_id} is a mainnet; testnet_demo refuses to start")
        if self.chain_id not in self.demo_allowed_chain_ids:
            raise ValueError(
                f"CHAIN_ID {self.chain_id} is not in DEMO_ALLOWED_CHAIN_IDS {self.demo_allowed_chain_ids}"
            )
        if self.demo_grant_cap <= 0:
            raise ValueError("DEMO_GRANT_CAP must be positive")
        return self


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
