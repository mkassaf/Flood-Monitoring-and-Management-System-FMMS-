"""Pydantic v2 models for rule-engine.

Mirrors the telemetry-service TelemetryMessage wire format and provides the
Alert model matching contracts/alert.schema.json.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field


# ─── Telemetry (input) ────────────────────────────────────────────────────────


class Measurements(BaseModel):
    """Sensor readings — at least one field is present (validated by producer)."""

    water_level_m: Optional[float] = Field(None, ge=0, le=50)
    river_flow_velocity_m_s: Optional[float] = Field(None, ge=0, le=20)
    rainfall_mm_h: Optional[float] = Field(None, ge=0, le=500)
    soil_saturation_pct: Optional[float] = Field(None, ge=0, le=100)
    wind_speed_m_s: Optional[float] = Field(None, ge=0, le=100)
    wind_direction_deg: Optional[float] = Field(None, ge=0, lt=360)

    def as_param_dict(self) -> dict[str, float]:
        """Return {parameter_name: value} for all non-None measurements."""
        return {
            k: v
            for k, v in self.model_dump().items()
            if v is not None
        }


class TelemetryMessage(BaseModel):
    """Enriched envelope consumed from the 'telemetry' Kafka topic.

    Produced by ingestion-gateway. We accept Literal types for schema_version /
    status / mode so that malformed messages are rejected at parse time rather
    than silently processed.
    """

    schema_version: Literal["1.0.0"]
    sensor_id: str  # UUID string
    area_id: str  # UUID string
    ts: str  # ISO 8601 UTC sensor-side timestamp
    status: Literal[0, 1]
    mode: Literal["nominal", "critical"]
    measurements: Measurements
    ingested_at: str  # ISO 8601 UTC, stamped by ingestion-gateway


# ─── Thresholds (from geo-service) ────────────────────────────────────────────


class AreaThreshold(BaseModel):
    """Per-parameter flood threshold configured for a geographic area."""

    area_id: str
    parameter: str
    warning_lo: Optional[float] = None
    warning_hi: Optional[float] = None
    critical_lo: Optional[float] = None
    critical_hi: Optional[float] = None


# ─── Alerts (output) ──────────────────────────────────────────────────────────


class AlertContext(BaseModel):
    """Kind-specific context fields — only relevant fields are set."""

    redundancy_remaining: Optional[int] = Field(None, ge=0)
    trend: Optional[Literal["rising", "falling", "stable"]] = None
    originating_alert_id: Optional[str] = None  # UUID string

    model_config = {"extra": "allow"}


class Alert(BaseModel):
    """Canonical alert produced by the rule engine — matches alert.schema.json."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    alert_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    kind: Literal["threshold", "malfunction", "priority"]
    severity: Literal["low", "medium", "high"]
    area_id: str
    sensor_id: Optional[str] = None
    parameter: Optional[str] = None
    value: Optional[float] = None
    threshold: Optional[float] = None
    ts_event: str  # ISO 8601 UTC
    ts_emitted: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    context: AlertContext = Field(default_factory=AlertContext)

    def kafka_topic(self) -> str:
        """Return the Kafka topic this alert should be published to."""
        return f"alerts.{self.kind}"
