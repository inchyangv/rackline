"""
Configuration for HashCredit API.
"""

from functools import lru_cache
from typing import Optional

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
    # WARNING: If using host="0.0.0.0" (externally accessible), you MUST:
    # 1. Set API_TOKEN to a secure random value
    # 2. Use a firewall or reverse proxy with access control
    host: str = Field(
        default="127.0.0.1",
        description="API host (127.0.0.1 for local only, 0.0.0.0 for external - REQUIRES API_TOKEN)"
    )
    port: int = Field(default=8000, description="API port")
    debug: bool = Field(default=False, description="Enable debug mode")

    # Authentication
    # SECURITY: When API_TOKEN is set, ALL requests require the token via X-API-Key header.
    # There is no local bypass - this prevents proxy bypass attacks.
    api_token: Optional[str] = Field(
        default=None,
        description="API token for authentication (REQUIRED for non-local/production use)"
    )
    allowed_origins: list[str] = Field(
        default=["http://localhost:3000", "http://127.0.0.1:3000"],
        description="CORS allowed origins"
    )

    # Bitcoin RPC
    bitcoin_rpc_url: str = Field(
        default="http://localhost:18332",
        description="Bitcoin Core RPC URL"
    )
    bitcoin_rpc_user: str = Field(default="", description="Bitcoin RPC username")
    bitcoin_rpc_password: str = Field(default="", description="Bitcoin RPC password")

    # EVM
    evm_rpc_url: str = Field(
        default="http://localhost:8545",
        description="EVM RPC URL (Creditcoin testnet)"
    )
    chain_id: int = Field(default=102031, description="EVM chain ID")
    private_key: Optional[str] = Field(
        default=None,
        description="Private key for signing transactions"
    )

    # Contracts
    hash_credit_manager: Optional[str] = Field(
        default=None,
        description="HashCreditManager contract address"
    )
    checkpoint_manager: Optional[str] = Field(
        default=None,
        description="CheckpointManager contract address"
    )
    btc_spv_verifier: Optional[str] = Field(
        default=None,
        description="BtcSpvVerifier contract address"
    )


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
