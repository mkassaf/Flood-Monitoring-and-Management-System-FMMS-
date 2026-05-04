"""Pydantic v2 request / response models for alert-service."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


# ─── Shared base ──────────────────────────────────────────────────────────────


class _Base(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ─── Alert context ────────────────────────────────────────────────────────────

_TREND = Literal["rising", "falling", "stable"]


class AlertContext(BaseModel):
    """Kind-specific extras embedded in the alert envelope."""

    model_config = ConfigDict(extra="allow")

    redundancy_remaining: Optional[int] = Field(
        default=None,
        ge=0,
        description=(
            "For malfunction alerts: count of still-operational sensors "
            "covering this parameter in the area."
        ),
    )
    trend: Optional[_TREND] = Field(
        default=None,
        description="For threshold alerts: short-window trend at the moment of breach.",
    )
    originating_alert_id: Optional[str] = Field(
        default=None,
        description="For priority alerts: UUID of the escalated source alert.",
    )


# ─── Wire-format alert (matches alert.schema.json 1.0.0) ─────────────────────

_KIND = Literal["threshold", "malfunction", "priority"]
_SEVERITY = Literal["low", "medium", "high"]
_PARAMETER = Literal[
    "water_level_m",
    "river_flow_velocity_m_s",
    "rainfall_mm_h",
    "soil_saturation_pct",
    "wind_speed_m_s",
    "wind_direction_deg",
]


class Alert(BaseModel):
    """Canonical alert payload — mirrors alert.schema.json v1.0.0 exactly."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    alert_id: str = Field(..., description="Globally unique UUID. Used for deduplication.")
    kind: _KIND
    severity: _SEVERITY
    area_id: str = Field(..., description="UUID of the affected area.")
    sensor_id: Optional[str] = Field(
        default=None,
        description="UUID of the originating sensor. Null for area-level alerts.",
    )
    parameter: Optional[_PARAMETER] = Field(
        default=None,
        description="Parameter that triggered the alert. Null for malfunction / area-level.",
    )
    value: Optional[float] = Field(
        default=None, description="Measured value at the moment of the alert."
    )
    threshold: Optional[float] = Field(
        default=None, description="Configured threshold the value crossed."
    )
    ts_event: datetime = Field(..., description="Time of the originating sensor event.")
    ts_emitted: datetime = Field(..., description="Time the rule engine produced this alert.")
    context: AlertContext = Field(default_factory=AlertContext)


# ─── REST response subset ─────────────────────────────────────────────────────


class AlertSummary(_Base):
    """Abbreviated alert representation for list endpoints."""

    alert_id: str
    kind: str
    severity: str
    area_id: str
    sensor_id: Optional[str]
    parameter: Optional[str]
    value: Optional[float]
    threshold: Optional[float]
    ts_event: datetime
    ts_emitted: datetime
    ts_persisted: datetime
    acknowledged_at: Optional[datetime]
    acknowledged_by: Optional[str]
    ack_reason: Optional[str]


# ─── Acknowledge request body ─────────────────────────────────────────────────


class AcknowledgeRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=1000)
