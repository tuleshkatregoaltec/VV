from pydantic_settings import BaseSettings
from pydantic import field_validator


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str

    # Redis
    REDIS_URL: str
    REDIS_PASSWORD: str

    # WorkOS
    WORKOS_API_KEY: str
    WORKOS_CLIENT_ID: str
    WORKOS_REDIRECT_URI: str
    FRONTEND_URL: str

    # Security
    SESSION_SECRET: str
    SERVICE_API_KEY: str

    # CORS
    ALLOWED_ORIGINS: list[str]

    # Honeybadger
    HONEYBADGER_API_KEY: str

    # OpenRouter
    OPENROUTER_API_KEY: str
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    CHAT_MODEL: str = "anthropic/claude-3-haiku"

    # Auth
    AUTH_ADMIN_EMAIL: str
    AUTH_ADMIN_PASSWORD: str
    AUTH_URL: str

    # PostHog
    POSTHOG_API_KEY: str
    POSTHOG_HOST: str

    # Cloudflare R2 / S3
    R2_ENDPOINT_URL: str
    R2_ACCESS_KEY_ID: str
    R2_SECRET_ACCESS_KEY: str
    R2_BUCKET_NAME: str
    R2_REGION: str = "auto"

    # Stripe
    STRIPE_SECRET_KEY: str
    STRIPE_PUBLISHABLE_KEY: str
    STRIPE_WEBHOOK_SECRET: str
    STRIPE_PRICE_ID_TIER1: str  # 990 AED/seat for 1-5 seats
    STRIPE_PRICE_ID_TIER2: str  # 890 AED/seat for 6-10 seats

    # Frontend URLs for Stripe redirects
    FRONTEND_SUCCESS_URL: str
    FRONTEND_CANCEL_URL: str

    # Enterprise contact
    ENTERPRISE_CONTACT_EMAIL: str = "contact@vitevue.com"

    @field_validator("SERVICE_API_KEY")
    @classmethod
    def validate_service_api_key(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("SERVICE_API_KEY must be at least 32 characters")
        return v

    class Config:
        env_file = ".env"


settings = Settings()  # type: ignore
