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
    service_name: str = "dashboard-bff"

    # ─── Required infrastructure connections ──────────────────────────────────
    POSTGRES_DSN: str
    REDIS_URL: str

    # ─── Downstream service URLs ───────────────────────────────────────────────
    AUTH_SERVICE_URL: str = "http://auth-service:8000"
    GEO_SERVICE_URL: str = "http://geo-service:8000"

    # ─── JWT / auth ────────────────────────────────────────────────────────────
    JWT_PUBLIC_KEY_PATH: str  # path to RS256 public key PEM file — required
    JWT_ALGORITHM: str = "RS256"

    # ─── Caching ───────────────────────────────────────────────────────────────
    SCOPE_CACHE_TTL_S: int = 300  # seconds to cache resolved area_ids per user

    # ─── WebSocket ─────────────────────────────────────────────────────────────
    WS_HEARTBEAT_INTERVAL_S: int = 30
    WS_MAX_CONNECTIONS_PER_POD: int = 200


settings = Settings()
