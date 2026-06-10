from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    r2_bucket: str = Field(default="", alias="R2_BUCKET")
    r2_region: str = Field(default="auto", alias="R2_REGION")
    r2_endpoint_url: str = Field(default="", alias="R2_ENDPOINT_URL")
    r2_use_path_style: bool = Field(default=True, alias="R2_USE_PATH_STYLE")
    r2_public_url_base: str = Field(default="", alias="R2_PUBLIC_URL_BASE")
    r2_access_key_id: str = Field(default="", alias="R2_ACCESS_KEY_ID")
    r2_secret_access_key: str = Field(default="", alias="R2_SECRET_ACCESS_KEY")
    clickhouse_host: str = Field(default="localhost", alias="CLICKHOUSE_HOST")
    clickhouse_port: int = Field(default=8123, alias="CLICKHOUSE_PORT")
    clickhouse_user: str = Field(default="default", alias="CLICKHOUSE_USER")
    clickhouse_password: str = Field(default="", alias="CLICKHOUSE_PASSWORD")
    clickhouse_database: str = Field(default="default", alias="CLICKHOUSE_DATABASE")
    clickhouse_secure: bool = Field(default=False, alias="CLICKHOUSE_SECURE")
    platform_postgres_url: str = Field(default="", alias="PLATFORM_POSTGRES_URL")
    news_feed_urls: str = Field(default="", alias="NEWS_FEED_URLS")
    news_thumbnail_prefix: str = Field(
        default="media/news/thumbnails",
        alias="NEWS_THUMBNAIL_PREFIX",
    )


settings = Settings()
