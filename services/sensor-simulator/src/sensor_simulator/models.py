"""Pydantic v2 models for the FMMS telemetry envelope (contracts/telemetry-envelope.schema.json)."""

from typing import Literal

from pydantic import BaseModel, Field


class Measurements(BaseModel):
    """Sensor readings. A sensor exposes only the transducers it physically has."""

    water_level_m: float | None = Field(default=None, ge=0.0, le=50.0)
    river_flow_velocity_m_s: float | None = Field(default=None, ge=0.0, le=20.0)
    rainfall_mm_h: float | None = Field(default=None, ge=0.0, le=500.0)
    soil_saturation_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    wind_speed_m_s: float | None = Field(default=None, ge=0.0, le=100.0)
    wind_direction_deg: float | None = Field(default=None, ge=0.0, lt=360.0)


class TelemetryEnvelope(BaseModel):
    """Canonical wire format — must match contracts/telemetry-envelope.schema.json."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    sensor_id: str
    area_id: str
    ts: str  # ISO 8601 UTC
    status: Literal[0, 1]
    mode: Literal["nominal", "critical"]
    measurements: Measurements
