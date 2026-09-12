"""
Configuration for HashCredit API.
"""

from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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
        description="EVM RPC URL (HashKey Chain testnet)"
    )
    chain_id: int = Field(default=133, description="EVM chain ID")
    # Admin key (owner of HashCreditManager, used for registerBorrower/grantTestnetCredit)
    admin_private_key: str | None = Field(
        default=None,
        description="Private key for the contract owner (hex, no 0x prefix ok)",
        alias="ADMIN_PRIVATE_KEY",
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


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
