"""Per-area sensor redundancy state tracked in Redis (FR-08).

State keys (set by this module and by telemetry-service):
  area:{area_id}:operational_count:{parameter}  → int
  sensor:{sensor_id}:fault_count                → int (consecutive status=0 readings)

Escalation rules:
  status=0, count decremented to > 0  → malfunction, severity=low
  status=0, count decremented to == 0 → malfunction, severity=high
                                       + priority, severity=high
  status=1 after fault (count recovered from 0 to 1) → info log only, no alert
"""

from __future__ import annotations

import structlog
from redis.asyncio import Redis

from rule_engine.metrics import ALERTS_EMITTED, REDUNDANCY_ESCALATIONS
from rule_engine.models import Alert, AlertContext

log = structlog.get_logger(__name__)

_FAULT_COUNT_TTL_S = 3600  # auto-expire fault counters after 1 hour without update


class RedundancyTracker:
    """Manages sensor redundancy state in Redis and emits alerts on state change."""

    def __init__(self, redis_client: Redis) -> None:  # type: ignore[type-arg]
        self._redis = redis_client

    # ── Public API ────────────────────────────────────────────────────────────

    async def on_sensor_reading(
        self,
        sensor_id: str,
        area_id: str,
        parameters: list[str],
        status: int,
        ts_event: str,
    ) -> list[Alert]:
        """Process a sensor status update and return any alerts that result.

        Args:
            sensor_id: Originating sensor UUID string.
            area_id: Area the sensor belongs to.
            parameters: List of parameters the sensor measures.
            status: 1 = healthy, 0 = fault.
            ts_event: ISO 8601 timestamp of the originating telemetry event.
        """
        alerts: list[Alert] = []

        if status == 0:
            alerts.extend(
                await self._handle_fault(sensor_id, area_id, parameters, ts_event)
            )
        else:
            await self._handle_recovery(sensor_id, area_id, parameters)

        return alerts

    async def init_area_sensor_count(
        self, area_id: str, parameter: str, count: int
    ) -> None:
        """Initialise operational count only if the key does not already exist (NX)."""
        key = self._count_key(area_id, parameter)
        await self._redis.set(key, count, nx=True)

    async def get_operational_count(self, area_id: str, parameter: str) -> int:
        """Return current operational sensor count for *area_id* / *parameter*."""
        key = self._count_key(area_id, parameter)
        raw = await self._redis.get(key)
        if raw is None:
            return 0
        return int(raw)

    async def decrement(self, area_id: str, parameter: str) -> int:
        """Atomically decrement the operational count, clamped to 0.

        Returns the new (post-decrement) value.
        """
        key = self._count_key(area_id, parameter)
        # DECR is atomic; clamp to 0 to avoid negative counts.
        new_value: int = await self._redis.decr(key)
        if new_value < 0:
            await self._redis.set(key, 0)
            return 0
        return new_value

    async def increment(self, area_id: str, parameter: str) -> int:
        """Atomically increment the operational count and return the new value."""
        key = self._count_key(area_id, parameter)
        new_value: int = await self._redis.incr(key)
        return new_value

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _handle_fault(
        self,
        sensor_id: str,
        area_id: str,
        parameters: list[str],
        ts_event: str,
    ) -> list[Alert]:
        fault_key = self._fault_key(sensor_id)
        fault_count: int = await self._redis.incr(fault_key)
        await self._redis.expire(fault_key, _FAULT_COUNT_TTL_S)

        alerts: list[Alert] = []

        # Only adjust operational count on the *first* fault in a run
        if fault_count != 1:
            return alerts

        for parameter in parameters:
            new_count = await self.decrement(area_id, parameter)

            if new_count == 0:
                # Total loss of coverage — high malfunction + priority escalation
                REDUNDANCY_ESCALATIONS.inc()
                malfunction = Alert(
                    kind="malfunction",
                    severity="high",
                    area_id=area_id,
                    sensor_id=sensor_id,
                    parameter=parameter,
                    ts_event=ts_event,
                    context=AlertContext(redundancy_remaining=0),
                )
                priority = Alert(
                    kind="priority",
                    severity="high",
                    area_id=area_id,
                    sensor_id=sensor_id,
                    parameter=parameter,
                    ts_event=ts_event,
                    context=AlertContext(
                        redundancy_remaining=0,
                        originating_alert_id=malfunction.alert_id,
                    ),
                )
                ALERTS_EMITTED.labels(kind="malfunction", severity="high").inc()
                ALERTS_EMITTED.labels(kind="priority", severity="high").inc()
                alerts.extend([malfunction, priority])
                log.warning(
                    "redundancy.full_loss",
                    area_id=area_id,
                    parameter=parameter,
                    sensor_id=sensor_id,
                )
            else:
                # Partial degradation — low malfunction
                malfunction = Alert(
                    kind="malfunction",
                    severity="low",
                    area_id=area_id,
                    sensor_id=sensor_id,
                    parameter=parameter,
                    ts_event=ts_event,
                    context=AlertContext(redundancy_remaining=new_count),
                )
                ALERTS_EMITTED.labels(kind="malfunction", severity="low").inc()
                alerts.append(malfunction)
                log.info(
                    "redundancy.degraded",
                    area_id=area_id,
                    parameter=parameter,
                    remaining=new_count,
                    sensor_id=sensor_id,
                )

        return alerts

    async def _handle_recovery(
        self,
        sensor_id: str,
        area_id: str,
        parameters: list[str],
    ) -> None:
        fault_key = self._fault_key(sensor_id)
        raw = await self._redis.get(fault_key)
        if raw is None or int(raw) == 0:
            # No prior fault recorded — nothing to recover
            return

        # Clear the fault counter
        await self._redis.delete(fault_key)

        for parameter in parameters:
            new_count = await self.increment(area_id, parameter)
            if new_count == 1:
                log.info(
                    "redundancy.recovered",
                    area_id=area_id,
                    parameter=parameter,
                    sensor_id=sensor_id,
                )

    # ── Key helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _count_key(area_id: str, parameter: str) -> str:
        return f"area:{area_id}:operational_count:{parameter}"

    @staticmethod
    def _fault_key(sensor_id: str) -> str:
        return f"sensor:{sensor_id}:fault_count"
