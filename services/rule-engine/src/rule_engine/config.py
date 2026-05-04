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
    service_name: str = "rule-engine"

    # Kafka
    kafka_bootstrap: str = "localhost:9092"
    kafka_topic: str = "telemetry"
    kafka_consumer_group: str = "rule-engine"
    alert_kafka_bootstrap: str = "localhost:9092"

    # Redis (required — service fails fast if missing)
    redis_url: str

    # Geo-service
    geo_service_url: str = "http://geo-service:8000"
    threshold_cache_ttl_s: int = 60

    # Watchdog
    sensor_silence_timeout_s: int = 180
    watchdog_interval_s: int = 30


settings = Settings()
