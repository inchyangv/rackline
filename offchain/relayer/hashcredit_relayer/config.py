"""
Configuration management for HashCredit Relayer.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from pydantic import BaseModel
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Environment-based settings."""

    # EVM Network
    rpc_url: str = "https://rpc.cc3-testnet.creditcoin.network"
    chain_id: int = 102031
    private_key: str = ""

    # Contract addresses
    hash_credit_manager: str = ""
    verifier: str = ""

    # Bitcoin API
    bitcoin_api_url: str = "https://mempool.space/api"

    # Relayer settings
    relayer_private_key: str = ""
    poll_interval_seconds: int = 60
    confirmations_required: int = 6

    # Database
    database_url: str = "sqlite:///./relayer.db"

    # Watched addresses (comma-separated)
    watched_addresses: str = ""

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@dataclass
class WatchedBorrower:
    """A borrower being watched for payouts."""

    evm_address: str
    btc_address: str
    btc_script_pubkey_hash: Optional[str] = None


@dataclass
class RelayerConfig:
    """Full relayer configuration."""

    settings: Settings
    watched_borrowers: list[WatchedBorrower] = field(default_factory=list)

    @classmethod
    def from_env(cls, env_path: Optional[Path] = None) -> "RelayerConfig":
        """Load configuration from environment."""
        settings = Settings(_env_file=env_path) if env_path else Settings()
        return cls(settings=settings)

    def add_borrower(self, evm_address: str, btc_address: str) -> None:
        """Add a borrower to watch list."""
        self.watched_borrowers.append(
            WatchedBorrower(evm_address=evm_address, btc_address=btc_address)
        )
