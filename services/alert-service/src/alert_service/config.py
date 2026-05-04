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
    service_name: str = "alert-service"

    # Kafka
    KAFKA_BOOTSTRAP: str = "localhost:9092"
    KAFKA_TOPICS: list[str] = ["alerts.threshold", "alerts.malfunction", "alerts.priority"]
    KAFKA_CONSUMER_GROUP: str = "alert-service"

    # Postgres — required, no default
    POSTGRES_DSN: str

    # Redis — required, no default
    REDIS_URL: str


settings = Settings()
