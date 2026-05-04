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
    service_name: str = "telemetry-service"

    # Kafka
    KAFKA_BOOTSTRAP: str = "localhost:9092"
    KAFKA_TOPIC: str = "telemetry"
    KAFKA_CONSUMER_GROUP: str = "telemetry-service"
    KAFKA_AUTO_OFFSET_RESET: str = "latest"

    # Postgres — required, no default
    POSTGRES_DSN: str

    # Redis — required, no default
    REDIS_URL: str

    # Batching (NFR-07)
    BATCH_INTERVAL_S: float = 1.0
    BATCH_MAX_SIZE: int = 1000

    # Redis TTL for hot state: 2× nominal 60 s emission interval
    REDIS_HOT_STATE_TTL_S: int = 120


settings = Settings()
