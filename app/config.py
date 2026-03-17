from __future__ import annotations

from functools import lru_cache
from typing import Any, cast

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_EMBEDDING_DIMENSION = 768


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    app_env: str = Field(default="development", alias="APP_ENV")
    app_host: str = Field(default="0.0.0.0", alias="APP_HOST")
    app_port: int = Field(default=8000, alias="APP_PORT")

    postgres_host: str = Field(alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, alias="POSTGRES_PORT")
    postgres_db: str = Field(alias="POSTGRES_DB")
    postgres_user: str = Field(alias="POSTGRES_USER")
    postgres_password: SecretStr = Field(alias="POSTGRES_PASSWORD")

    anthropic_base_url: str = Field(default="http://localhost:11434", alias="ANTHROPIC_BASE_URL")
    anthropic_auth_token: SecretStr = Field(
        default=SecretStr("ollama"),
        alias="ANTHROPIC_AUTH_TOKEN",
        validation_alias=AliasChoices("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY"),
    )
    anthropic_model_name: str = Field(default="kimi-k2.5:cloud", alias="ANTHROPIC_MODEL_NAME")

    ollama_base_url: str = Field(default="http://localhost:11434", alias="OLLAMA_BASE_URL")
    ollama_embed_model: str = Field(default="embeddinggemma", alias="OLLAMA_EMBED_MODEL")
    embedding_dimension: int = Field(
        default=DEFAULT_EMBEDDING_DIMENSION,
        alias="EMBEDDING_DIMENSION",
    )

    upload_dir: str = Field(default="./data/uploads", alias="UPLOAD_DIR")
    parsed_dir: str = Field(default="./data/parsed", alias="PARSED_DIR")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    langfuse_public_key: SecretStr | None = Field(default=None, alias="LANGFUSE_PUBLIC_KEY")
    langfuse_secret_key: SecretStr | None = Field(default=None, alias="LANGFUSE_SECRET_KEY")
    langfuse_host: str | None = Field(
        default=None,
        alias="LANGFUSE_HOST",
        validation_alias=AliasChoices("LANGFUSE_HOST", "LANGFUSE_BASE_URL"),
    )
    langfuse_tracing_enabled: bool = Field(default=True, alias="LANGFUSE_TRACING_ENABLED")
    langfuse_tracing_environment: str | None = Field(
        default=None,
        alias="LANGFUSE_TRACING_ENVIRONMENT",
    )
    langfuse_release: str | None = Field(default=None, alias="LANGFUSE_RELEASE")
    langfuse_sample_rate: float = Field(default=1.0, alias="LANGFUSE_SAMPLE_RATE")

    @property
    def database_url(self) -> str:
        password = self.postgres_password.get_secret_value()
        return (
            f"postgresql+psycopg://{self.postgres_user}:{password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def migration_database_url(self) -> str:
        password = self.postgres_password.get_secret_value()
        return (
            f"postgresql://{self.postgres_user}:{password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def langfuse_base_url(self) -> str:
        return self.langfuse_host or "https://cloud.langfuse.com"

    @property
    def langfuse_is_configured(self) -> bool:
        return (
            self.langfuse_tracing_enabled
            and self.langfuse_public_key is not None
            and self.langfuse_secret_key is not None
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings_cls = cast(Any, Settings)
    return settings_cls()
