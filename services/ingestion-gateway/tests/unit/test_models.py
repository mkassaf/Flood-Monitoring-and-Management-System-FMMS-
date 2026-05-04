"""Unit tests for the TelemetryEnvelope and related Pydantic models."""

import pytest
from pydantic import ValidationError

from ingestion_gateway.models import KafkaMessage, Measurements, TelemetryEnvelope

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_PAYLOAD: dict = {
    "schema_version": "1.0.0",
    "sensor_id": "550e8400-e29b-41d4-a716-446655440000",
    "area_id": "660e8400-e29b-41d4-a716-446655440001",
    "ts": "2024-06-01T12:00:00Z",
    "status": 1,
    "mode": "nominal",
    "measurements": {"water_level_m": 1.5},
}


def _make(**overrides) -> dict:
    return {**VALID_PAYLOAD, **overrides}


# ---------------------------------------------------------------------------
# Measurements
# ---------------------------------------------------------------------------


class TestMeasurements:
    def test_valid_single_measurement(self) -> None:
        m = Measurements(water_level_m=2.0)
        assert m.water_level_m == 2.0

    def test_valid_multiple_measurements(self) -> None:
        m = Measurements(water_level_m=1.0, rainfall_mm_h=10.0)
        assert m.rainfall_mm_h == 10.0

    def test_all_none_raises_value_error(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            Measurements()
        errors = exc_info.value.errors()
        assert any("at least one measurement" in str(e["msg"]) for e in errors)

    def test_water_level_below_zero_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Measurements(water_level_m=-0.1)

    def test_water_level_above_max_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Measurements(water_level_m=50.1)

    def test_river_flow_velocity_boundary(self) -> None:
        m = Measurements(river_flow_velocity_m_s=20.0)
        assert m.river_flow_velocity_m_s == 20.0

    def test_river_flow_velocity_above_max_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Measurements(river_flow_velocity_m_s=20.1)

    def test_rainfall_boundary(self) -> None:
        m = Measurements(rainfall_mm_h=500.0)
        assert m.rainfall_mm_h == 500.0

    def test_rainfall_above_max_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Measurements(rainfall_mm_h=500.1)

    def test_soil_saturation_boundary(self) -> None:
        m = Measurements(soil_saturation_pct=100.0)
        assert m.soil_saturation_pct == 100.0

    def test_soil_saturation_above_max_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Measurements(soil_saturation_pct=100.1)

    def test_wind_direction_exclusive_maximum(self) -> None:
        """360 degrees must be rejected (exclusive maximum)."""
        with pytest.raises(ValidationError):
            Measurements(wind_direction_deg=360.0)

    def test_wind_direction_just_below_max_accepted(self) -> None:
        m = Measurements(wind_direction_deg=359.9)
        assert m.wind_direction_deg == pytest.approx(359.9)

    def test_wind_speed_zero_accepted(self) -> None:
        m = Measurements(wind_speed_m_s=0.0)
        assert m.wind_speed_m_s == 0.0


# ---------------------------------------------------------------------------
# TelemetryEnvelope
# ---------------------------------------------------------------------------


class TestTelemetryEnvelope:
    def test_valid_payload_accepted(self) -> None:
        env = TelemetryEnvelope.model_validate(VALID_PAYLOAD)
        assert env.schema_version == "1.0.0"
        assert env.sensor_id == VALID_PAYLOAD["sensor_id"]
        assert env.area_id == VALID_PAYLOAD["area_id"]
        assert env.status == 1
        assert env.mode == "nominal"
        assert env.measurements.water_level_m == 1.5

    def test_schema_version_must_be_1_0_0(self) -> None:
        with pytest.raises(ValidationError):
            TelemetryEnvelope.model_validate(_make(schema_version="2.0.0"))

    def test_schema_version_wrong_string_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TelemetryEnvelope.model_validate(_make(schema_version="1.0"))

    def test_invalid_status_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TelemetryEnvelope.model_validate(_make(status=2))

    def test_status_zero_accepted(self) -> None:
        env = TelemetryEnvelope.model_validate(_make(status=0))
        assert env.status == 0

    def test_invalid_mode_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TelemetryEnvelope.model_validate(_make(mode="emergency"))

    def test_mode_critical_accepted(self) -> None:
        env = TelemetryEnvelope.model_validate(_make(mode="critical"))
        assert env.mode == "critical"

    def test_missing_schema_version_rejected(self) -> None:
        payload = {k: v for k, v in VALID_PAYLOAD.items() if k != "schema_version"}
        with pytest.raises(ValidationError):
            TelemetryEnvelope.model_validate(payload)

    def test_missing_measurements_rejected(self) -> None:
        payload = {k: v for k, v in VALID_PAYLOAD.items() if k != "measurements"}
        with pytest.raises(ValidationError):
            TelemetryEnvelope.model_validate(payload)

    def test_empty_measurements_object_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TelemetryEnvelope.model_validate(_make(measurements={}))

    def test_all_measurement_fields_present(self) -> None:
        env = TelemetryEnvelope.model_validate(
            _make(
                measurements={
                    "water_level_m": 3.0,
                    "river_flow_velocity_m_s": 1.5,
                    "rainfall_mm_h": 20.0,
                    "soil_saturation_pct": 85.0,
                    "wind_speed_m_s": 12.0,
                    "wind_direction_deg": 270.0,
                }
            )
        )
        assert env.measurements.wind_direction_deg == 270.0

    def test_missing_required_field_sensor_id_rejected(self) -> None:
        payload = {k: v for k, v in VALID_PAYLOAD.items() if k != "sensor_id"}
        with pytest.raises(ValidationError):
            TelemetryEnvelope.model_validate(payload)

    def test_missing_required_field_area_id_rejected(self) -> None:
        payload = {k: v for k, v in VALID_PAYLOAD.items() if k != "area_id"}
        with pytest.raises(ValidationError):
            TelemetryEnvelope.model_validate(payload)


# ---------------------------------------------------------------------------
# KafkaMessage
# ---------------------------------------------------------------------------


class TestKafkaMessage:
    def test_kafka_message_extends_envelope_with_ingested_at(self) -> None:
        km = KafkaMessage.model_validate(
            {**VALID_PAYLOAD, "ingested_at": "2024-06-01T12:00:01Z"}
        )
        assert km.ingested_at == "2024-06-01T12:00:01Z"
        assert km.schema_version == "1.0.0"

    def test_kafka_message_missing_ingested_at_rejected(self) -> None:
        with pytest.raises(ValidationError):
            KafkaMessage.model_validate(VALID_PAYLOAD)

    def test_model_dump_round_trip(self) -> None:
        km = KafkaMessage.model_validate(
            {**VALID_PAYLOAD, "ingested_at": "2024-06-01T12:00:01Z"}
        )
        dumped = km.model_dump()
        assert dumped["ingested_at"] == "2024-06-01T12:00:01Z"
        assert dumped["measurements"]["water_level_m"] == 1.5
