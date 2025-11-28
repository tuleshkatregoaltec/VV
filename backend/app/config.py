from pydantic_settings import BaseSettings


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

    # CORS
    ALLOWED_ORIGINS: list[str]

    # Honeybadger
    HONEYBADGER_API_KEY: str

    class Config:
        env_file = ".env"


settings = Settings()  # type: ignore
