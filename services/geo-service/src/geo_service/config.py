"""Service configuration (env-driven, fail-fast)."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    log_level: str = "INFO"
    log_format: str = "json"
    service_name: str = "geo-service"

    # Postgres connection string — required, no default
    POSTGRES_DSN: str

    # How long ingestion-gateway may cache sensor→area bindings (seconds)
    GEO_SENSOR_CACHE_TTL_S: int = 300


settings = Settings()
