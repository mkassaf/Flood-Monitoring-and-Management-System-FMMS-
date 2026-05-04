"""Unit tests for geo-service Pydantic models."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from geo_service.models import (
    Area,
    AreaCreate,
    AreaThreshold,
    AreaThresholdUpsert,
    City,
    CityCreate,
    Region,
    RegionCreate,
    Sensor,
    SensorAreaBinding,
    SensorCreate,
    SensorCreated,
)

# ─── Shared fixtures ──────────────────────────────────────────────────────────

_NOW = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
_REGION_ID = "11111111-1111-1111-1111-111111111111"
_CITY_ID = "22222222-2222-2222-2222-222222222222"
_AREA_ID = "33333333-3333-3333-3333-333333333333"
_SENSOR_ID = "44444444-4444-4444-4444-444444444444"


# ─── Region ───────────────────────────────────────────────────────────────────


def test_region_create_valid() -> None:
    body = RegionCreate(name="North Region")
    assert body.name == "North Region"


def test_region_create_rejects_empty_name() -> None:
    with pytest.raises(ValidationError):
        RegionCreate(name="")


def test_region_response_model() -> None:
    region = Region(region_id=_REGION_ID, name="North Region", created_at=_NOW)
    assert region.region_id == _REGION_ID
    assert region.name == "North Region"
    assert region.created_at == _NOW


# ─── City ─────────────────────────────────────────────────────────────────────


def test_city_create_valid() -> None:
    body = CityCreate(region_id=_REGION_ID, name="Springfield")
    assert body.region_id == _REGION_ID


def test_city_create_rejects_empty_name() -> None:
    with pytest.raises(ValidationError):
        CityCreate(region_id=_REGION_ID, name="")


def test_city_response_model() -> None:
    city = City(city_id=_CITY_ID, region_id=_REGION_ID, name="Springfield", created_at=_NOW)
    assert city.city_id == _CITY_ID
    assert city.region_id == _REGION_ID


# ─── Area ─────────────────────────────────────────────────────────────────────


def test_area_create_defaults_risk_profile() -> None:
    body = AreaCreate(city_id=_CITY_ID, name="Downtown")
    assert body.risk_profile == "standard"


def test_area_create_custom_risk_profile() -> None:
    body = AreaCreate(city_id=_CITY_ID, name="Floodplain", risk_profile="high")
    assert body.risk_profile == "high"


def test_area_create_rejects_empty_name() -> None:
    with pytest.raises(ValidationError):
        AreaCreate(city_id=_CITY_ID, name="")


def test_area_response_model() -> None:
    area = Area(
        area_id=_AREA_ID,
        city_id=_CITY_ID,
        name="Downtown",
        risk_profile="standard",
        created_at=_NOW,
    )
    assert area.area_id == _AREA_ID
    assert area.risk_profile == "standard"


# ─── Sensor ───────────────────────────────────────────────────────────────────


def test_sensor_create_valid_with_label() -> None:
    body = SensorCreate(area_id=_AREA_ID, label="river-gauge-01")
    assert body.label == "river-gauge-01"


def test_sensor_create_valid_without_label() -> None:
    body = SensorCreate(area_id=_AREA_ID)
    assert body.label is None


def test_sensor_response_does_not_expose_token_hash() -> None:
    """token_hash must never appear in the Sensor response model."""
    sensor = Sensor(
        sensor_id=_SENSOR_ID,
        area_id=_AREA_ID,
        label="gauge-01",
        decommissioned_at=None,
        created_at=_NOW,
    )
    serialised = sensor.model_dump()
    assert "token_hash" not in serialised


def test_sensor_response_fields() -> None:
    sensor = Sensor(
        sensor_id=_SENSOR_ID,
        area_id=_AREA_ID,
        label=None,
        decommissioned_at=None,
        created_at=_NOW,
    )
    assert sensor.sensor_id == _SENSOR_ID
    assert sensor.label is None
    assert sensor.decommissioned_at is None


def test_sensor_created_includes_token() -> None:
    created = SensorCreated(
        sensor_id=_SENSOR_ID,
        area_id=_AREA_ID,
        label="gauge-01",
        decommissioned_at=None,
        created_at=_NOW,
        token="supersecrettoken",
    )
    assert created.token == "supersecrettoken"
    # Confirm token_hash is still absent
    assert "token_hash" not in created.model_dump()


def test_sensor_created_token_hash_not_in_schema() -> None:
    """Verify at the schema level that token_hash is not a declared field."""
    field_names = set(SensorCreated.model_fields.keys())
    assert "token_hash" not in field_names


# ─── SensorAreaBinding ────────────────────────────────────────────────────────


def test_sensor_area_binding_valid() -> None:
    binding = SensorAreaBinding(sensor_id=_SENSOR_ID, area_id=_AREA_ID)
    assert binding.sensor_id == _SENSOR_ID
    assert binding.area_id == _AREA_ID


def test_sensor_area_binding_requires_both_fields() -> None:
    with pytest.raises(ValidationError):
        SensorAreaBinding(sensor_id=_SENSOR_ID)  # type: ignore[call-arg]


# ─── AreaThreshold ────────────────────────────────────────────────────────────


def test_area_threshold_all_optional_floats() -> None:
    threshold = AreaThreshold(
        area_id=_AREA_ID,
        parameter="water_level",
        warning_lo=None,
        warning_hi=None,
        critical_lo=None,
        critical_hi=None,
    )
    assert threshold.warning_lo is None
    assert threshold.critical_hi is None


def test_area_threshold_with_values() -> None:
    threshold = AreaThreshold(
        area_id=_AREA_ID,
        parameter="water_level",
        warning_lo=1.0,
        warning_hi=2.5,
        critical_lo=0.5,
        critical_hi=3.5,
    )
    assert threshold.warning_hi == 2.5
    assert threshold.critical_lo == 0.5


def test_area_threshold_upsert_all_none() -> None:
    upsert = AreaThresholdUpsert()
    assert upsert.warning_lo is None
    assert upsert.critical_hi is None


def test_area_threshold_upsert_partial() -> None:
    upsert = AreaThresholdUpsert(warning_lo=1.0, critical_hi=5.0)
    assert upsert.warning_lo == 1.0
    assert upsert.warning_hi is None
    assert upsert.critical_hi == 5.0
