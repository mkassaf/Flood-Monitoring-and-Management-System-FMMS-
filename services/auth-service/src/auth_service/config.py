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
    service_name: str = "auth-service"

    # Postgres connection string — required, no default
    POSTGRES_DSN: str

    # Paths to RSA PEM key files — required, no defaults
    JWT_PRIVATE_KEY_PATH: str
    JWT_PUBLIC_KEY_PATH: str

    # Token time-to-live in seconds
    JWT_ACCESS_TTL_S: int = 3600
    JWT_REFRESH_TTL_S: int = 86400


settings = Settings()
