"""Pure threshold evaluation — no I/O, fully deterministic.

Given a telemetry message, a list of area thresholds, and a sliding window of
recent per-sensor values, returns zero or more Alert objects.
"""

from __future__ import annotations

from typing import Literal

from rule_engine.models import Alert, AlertContext, AreaThreshold, TelemetryMessage

# Number of historical readings used to compute trend
_TREND_WINDOW = 5


def _compute_trend(
    history: list[float],
    current: float,
) -> Literal["rising", "falling", "stable"]:
    """Determine trend from the most recent *_TREND_WINDOW* values including *current*.

    Uses a simple linear comparison: if the oldest value in the window is
    materially lower than the newest we call it rising, and vice versa.
    A relative tolerance of 1 % avoids noise-induced flip-flopping.
    """
    window = (history + [current])[-_TREND_WINDOW:]
    if len(window) < 2:
        return "stable"
    oldest, newest = window[0], window[-1]
    if oldest == 0.0:
        return "stable" if newest == 0.0 else "rising"
    delta_pct = (newest - oldest) / abs(oldest)
    if delta_pct > 0.01:
        return "rising"
    if delta_pct < -0.01:
        return "falling"
    return "stable"


def evaluate_thresholds(
    msg: TelemetryMessage,
    thresholds: list[AreaThreshold],
    existing_sensor_values: dict[str, list[float]],
) -> list[Alert]:
    """Evaluate each measurement in *msg* against configured *thresholds*.

    Args:
        msg: The incoming telemetry message.
        thresholds: Area threshold configs fetched from geo-service (may be empty).
        existing_sensor_values: Mapping of ``parameter → [val, val, …]`` (up to
            _TREND_WINDOW entries) previously stored for this sensor.  Used to
            compute the trend context field.

    Returns:
        A list of Alert objects (may be empty).  Callers are responsible for
        emitting these to the appropriate Kafka topic.
    """
    if not thresholds:
        return []

    # Index thresholds by parameter for O(1) lookup
    threshold_by_param: dict[str, AreaThreshold] = {t.parameter: t for t in thresholds}

    alerts: list[Alert] = []
    measurements = msg.measurements.as_param_dict()

    for parameter, value in measurements.items():
        thr = threshold_by_param.get(parameter)
        if thr is None:
            continue  # no threshold configured for this parameter

        severity: Literal["low", "medium", "high"] | None = None
        crossed_threshold: float | None = None

        # Evaluate in order: critical first, then warning
        if thr.critical_hi is not None and value > thr.critical_hi:
            severity = "high"
            crossed_threshold = thr.critical_hi
        elif thr.warning_hi is not None and value > thr.warning_hi:
            severity = "medium"
            crossed_threshold = thr.warning_hi
        elif thr.critical_lo is not None and value < thr.critical_lo:
            severity = "high"
            crossed_threshold = thr.critical_lo
        elif thr.warning_lo is not None and value < thr.warning_lo:
            severity = "medium"
            crossed_threshold = thr.warning_lo

        if severity is None:
            continue  # value within bounds

        history = existing_sensor_values.get(parameter, [])
        trend = _compute_trend(history, value)

        alerts.append(
            Alert(
                kind="threshold",
                severity=severity,
                area_id=msg.area_id,
                sensor_id=msg.sensor_id,
                parameter=parameter,
                value=value,
                threshold=crossed_threshold,
                ts_event=msg.ts,
                context=AlertContext(trend=trend),
            )
        )

    return alerts
