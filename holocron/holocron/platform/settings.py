from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    s3_bucket: str = Field(default="", alias="S3_BUCKET")
    s3_region: str = Field(default="us-east-1", alias="AWS_REGION")
    s3_endpoint_url: str | None = Field(default=None, alias="S3_ENDPOINT_URL")
    s3_use_path_style: bool = Field(default=False, alias="S3_USE_PATH_STYLE")
    s3_public_url_base: str = Field(default="", alias="S3_PUBLIC_URL_BASE")
    r2_endpoint_url: str | None = Field(default=None, alias="R2_ENDPOINT")
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
