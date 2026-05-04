"""Unit tests for sensor.py — critical detection, delta suppression, range safety."""

from __future__ import annotations

import random

import pytest

from sensor_simulator.sensor import (
    CRITICAL_THRESHOLD_FRACTION,
    PARAM_META,
    Sensor,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_sensor(
    params: list[str] | None = None,
    fault_probability: float = 0.0,
    delta_filter_pct: float = 0.02,
) -> Sensor:
    if params is None:
        params = ["water_level_m", "rainfall_mm_h"]
    return Sensor(
        sensor_id="00000000-0000-0000-0000-000000000001",
        area_id="00000000-0000-0000-0000-000000000002",
        active_params=params,
        nominal_interval=60.0,
        critical_interval=5.0,
        fault_probability=fault_probability,
        delta_filter_pct=delta_filter_pct,
        rng=random.Random(42),  # noqa: S311
    )


# ---------------------------------------------------------------------------
# _check_critical
# ---------------------------------------------------------------------------


class TestCheckCritical:
    def test_all_below_threshold_returns_false(self) -> None:
        sensor = _make_sensor(["water_level_m"])
        _, hi, _ = PARAM_META["water_level_m"]
        # Value at exactly 50% of max — should not be critical
        measurements = {"water_level_m": 0.5 * hi}
        assert sensor._check_critical(measurements) is False

    def test_value_at_threshold_boundary_returns_false(self) -> None:
        sensor = _make_sensor(["water_level_m"])
        _, hi, _ = PARAM_META["water_level_m"]
        # Exactly at threshold — NOT strictly greater, so nominal
        measurements = {"water_level_m": CRITICAL_THRESHOLD_FRACTION * hi}
        assert sensor._check_critical(measurements) is False

    def test_value_above_threshold_returns_true(self) -> None:
        sensor = _make_sensor(["water_level_m"])
        _, hi, _ = PARAM_META["water_level_m"]
        measurements = {"water_level_m": (CRITICAL_THRESHOLD_FRACTION + 0.01) * hi}
        assert sensor._check_critical(measurements) is True

    def test_any_param_above_threshold_returns_true(self) -> None:
        sensor = _make_sensor(["water_level_m", "rainfall_mm_h"])
        _, wl_hi, _ = PARAM_META["water_level_m"]
        _, rain_hi, _ = PARAM_META["rainfall_mm_h"]
        measurements = {
            "water_level_m": 0.1 * wl_hi,  # nominal
            "rainfall_mm_h": 0.9 * rain_hi,  # critical
        }
        assert sensor._check_critical(measurements) is True

    def test_all_params_above_threshold_returns_true(self) -> None:
        sensor = _make_sensor(["water_level_m", "rainfall_mm_h"])
        _, wl_hi, _ = PARAM_META["water_level_m"]
        _, rain_hi, _ = PARAM_META["rainfall_mm_h"]
        measurements = {
            "water_level_m": 0.8 * wl_hi,
            "rainfall_mm_h": 0.8 * rain_hi,
        }
        assert sensor._check_critical(measurements) is True


# ---------------------------------------------------------------------------
# _should_suppress
# ---------------------------------------------------------------------------


class TestShouldSuppress:
    def test_no_prior_publish_never_suppresses(self) -> None:
        sensor = _make_sensor(["water_level_m"])
        assert sensor._last_published == {}
        measurements = {"water_level_m": 1.0}
        assert sensor._should_suppress(measurements) is False

    def test_identical_value_suppressed(self) -> None:
        sensor = _make_sensor(["water_level_m"])
        value = 5.0
        sensor._last_published = {"water_level_m": value}
        # No change at all — should suppress
        assert sensor._should_suppress({"water_level_m": value}) is True

    def test_change_below_delta_suppressed(self) -> None:
        sensor = _make_sensor(["water_level_m"], delta_filter_pct=0.02)
        _, hi, _ = PARAM_META["water_level_m"]
        threshold = 0.02 * hi  # 1.0m for water_level (range 0-50)
        sensor._last_published = {"water_level_m": 10.0}
        # Change is half the threshold → suppress
        small_change = threshold * 0.5
        assert sensor._should_suppress({"water_level_m": 10.0 + small_change}) is True

    def test_change_equal_to_delta_not_suppressed(self) -> None:
        sensor = _make_sensor(["water_level_m"], delta_filter_pct=0.02)
        _, hi, _ = PARAM_META["water_level_m"]
        threshold = 0.02 * hi
        sensor._last_published = {"water_level_m": 10.0}
        # Change equals threshold exactly → NOT suppressed (>= threshold passes through)
        assert sensor._should_suppress({"water_level_m": 10.0 + threshold}) is False

    def test_change_above_delta_not_suppressed(self) -> None:
        sensor = _make_sensor(["water_level_m"], delta_filter_pct=0.02)
        _, hi, _ = PARAM_META["water_level_m"]
        threshold = 0.02 * hi
        sensor._last_published = {"water_level_m": 10.0}
        big_change = threshold * 2.0
        assert sensor._should_suppress({"water_level_m": 10.0 + big_change}) is False

    def test_any_param_exceeds_delta_not_suppressed(self) -> None:
        """If even one param has changed enough, the whole reading goes through."""
        sensor = _make_sensor(["water_level_m", "rainfall_mm_h"], delta_filter_pct=0.02)
        _, wl_hi, _ = PARAM_META["water_level_m"]
        _, rain_hi, _ = PARAM_META["rainfall_mm_h"]
        sensor._last_published = {
            "water_level_m": 5.0,
            "rainfall_mm_h": 100.0,
        }
        measurements = {
            "water_level_m": 5.0,  # unchanged
            "rainfall_mm_h": 100.0 + 0.05 * rain_hi,  # large change
        }
        assert sensor._should_suppress(measurements) is False

    def test_all_params_must_be_small_to_suppress(self) -> None:
        sensor = _make_sensor(["water_level_m", "rainfall_mm_h"], delta_filter_pct=0.02)
        _, wl_hi, _ = PARAM_META["water_level_m"]
        _, rain_hi, _ = PARAM_META["rainfall_mm_h"]
        sensor._last_published = {
            "water_level_m": 5.0,
            "rainfall_mm_h": 100.0,
        }
        measurements = {
            "water_level_m": 5.0 + 0.001 * wl_hi,  # tiny change
            "rainfall_mm_h": 100.0 + 0.001 * rain_hi,  # tiny change
        }
        assert sensor._should_suppress(measurements) is True


# ---------------------------------------------------------------------------
# Measurements stay within valid ranges after many steps
# ---------------------------------------------------------------------------


class TestMeasurementRanges:
    @pytest.mark.parametrize("param", list(PARAM_META.keys()))
    def test_param_stays_in_range_after_many_steps(self, param: str) -> None:
        sensor = _make_sensor([param])
        lo, hi, _ = PARAM_META[param]
        for _ in range(500):
            measurements = sensor._generate_measurements()
            value = measurements[param]
            assert lo <= value <= hi, (
                f"param={param} value={value} out of [{lo}, {hi}]"
            )

    def test_multiple_params_all_stay_in_range(self) -> None:
        all_params = list(PARAM_META.keys())
        sensor = _make_sensor(all_params)
        for _ in range(200):
            measurements = sensor._generate_measurements()
            for param, value in measurements.items():
                lo, hi, _ = PARAM_META[param]
                assert lo <= value <= hi, (
                    f"param={param} value={value} out of [{lo}, {hi}]"
                )


# ---------------------------------------------------------------------------
# Sensor initialisation
# ---------------------------------------------------------------------------


class TestSensorInit:
    def test_requires_at_least_one_active_param(self) -> None:
        with pytest.raises(ValueError, match="at least one"):
            _make_sensor(params=[])

    def test_initial_state_within_valid_range(self) -> None:
        sensor = _make_sensor(["water_level_m", "soil_saturation_pct"])
        for param, value in sensor._current.items():
            lo, hi, _ = PARAM_META[param]
            assert lo <= value <= hi

    def test_last_published_empty_on_init(self) -> None:
        sensor = _make_sensor()
        assert sensor._last_published == {}

    def test_fault_cycles_zero_on_init(self) -> None:
        sensor = _make_sensor()
        assert sensor._fault_cycles_remaining == 0
