"""Pydantic v2 request / response models for geo-service."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# ─── Shared config ────────────────────────────────────────────────────────────

class _Base(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ─── Region ───────────────────────────────────────────────────────────────────

class RegionCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)


class Region(_Base):
    region_id: str
    name: str
    created_at: datetime


# ─── City ─────────────────────────────────────────────────────────────────────

class CityCreate(BaseModel):
    region_id: str
    name: str = Field(..., min_length=1, max_length=255)


class City(_Base):
    city_id: str
    region_id: str
    name: str
    created_at: datetime


# ─── Area ─────────────────────────────────────────────────────────────────────

class AreaCreate(BaseModel):
    city_id: str
    name: str = Field(..., min_length=1, max_length=255)
    risk_profile: str = "standard"


class Area(_Base):
    area_id: str
    city_id: str
    name: str
    risk_profile: str
    created_at: datetime


# ─── Sensor ───────────────────────────────────────────────────────────────────

class SensorCreate(BaseModel):
    area_id: str
    label: str | None = None


class Sensor(_Base):
    """Sensor response model — token_hash is intentionally excluded."""

    sensor_id: str
    area_id: str
    label: str | None
    decommissioned_at: datetime | None
    created_at: datetime


class SensorCreated(Sensor):
    """Returned only on creation; exposes the plaintext token exactly once."""

    token: str


# ─── Sensor→Area binding ──────────────────────────────────────────────────────

class SensorAreaBinding(_Base):
    """Returned by the hot-path sensor-lookup endpoint used by ingestion-gateway."""

    sensor_id: str
    area_id: str


# ─── Threshold ────────────────────────────────────────────────────────────────

class AreaThresholdUpsert(BaseModel):
    warning_lo: float | None = None
    warning_hi: float | None = None
    critical_lo: float | None = None
    critical_hi: float | None = None


class AreaThreshold(_Base):
    area_id: str
    parameter: str
    warning_lo: float | None
    warning_hi: float | None
    critical_lo: float | None
    critical_hi: float | None
