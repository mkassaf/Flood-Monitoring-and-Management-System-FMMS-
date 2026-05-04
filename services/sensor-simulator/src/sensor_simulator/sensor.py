"""Individual sensor simulation: random walk, adaptive frequency, edge filtering, fault injection."""

from __future__ import annotations

import asyncio
import random
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

from sensor_simulator.models import Measurements, TelemetryEnvelope

if TYPE_CHECKING:
    import paho.mqtt.client as mqtt

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Parameter metadata: (min, max, typical_step_size)
# ---------------------------------------------------------------------------
PARAM_META: dict[str, tuple[float, float, float]] = {
    "water_level_m": (0.0, 50.0, 0.1),
    "river_flow_velocity_m_s": (0.0, 20.0, 0.05),
    "rainfall_mm_h": (0.0, 500.0, 1.0),
    "soil_saturation_pct": (0.0, 100.0, 0.5),
    "wind_speed_m_s": (0.0, 100.0, 0.2),
    "wind_direction_deg": (0.0, 359.99, 1.0),
}

CRITICAL_THRESHOLD_FRACTION = 0.70  # switch to critical if value > 70% of max
# Fault lasts between 3 and 10 cycles.
FAULT_MIN_CYCLES = 3
FAULT_MAX_CYCLES = 10


class Sensor:
    """Simulates a single physical sensor over its full lifecycle."""

    def __init__(
        self,
        sensor_id: str,
        area_id: str,
        active_params: list[str],
        nominal_interval: float,
        critical_interval: float,
        fault_probability: float,
        delta_filter_pct: float,
        rng: random.Random,
    ) -> None:
        if not active_params:
            raise ValueError("A sensor must have at least one active parameter.")
        self.sensor_id = sensor_id
        self.area_id = area_id
        self.active_params = active_params
        self.nominal_interval = nominal_interval
        self.critical_interval = critical_interval
        self.fault_probability = fault_probability
        self.delta_filter_pct = delta_filter_pct
        self._rng = rng

        # Current state
        self._current: dict[str, float] = {
            p: rng.uniform(*PARAM_META[p][:2]) for p in active_params
        }
        self._last_published: dict[str, float] = {}
        self._fault_cycles_remaining: int = 0

        self._log = logger.bind(sensor_id=sensor_id, area_id=area_id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _generate_measurements(self) -> dict[str, float]:
        """Advance each active param by a bounded random walk."""
        updated: dict[str, float] = {}
        for param in self.active_params:
            lo, hi, step = PARAM_META[param]
            delta = self._rng.gauss(0, step)
            new_val = self._current[param] + delta
            new_val = max(lo, min(hi, new_val))
            self._current[param] = new_val
            updated[param] = new_val
        return updated

    def _check_critical(self, measurements: dict[str, float]) -> bool:
        """Return True if any measurement exceeds 70% of its configured maximum."""
        for param, value in measurements.items():
            _, hi, _ = PARAM_META[param]
            if value > CRITICAL_THRESHOLD_FRACTION * hi:
                return True
        return False

    def _should_suppress(self, measurements: dict[str, float]) -> bool:
        """Return True if every param's change since last publish is below the delta threshold."""
        if not self._last_published:
            return False
        for param, value in measurements.items():
            _, hi, _ = PARAM_META[param]
            threshold = self.delta_filter_pct * hi
            previous = self._last_published.get(param)
            if previous is None or abs(value - previous) >= threshold:
                return False
        return True

    def _build_envelope(
        self,
        measurements: dict[str, float],
        is_critical: bool,
        is_faulty: bool,
    ) -> TelemetryEnvelope:
        meas_kwargs = {p: measurements.get(p) for p in PARAM_META}
        return TelemetryEnvelope(
            sensor_id=self.sensor_id,
            area_id=self.area_id,
            ts=datetime.now(UTC).isoformat(),
            status=0 if is_faulty else 1,
            mode="critical" if is_critical else "nominal",
            measurements=Measurements(**meas_kwargs),
        )

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def run(
        self,
        client: "mqtt.Client",
        published_counter: object,  # prometheus Counter
        suppressed_counter: object,  # prometheus Counter
    ) -> None:
        """Sensor main loop — runs until the asyncio task is cancelled."""
        self._log.info("sensor started", active_params=self.active_params)
        try:
            while True:
                measurements = self._generate_measurements()
                is_critical = self._check_critical(measurements)

                # Fault injection
                if self._fault_cycles_remaining > 0:
                    self._fault_cycles_remaining -= 1
                    is_faulty = True
                elif self._rng.random() < self.fault_probability:
                    self._fault_cycles_remaining = self._rng.randint(
                        FAULT_MIN_CYCLES, FAULT_MAX_CYCLES
                    )
                    is_faulty = True
                else:
                    is_faulty = False

                # Edge-filtering: faulty sensors always transmit (status=0 is important info)
                if not is_faulty and self._should_suppress(measurements):
                    self._log.debug("suppressed (delta filter)")
                    try:
                        suppressed_counter.labels(area_id=self.area_id).inc()  # type: ignore[union-attr]
                    except Exception:  # noqa: BLE001
                        pass
                    interval = self.critical_interval if is_critical else self.nominal_interval
                    await asyncio.sleep(interval)
                    continue

                envelope = self._build_envelope(measurements, is_critical, is_faulty)
                payload = envelope.model_dump_json()
                topic = f"sensors/{self.sensor_id}"

                try:
                    info = await asyncio.to_thread(
                        client.publish, topic, payload, qos=1
                    )
                    info.wait_for_publish(timeout=5.0)
                    self._last_published = dict(measurements)
                    self._log.debug(
                        "published",
                        topic=topic,
                        mode=envelope.mode,
                        status=envelope.status,
                    )
                    try:
                        published_counter.labels(area_id=self.area_id).inc()  # type: ignore[union-attr]
                    except Exception:  # noqa: BLE001
                        pass
                except Exception as exc:
                    self._log.error("publish failed", error=str(exc))

                interval = self.critical_interval if is_critical else self.nominal_interval
                await asyncio.sleep(interval)

        except asyncio.CancelledError:
            self._log.info("sensor stopped")
            raise
