from functools import cached_property
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str  # configMap

    # Redis
    REDIS_URL: str  # configMap
    REDIS_PASSWORD: str  # Bitwarden Secrets

    FRONTEND_URL: str  # configMap

    # Security
    SESSION_SECRET: str  # Bitwarden Secrets
    SERVICE_API_KEY: str  # Bitwarden Secrets

    # CORS
    ALLOWED_ORIGINS: list[str]  # configMap

    # Honeybadger
    HONEYBADGER_API_KEY: str  # Bitwarden Secrets
    LOGFIRE_TOKEN: str | None = None

    # OpenRouter
    OPENROUTER_API_KEY: str  # Bitwarden Secrets
    DEFAULT_CHAT_MODEL: str  # configMap

    # Auth
    AUTH_URL: str  # configMap
    AUTH_SERVICE_ROLE_KEY: str  # Bitwarden Secrets
    AUTH_ADMIN_EMAIL: str | None = None
    AUTH_ADMIN_PASSWORD: str | None = None

    # PostHog
    POSTHOG_API_KEY: str  # Bitwarden Secrets
    POSTHOG_HOST: str  # configMap

    # S3
    S3_ENDPOINT_URL: str  # configMap
    S3_ACCESS_KEY_ID: str  # Bitwarden Secrets
    S3_SECRET_ACCESS_KEY: str
    S3_BUCKET_NAME: str  # configMap
    S3_REGION: str  # configMap

    # ClickHouse
    CLICKHOUSE_HOST: str  # configMap
    CLICKHOUSE_PORT: int  # configMap
    CLICKHOUSE_USER: str  # configMap
    CLICKHOUSE_PASSWORD: str  # Bitwarden Secrets
    CLICKHOUSE_DB: str  # configMap

    # Stripe
    STRIPE_SECRET_KEY: str  # Bitwarden Secrets
    STRIPE_WEBHOOK_SECRET: str  # Bitwarden Secrets
    STRIPE_PRICE_ID_TIER1: str  # configMap
    STRIPE_PRICE_ID_TIER2: str  # configMap

    # Frontend URLs for Stripe redirects
    FRONTEND_SUCCESS_URL: str  # configMap
    FRONTEND_CANCEL_URL: str  # configMap

    @cached_property
    def ALEMBIC_DATABASE_URL(self) -> str:
        if self.DATABASE_URL.startswith("postgresql+asyncpg://"):
            return self.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://", 1)
        return self.DATABASE_URL

    @field_validator("SERVICE_API_KEY")
    @classmethod
    def validate_service_api_key(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("SERVICE_API_KEY must be at least 32 characters")
        return v

    class Config:
        env_file = Path(__file__).resolve().parents[2] / ".env.dev"


settings = Settings()  # type: ignore
