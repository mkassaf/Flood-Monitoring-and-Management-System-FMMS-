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
    service_name: str = "ingestion-gateway"

    # MQTT broker
    mqtt_host: str = "localhost"
    mqtt_port: int = 1883

    # Kafka
    kafka_bootstrap: str = "localhost:9092"
    kafka_topic: str = "telemetry"
    kafka_linger_ms: int = 10
    kafka_batch_size: int = 65536

    # Postgres (required — no default, service fails fast if unset)
    postgres_dsn: str

    # Sensor cache
    sensor_cache_ttl_s: int = 300


settings = Settings()
