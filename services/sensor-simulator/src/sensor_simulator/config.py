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
    service_name: str = "sensor-simulator"

    # MQTT broker
    mqtt_host: str = "localhost"
    mqtt_port: int = 1883

    # Simulation parameters
    sim_sensor_count: int = 1000
    sim_area_count: int = 20
    sim_nominal_interval_s: float = 60.0
    sim_critical_interval_s: float = 5.0
    sim_fault_probability: float = 0.005
    sim_delta_filter_pct: float = 0.02  # suppress retransmit if change < 2% of range

    # Metrics HTTP server
    metrics_port: int = 8000


settings = Settings()
