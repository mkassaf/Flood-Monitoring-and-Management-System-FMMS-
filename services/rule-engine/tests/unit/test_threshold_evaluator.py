"""Unit tests for the pure threshold evaluation function."""
import pytest
from rule_engine.models import AreaThreshold, Measurements, TelemetryMessage
from rule_engine.threshold_evaluator import evaluate_thresholds


def _make_msg(water_level: float | None = None, rainfall: float | None = None) -> TelemetryMessage:
    return TelemetryMessage(
        schema_version="1.0.0",
        sensor_id="00000000-0000-0000-0000-000000000001",
        area_id="00000000-0000-0000-0000-000000000002",
        ts="2024-01-01T00:00:00+00:00",
        status=1,
        mode="nominal",
        measurements=Measurements(water_level_m=water_level, rainfall_mm_h=rainfall),
        ingested_at="2024-01-01T00:00:00+00:00",
    )


def _make_thresholds() -> list[AreaThreshold]:
    return [
        AreaThreshold(
            area_id="00000000-0000-0000-0000-000000000002",
            parameter="water_level_m",
            warning_hi=2.0,
            critical_hi=3.0,
            warning_lo=None,
            critical_lo=None,
        ),
        AreaThreshold(
            area_id="00000000-0000-0000-0000-000000000002",
            parameter="rainfall_mm_h",
            warning_hi=20.0,
            critical_hi=30.0,
            warning_lo=None,
            critical_lo=None,
        ),
    ]


def test_no_alerts_when_below_all_thresholds():
    msg = _make_msg(water_level=1.0, rainfall=5.0)
    alerts = evaluate_thresholds(msg, _make_thresholds(), {})
    assert alerts == []


def test_warning_alert_when_above_warning_hi():
    msg = _make_msg(water_level=2.5)
    alerts = evaluate_thresholds(msg, _make_thresholds(), {})
    assert len(alerts) == 1
    assert alerts[0].severity == "medium"
    assert alerts[0].kind == "threshold"
    assert alerts[0].parameter == "water_level_m"


def test_critical_alert_when_above_critical_hi():
    msg = _make_msg(water_level=3.5)
    alerts = evaluate_thresholds(msg, _make_thresholds(), {})
    assert len(alerts) == 1
    assert alerts[0].severity == "high"
    assert alerts[0].threshold == 3.0


def test_multiple_parameters_both_breached():
    msg = _make_msg(water_level=4.0, rainfall=35.0)
    alerts = evaluate_thresholds(msg, _make_thresholds(), {})
    assert len(alerts) == 2
    assert all(a.severity == "high" for a in alerts)


def test_no_alerts_when_no_thresholds_configured():
    msg = _make_msg(water_level=10.0)
    alerts = evaluate_thresholds(msg, [], {})
    assert alerts == []


def test_trend_is_rising_when_values_increase():
    msg = _make_msg(water_level=2.5)
    history = {"water_level_m": [1.0, 1.5, 2.0]}
    alerts = evaluate_thresholds(msg, _make_thresholds(), history)
    assert len(alerts) == 1
    assert alerts[0].context.trend == "rising"


def test_trend_is_falling_when_values_decrease():
    msg = _make_msg(water_level=2.1)
    history = {"water_level_m": [5.0, 4.0, 3.0]}
    alerts = evaluate_thresholds(msg, _make_thresholds(), history)
    assert alerts[0].context.trend == "falling"


def test_critical_takes_precedence_over_warning():
    msg = _make_msg(water_level=3.5)
    alerts = evaluate_thresholds(msg, _make_thresholds(), {})
    assert alerts[0].severity == "high"
    assert alerts[0].threshold == 3.0  # critical threshold, not warning
