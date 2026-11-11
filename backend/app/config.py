import os
import warnings
from functools import cached_property
from pathlib import Path
from typing import Annotated, Any, Literal

from cryptography.fernet import Fernet
from dotenv import dotenv_values
from pydantic import (
    AnyUrl,
    BeforeValidator,
    EmailStr,
    PostgresDsn,
    computed_field,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing_extensions import Self


def parse_cors(v: Any) -> list[str] | str:
    if isinstance(v, str) and not v.startswith("["):
        return [origin.strip() for origin in v.split(",") if origin.strip()]
    if isinstance(v, list | str):
        return v
    raise ValueError(v)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env.dev", "../.env.dev"),
        env_ignore_empty=True,
        extra="ignore",
    )

    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "Vitevue API"
    ENVIRONMENT: Literal["local", "staging", "production"] = "local"

    # Database
    POSTGRES_URL: PostgresDsn

    # Redis
    REDIS_URL: str  # configMap
    REDIS_PASSWORD: str  # Bitwarden Secrets

    FRONTEND_URL: AnyUrl  # configMap
    PUBLIC_API_BASE_URL: AnyUrl | None = None

    # Google Calendar OAuth. Leave unset to keep the integration disabled.
    GOOGLE_CALENDAR_CLIENT_ID: str | None = None
    GOOGLE_CALENDAR_CLIENT_SECRET: str | None = None
    GOOGLE_CALENDAR_REDIRECT_URI: AnyUrl | None = None
    GOOGLE_CALENDAR_TOKEN_ENCRYPTION_KEY: str | None = None

    # Security
    SESSION_SECRET: str  # Bitwarden Secrets
    SERVICE_API_KEY: str  # Bitwarden Secrets

    # CORS
    ALLOWED_ORIGINS: Annotated[list[AnyUrl] | str, BeforeValidator(parse_cors)] = []

    # Honeybadger
    HONEYBADGER_API_KEY: str | None = None
    LOGFIRE_TOKEN: str | None = None

    # Content-free AI telemetry is explicitly opt-in.
    AI_TELEMETRY_ENABLED: bool = False
    LANGSMITH_API_KEY: str | None = None
    LANGSMITH_ENDPOINT: str = "https://api.smith.langchain.com"
    LANGSMITH_WORKSPACE_ID: str | None = None

    # OpenRouter
    OPENROUTER_API_KEY: str  # Bitwarden Secrets
    DEFAULT_CHAT_MODEL: str  # configMap
    # CRM Assistant only: with an OpenAI key it calls OpenAI directly; otherwise it uses OpenRouter.
    ASSISTANT_OPENAI_API_KEY: str | None = None
    ASSISTANT_MODEL: str | None = None
    # CRM Assistant voice: an OpenRouter model that accepts audio; unset uses DEFAULT_CHAT_MODEL.
    ASSISTANT_VOICE_MODEL: str | None = None

    # Auth
    AUTH_URL: AnyUrl  # configMap
    AUTH_SERVICE_ROLE_KEY: str  # Bitwarden Secrets
    FIRST_SUPERUSER: EmailStr | None = None
    FIRST_SUPERUSER_PASSWORD: str | None = None
    FIRST_SUPERUSER_RENAME_FROM: EmailStr | None = None
    FIRST_SUPERUSER_FIRST_NAME: str = "Admin"
    FIRST_SUPERUSER_LAST_NAME: str = "User"
    FIRST_SUPERUSER_AVATAR_URL: str | None = None

    # Brevo (CRM › Connectors › Email). One Vitevue account; names match the CVBuilder pipeline.
    BREVO_API_KEY: str | None = None
    BREVO_SENDER_EMAIL: str | None = None  # must be a verified sender in Brevo
    BREVO_SENDER_NAME: str | None = None
    BREVO_REPLY_TO: str | None = None
    BREVO_WEBHOOK_SECRET: str | None = None  # POST /api/v1/crm/email/brevo-webhook?secret=...
    # Inbound parsing: mail to this subdomain (MX → Brevo) is posted to /email/brevo-inbound.
    BREVO_INBOUND_DOMAIN: str | None = None
    # Phase 1 has one company: an email from an unknown sender becomes its lead.
    BREVO_INBOUND_ORGANIZATION_ID: str | None = None
    # Connectors › Email keeps sends, templates and received emails in this JSON file (no tables).
    CRM_EMAIL_STORE_PATH: str | None = None

    # Meta WhatsApp Cloud API (CRM › Connectors › WhatsApp). Leave unset to keep it disabled.
    WHATSAPP_ACCESS_TOKEN: str | None = None  # system user token, Bitwarden Secrets
    WHATSAPP_APP_SECRET: str | None = None  # checks X-Hub-Signature-256 on webhooks, Bitwarden
    WHATSAPP_WEBHOOK_VERIFY_TOKEN: str | None = None  # our own random string, Bitwarden Secrets
    WHATSAPP_WABA_ID: str | None = None  # WhatsApp Business Account ID, configMap
    WHATSAPP_GRAPH_API_VERSION: str | None = None  # e.g. "v23.0": a version Meta supports

    # PostHog
    POSTHOG_API_KEY: str | None = None
    POSTHOG_HOST: AnyUrl | None = None

    # Object storage. Production currently uses Cloudflare R2 through the S3-compatible API.
    OBJECT_STORAGE_PROVIDER: Literal["r2", "aws_s3", "minio"] = "r2"  # configMap
    OBJECT_STORAGE_ENDPOINT_URL: AnyUrl | None = None  # configMap
    # Unset in production containers that authenticate with their task role.
    OBJECT_STORAGE_ACCESS_KEY_ID: str | None = None  # Bitwarden Secrets
    OBJECT_STORAGE_SECRET_ACCESS_KEY: str | None = None  # Bitwarden Secrets
    OBJECT_STORAGE_BUCKET: str  # configMap
    OBJECT_STORAGE_REGION: str = "auto"  # configMap
    OBJECT_STORAGE_USE_PATH_STYLE: bool = True  # configMap

    # ClickHouse
    CLICKHOUSE_HOST: str  # configMap
    CLICKHOUSE_PORT: int  # configMap
    CLICKHOUSE_USER: str  # configMap
    CLICKHOUSE_PASSWORD: str  # Bitwarden Secrets
    CLICKHOUSE_DATABASE: str  # configMap
    CLICKHOUSE_SECURE: bool = False  # configMap

    # Stripe
    STRIPE_SECRET_KEY: str  # Bitwarden Secrets
    STRIPE_WEBHOOK_SECRET: str  # Bitwarden Secrets
    STRIPE_PRICE_ID_TIER1: str  # configMap
    STRIPE_PRICE_ID_TIER2: str  # configMap

    # Frontend URLs for Stripe redirects
    FRONTEND_SUCCESS_URL: AnyUrl  # configMap
    FRONTEND_CANCEL_URL: AnyUrl  # configMap

    @cached_property
    def ALEMBIC_DATABASE_URL(self) -> str:
        database_url = str(self.POSTGRES_URL)
        if database_url.startswith("postgresql+asyncpg://"):
            return database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
        return database_url

    @computed_field  # type: ignore[prop-decorator]
    @property
    def all_cors_origins(self) -> list[str]:
        origins = [str(origin).rstrip("/") for origin in self.ALLOWED_ORIGINS]
        frontend_url = str(self.FRONTEND_URL).rstrip("/")
        if frontend_url not in origins:
            origins.append(frontend_url)
        return origins

    @computed_field  # type: ignore[prop-decorator]
    @property
    def honeybadger_enabled(self) -> bool:
        return bool(self.HONEYBADGER_API_KEY)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def logfire_enabled(self) -> bool:
        return bool(self.LOGFIRE_TOKEN)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def posthog_enabled(self) -> bool:
        return bool(self.POSTHOG_API_KEY and self.POSTHOG_HOST)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def bootstrap_superuser_enabled(self) -> bool:
        return bool(self.FIRST_SUPERUSER and self.FIRST_SUPERUSER_PASSWORD)

    @field_validator("SERVICE_API_KEY")
    @classmethod
    def validate_service_api_key(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("SERVICE_API_KEY must be at least 32 characters")
        return v

    @field_validator("SESSION_SECRET")
    @classmethod
    def validate_session_secret(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("SESSION_SECRET must be at least 32 characters")
        return v

    @field_validator("GOOGLE_CALENDAR_TOKEN_ENCRYPTION_KEY")
    @classmethod
    def validate_google_calendar_encryption_key(cls, v: str | None) -> str | None:
        if v:
            Fernet(v.encode())
        return v

    @model_validator(mode="after")
    def validate_superuser_bootstrap(self) -> Self:
        if bool(self.FIRST_SUPERUSER) != bool(self.FIRST_SUPERUSER_PASSWORD):
            raise ValueError(
                "FIRST_SUPERUSER and FIRST_SUPERUSER_PASSWORD must both be set together"
            )
        return self

    @model_validator(mode="after")
    def validate_object_storage_endpoint(self) -> Self:
        if (
            self.OBJECT_STORAGE_PROVIDER in {"r2", "minio"}
            and self.OBJECT_STORAGE_ENDPOINT_URL is None
        ):
            raise ValueError(
                "OBJECT_STORAGE_ENDPOINT_URL must be set when OBJECT_STORAGE_PROVIDER is r2 or minio"
            )
        return self

    def _check_default_secret(self, var_name: str, value: str | None) -> None:
        default_values = {
            "SESSION_SECRET": "dev_session_secret_at_least_32_chars_long_12345",
            "SERVICE_API_KEY": "dev_service_api_key_at_least_32_chars_long_12345",
            "FIRST_SUPERUSER_PASSWORD": "admin123",
        }
        if value != default_values.get(var_name):
            return

        message = (
            f"{var_name} is using a local development default. "
            "Change it for staging and production."
        )
        if self.ENVIRONMENT == "local":
            warnings.warn(message, stacklevel=1)
            return
        raise ValueError(message)

    @model_validator(mode="after")
    def enforce_non_default_secrets(self) -> Self:
        self._check_default_secret("SESSION_SECRET", self.SESSION_SECRET)
        self._check_default_secret("SERVICE_API_KEY", self.SERVICE_API_KEY)
        self._check_default_secret("FIRST_SUPERUSER_PASSWORD", self.FIRST_SUPERUSER_PASSWORD)
        return self


settings = Settings()  # type: ignore


# Legacy news storage resolution: name priority, then process/cwd/parent precedence.
def env_value(*names: str) -> str | None:
    env_files = [
        dotenv_values(path)
        for path in (Path.cwd() / ".env.dev", Path.cwd().parent / ".env.dev")
        if path.exists()
    ]

    for name in names:
        value = os.environ.get(name)
        if value:
            return value
        for values in env_files:
            value = values.get(name)
            if value:
                return value
    return None


def require_env(*names: str) -> str:
    value = env_value(*names)
    if value:
        return value
    raise RuntimeError(f"Missing required environment variable: {' or '.join(names)}")


def build_object_storage_client_kwargs() -> dict[str, str]:
    kwargs = {"region_name": env_value("OBJECT_STORAGE_REGION") or "auto"}
    access_key_id = env_value("OBJECT_STORAGE_ACCESS_KEY_ID")
    secret_access_key = env_value("OBJECT_STORAGE_SECRET_ACCESS_KEY")
    # Without static keys the SDK's default chain applies (e.g. a container task role).
    if access_key_id and secret_access_key:
        kwargs["aws_access_key_id"] = access_key_id
        kwargs["aws_secret_access_key"] = secret_access_key
    endpoint_url = env_value("OBJECT_STORAGE_ENDPOINT_URL")
    if endpoint_url:
        kwargs["endpoint_url"] = endpoint_url
    return kwargs
