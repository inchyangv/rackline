"""Standalone GPU configuration: deliberately does not load legacy Settings or .env."""

from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ProductSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GPU_", env_file=None, extra="ignore", populate_by_name=True)

    database_url: SecretStr | None = Field(default=None, validation_alias="HASHCREDIT_GPU_DATABASE_URL")
    execution_profile: Literal["LOCAL_MOCK", "NATIVE_TESTNET", "PRODUCTION"] = "PRODUCTION"
    chain_id: int | None = Field(default=None, gt=0)
    deployment_id: str | None = Field(default=None, pattern=r"^[0-9A-HJKMNP-TV-Z]{26}$")
    manifest_hash: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    app_domain: str | None = None
    session_secret: SecretStr | None = None
    max_projection_age_seconds: int = Field(default=120, ge=1, le=86400)
    session_ttl_seconds: int = Field(default=900, ge=60, le=3600)
    challenge_ttl_seconds: int = Field(default=300, ge=30, le=600)
    auth_rate_limit_per_minute: int = Field(default=30, ge=1, le=300)
    max_body_bytes: int = Field(default=16384, ge=1024, le=1048576)
    cors_origins: list[str] = Field(default_factory=list)
    deployment_manifest: str | None = None
    rpc_url: SecretStr | None = None
    abi_directory: str | None = None

    @field_validator("session_secret")
    @classmethod
    def strong_secret(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and len(value.get_secret_value()) < 32:
            raise ValueError("session secret must contain at least 32 characters")
        return value

    @field_validator("database_url")
    @classmethod
    def postgres_only(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and not value.get_secret_value().startswith(("postgresql://", "postgresql+psycopg2://")):
            raise ValueError("a PostgreSQL database is required")
        return value

    @field_validator("cors_origins")
    @classmethod
    def exact_origins(cls, value: list[str]) -> list[str]:
        from urllib.parse import urlsplit
        for origin in value:
            parsed = urlsplit(origin)
            if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment or "*" in origin:
                raise ValueError("CORS origins must be explicit HTTP(S) origins")
        return value

    @model_validator(mode="after")
    def profile_chain(self):
        if self.chain_id is not None:
            if self.execution_profile == "LOCAL_MOCK" and self.chain_id in (102030, 102031, 102032):
                raise ValueError("LOCAL_MOCK cannot use a public Creditcoin chain")
            if self.execution_profile == "NATIVE_TESTNET" and self.chain_id not in (102031, 102032):
                raise ValueError("NATIVE_TESTNET requires a Creditcoin testnet")
            if self.execution_profile == "PRODUCTION" and self.chain_id != 102030:
                raise ValueError("PRODUCTION requires Creditcoin mainnet")
        return self
