"""Pydantic v2 models for the FMMS telemetry envelope and Kafka message."""

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


class Measurements(BaseModel):
    """Sensor readings — at least one field must be present."""

    water_level_m: Optional[float] = Field(None, ge=0, le=50)
    river_flow_velocity_m_s: Optional[float] = Field(None, ge=0, le=20)
    rainfall_mm_h: Optional[float] = Field(None, ge=0, le=500)
    soil_saturation_pct: Optional[float] = Field(None, ge=0, le=100)
    wind_speed_m_s: Optional[float] = Field(None, ge=0, le=100)
    wind_direction_deg: Optional[float] = Field(None, ge=0, lt=360)

    @model_validator(mode="after")
    def at_least_one_measurement(self) -> "Measurements":
        if all(v is None for v in self.model_dump().values()):
            raise ValueError("at least one measurement field is required")
        return self


class TelemetryEnvelope(BaseModel):
    """Canonical wire format for a sensor reading arriving over MQTT."""

    schema_version: Literal["1.0.0"]
    sensor_id: str  # UUID string — validated by geo-service registration
    area_id: str  # UUID string — used as Kafka partition key
    ts: str  # ISO 8601 UTC timestamp from sensor
    status: Literal[0, 1]
    mode: Literal["nominal", "critical"]
    measurements: Measurements


class KafkaMessage(TelemetryEnvelope):
    """Enriched envelope forwarded to Kafka — adds server-side ingestion timestamp."""

    ingested_at: str  # ISO 8601 UTC, stamped by ingestion-gateway
