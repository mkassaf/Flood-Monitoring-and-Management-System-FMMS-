"""Pydantic v2 models for telemetry-service.

Mirrors the ingestion-gateway KafkaMessage wire format and provides the REST
API response model used by dashboard-bff.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class Measurements(BaseModel):
    """Sensor readings — at least one field is present (validated by producer)."""

    water_level_m: Optional[float] = Field(None, ge=0, le=50)
    river_flow_velocity_m_s: Optional[float] = Field(None, ge=0, le=20)
    rainfall_mm_h: Optional[float] = Field(None, ge=0, le=500)
    soil_saturation_pct: Optional[float] = Field(None, ge=0, le=100)
    wind_speed_m_s: Optional[float] = Field(None, ge=0, le=100)
    wind_direction_deg: Optional[float] = Field(None, ge=0, lt=360)


class TelemetryMessage(BaseModel):
    """Enriched envelope consumed from the 'telemetry' Kafka topic.

    Produced by ingestion-gateway (KafkaMessage).  We accept Literal types for
    schema_version / status / mode so that malformed messages are rejected at
    parse time rather than silently persisted.
    """

    schema_version: Literal["1.0.0"]
    sensor_id: str  # UUID string
    area_id: str  # UUID string
    ts: str  # ISO 8601 UTC sensor-side timestamp
    status: Literal[0, 1]
    mode: Literal["nominal", "critical"]
    measurements: Measurements
    ingested_at: str  # ISO 8601 UTC, stamped by ingestion-gateway


# ─── REST API response model ───────────────────────────────────────────────────


class TelemetryPoint(BaseModel):
    """One row from tsdb.telemetry, returned by the historical query API."""

    ts: datetime
    sensor_id: str
    area_id: str
    status: int
    mode: str
    water_level_m: Optional[float] = None
    river_flow_velocity_m_s: Optional[float] = None
    rainfall_mm_h: Optional[float] = None
    soil_saturation_pct: Optional[float] = None
    wind_speed_m_s: Optional[float] = None
    wind_direction_deg: Optional[float] = None
    ingested_at: datetime
