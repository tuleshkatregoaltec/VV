from pydantic_settings import BaseSettings
from pydantic import field_validator


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str

    # Redis
    REDIS_URL: str

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

    # PostHog
    POSTHOG_API_KEY: str
    POSTHOG_HOST: str = "https://us.i.posthog.com"

    @field_validator("SERVICE_API_KEY")
    @classmethod
    def validate_service_api_key(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("SERVICE_API_KEY must be at least 32 characters")
        return v

    class Config:
        env_file = ".env"


settings = Settings()  # type: ignore
