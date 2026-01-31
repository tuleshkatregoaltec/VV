from pydantic_settings import BaseSettings
from pydantic import field_validator


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

    # OpenRouter
    OPENROUTER_API_KEY: str  # Bitwarden Secrets
    DEFAULT_CHAT_MODEL: str  # configMap

    # Auth
    AUTH_ADMIN_EMAIL: str  # configMap
    AUTH_ADMIN_PASSWORD: str  # Bitwarden Secrets
    AUTH_URL: str  # configMap

    # System Admin (full platform access)
    SYSTEM_ADMIN_EMAIL: str  # configMap - email of system administrator

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

    @field_validator("SERVICE_API_KEY")
    @classmethod
    def validate_service_api_key(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("SERVICE_API_KEY must be at least 32 characters")
        return v

    class Config:
        env_file = ".env"


settings = Settings()  # type: ignore
