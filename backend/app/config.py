import os
import re
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
    Field,
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


def validate_assistant_model_id(value: str) -> str:
    """Reject prohibited families and implicit model routing for every assistant role."""
    value = value.strip()
    normalized = "".join(character for character in value.lower() if character.isalnum())
    if (
        not re.fullmatch(r"[A-Za-z0-9-]+/[A-Za-z0-9_.:+-]+", value)
        or "gemini" in normalized
        or ("qwen38" in normalized and "max" in normalized)
        or value.lower().startswith("openrouter/")
    ):
        raise ValueError("Assistant roles require an explicit non-Gemini, non-Qwen3.8-Max model")
    return value


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

    # Google Calendar OAuth (CRM › Calendar). Leave unset to keep the integration disabled.
    GOOGLE_CALENDAR_CLIENT_ID: str | None = None
    GOOGLE_CALENDAR_CLIENT_SECRET: str | None = None
    # Google sends the browser back here; it must match the OAuth client in Google Cloud.
    GOOGLE_CALENDAR_REDIRECT_URI: AnyUrl | None = None
    # One Fernet key encrypting stored Google refresh tokens.
    GOOGLE_CALENDAR_TOKEN_ENCRYPTION_KEY: str | None = None

    # Security
    SESSION_SECRET: str  # Bitwarden Secrets
    SERVICE_API_KEY: str  # Bitwarden Secrets

    # CORS
    ALLOWED_ORIGINS: Annotated[list[AnyUrl] | str, BeforeValidator(parse_cors)] = []
    # Optional full-match regex for extra origins, e.g. Cloudflare Pages previews:
    # ^https://[a-z0-9-]+\.vv-pilot\.pages\.dev$
    ALLOWED_ORIGIN_REGEX: str | None = None

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

    # Assistant qualification candidates are isolated from feasibility and imports.
    # Enable only after capped model evaluations and provider/privacy approval.
    ASSISTANT_ENABLED: bool = False
    ASSISTANT_TYPED_ROUTING_ENABLED: bool = False
    ASSISTANT_ROUTER_MODEL: str = "openai/gpt-6-luna"
    ASSISTANT_COORDINATOR_MODEL: str = "openai/gpt-6-luna"
    ASSISTANT_MARKET_MODEL: str = "openai/gpt-6-luna"
    ASSISTANT_PRICING_MODEL: str = "openai/gpt-6-luna"
    ASSISTANT_CRM_MODEL: str = "openai/gpt-6-luna"
    ASSISTANT_FOLLOWUP_MODEL: str = "openai/gpt-6-luna"
    ASSISTANT_ACTION_MODEL: str = "openai/gpt-6-luna"
    ASSISTANT_WHATSAPP_CLASSIFIER_MODEL: str = "openai/gpt-6-luna"
    ASSISTANT_WHATSAPP_DRAFTER_MODEL: str = "openai/gpt-6-luna"
    # Per-turn budget, separate from each user's daily allowance (a turn reserves
    # min(turn limit, remaining allowance)). Sized for openai/gpt-6-luna (1.05M context,
    # $0.10/M input, $0.50/M output): a logged 8-request tool turn used 29,516 tokens,
    # so 160k covers a two-workflow turn of 15-20 requests and costs at most ~$0.04.
    ASSISTANT_TURN_TOKEN_LIMIT: int = Field(default=160_000, ge=8_000)
    ASSISTANT_TURN_MIN_TOKENS: int = Field(default=16_000, ge=1_000)
    ASSISTANT_TURN_REQUEST_LIMIT: int = Field(default=20, ge=1)
    ASSISTANT_TURN_TOOL_CALLS_LIMIT: int = Field(default=24, ge=1)
    # Prior-turn text replayed to the model, and the point at which older tool
    # outputs inside a turn are compacted before the next request.
    ASSISTANT_HISTORY_TOKEN_LIMIT: int = Field(default=8_000, ge=500)
    ASSISTANT_REQUEST_CONTEXT_TOKEN_LIMIT: int = Field(default=32_000, ge=4_000)
    # Feasibility LLM runs (DEFAULT_CHAT_MODEL) share the same daily allowance.
    FEASIBILITY_RUN_TOKEN_LIMIT: int = Field(default=300_000, ge=8_000)
    FEASIBILITY_HBU_CACHE_SECONDS: int = Field(default=86_400, ge=60)

    @field_validator(
        "ASSISTANT_ROUTER_MODEL",
        "ASSISTANT_COORDINATOR_MODEL",
        "ASSISTANT_MARKET_MODEL",
        "ASSISTANT_PRICING_MODEL",
        "ASSISTANT_CRM_MODEL",
        "ASSISTANT_FOLLOWUP_MODEL",
        "ASSISTANT_ACTION_MODEL",
        "ASSISTANT_WHATSAPP_CLASSIFIER_MODEL",
        "ASSISTANT_WHATSAPP_DRAFTER_MODEL",
    )
    @classmethod
    def validate_assistant_models(cls, value: str) -> str:
        return validate_assistant_model_id(value)

    # Auth
    AUTH_URL: AnyUrl  # configMap
    AUTH_SERVICE_ROLE_KEY: str  # Bitwarden Secrets
    # Hosted Supabase requires an `apikey` header on every /auth/v1 call; self-hosted GoTrue ignores it.
    AUTH_PUBLISHABLE_KEY: str | None = None
    FIRST_SUPERUSER: EmailStr | None = None
    FIRST_SUPERUSER_PASSWORD: str | None = None
    FIRST_SUPERUSER_RENAME_FROM: EmailStr | None = None
    FIRST_SUPERUSER_FIRST_NAME: str = "Admin"
    FIRST_SUPERUSER_LAST_NAME: str = "User"
    FIRST_SUPERUSER_AVATAR_URL: str | None = None

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

    # CRM worker-local resource budgets; account for all workers/replicas when sizing.
    CRM_RENTAL_BASE_ENABLED: bool = False
    CRM_INBOUND_OWNER_ENRICHMENT_MODE: Literal["live", "stored", "off"] = "live"
    CRM_MAX_EXPENSIVE_REQUESTS: int = Field(default=2, ge=1, le=32)
    CRM_MAX_EXPENSIVE_REQUESTS_PER_ORG: int = Field(default=2, ge=1, le=16)
    # Requests beyond these budgets queue this long, then get 429 before any work starts.
    CRM_ADMISSION_WAIT_SECONDS: float = Field(default=30.0, gt=0, le=90)
    CRM_MAX_CONCURRENT_QUERIES: int = Field(default=1, ge=1, le=8)
    CRM_QUERY_MAX_MEMORY_BYTES: int = Field(default=3_000_000_000, ge=67_108_864)
    CRM_QUERY_MAX_THREADS: int = Field(default=2, ge=1, le=16)

    # Stripe
    STRIPE_SECRET_KEY: str  # Bitwarden Secrets
    STRIPE_WEBHOOK_SECRET: str  # Bitwarden Secrets
    STRIPE_PRICE_ID_TIER1: str  # configMap
    STRIPE_PRICE_ID_TIER2: str  # configMap

    # Single-number WhatsApp connectivity demo. Credentials stay server-side.
    WHATSAPP_DEMO_ENABLED: bool = False
    WHATSAPP_VERIFY_TOKEN: str | None = Field(default=None, repr=False)
    WHATSAPP_APP_SECRET: str | None = Field(default=None, repr=False)
    WHATSAPP_ACCESS_TOKEN: str | None = Field(default=None, repr=False)
    WHATSAPP_PHONE_NUMBER_ID: str | None = Field(default=None, pattern=r"^\d+$")
    WHATSAPP_TEST_RECIPIENT: str | None = Field(default=None, pattern=r"^\d{7,15}$")
    WHATSAPP_GRAPH_API_VERSION: str | None = Field(default=None, pattern=r"^v\d+\.\d+$")
    WHATSAPP_TEST_TEMPLATE: Literal["hello_world", "jaspers_market_order_confirmation_v1"] = (
        "hello_world"
    )
    WHATSAPP_AUTOMATION_ENABLED: bool = False
    WHATSAPP_PILOT_USER_ID: str | None = None
    WHATSAPP_PILOT_ORGANIZATION_ID: str | None = None
    WHATSAPP_MAX_DAILY_TURNS: int = Field(default=20, ge=1, le=100)
    # Customer channel is separate from the private self-assistant pilot.
    WHATSAPP_CUSTOMER_AUTOMATION_ENABLED: bool = False
    WHATSAPP_CUSTOMER_PHONE_NUMBER_ID: str | None = Field(default=None, pattern=r"^\d+$")
    WHATSAPP_CUSTOMER_ACCOUNT_ID: str | None = Field(default=None, pattern=r"^\d+$")
    WHATSAPP_CUSTOMER_ACCESS_TOKEN: str | None = Field(default=None, repr=False)
    WHATSAPP_CUSTOMER_TEST_RECIPIENT: str | None = Field(default=None, pattern=r"^\d{7,15}$")
    # Multi-agent Embedded Signup. App and configuration IDs are public values the
    # browser SDK needs; the app secret above exchanges codes server-side.
    WHATSAPP_APP_ID: str | None = Field(default=None, pattern=r"^\d+$")
    WHATSAPP_EMBEDDED_SIGNUP_CONFIG_ID: str | None = Field(default=None, pattern=r"^\d+$")
    # Comma-separated Fernet keys; the first encrypts, all decrypt (rotation).
    WHATSAPP_TOKEN_ENCRYPTION_KEY: str | None = Field(default=None, repr=False)
    WHATSAPP_CLASSIFIER_CONCURRENCY: int = Field(default=4, ge=1, le=32)
    # Read receipt, typing indicator and a human-paced delay before automatic replies.
    WHATSAPP_HUMAN_TIMING_ENABLED: bool = True

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

    @field_validator("GOOGLE_CALENDAR_TOKEN_ENCRYPTION_KEY")
    @classmethod
    def validate_google_calendar_encryption_key(cls, v: str | None) -> str | None:
        if v:
            Fernet(v.encode())
        return v

    @field_validator("SESSION_SECRET")
    @classmethod
    def validate_session_secret(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("SESSION_SECRET must be at least 32 characters")
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
