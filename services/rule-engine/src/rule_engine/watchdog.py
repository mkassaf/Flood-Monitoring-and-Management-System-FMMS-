"""Sensor silence watchdog — detects sensors that stop publishing (FR-08)."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import structlog
from redis.asyncio import Redis

from rule_engine.config import settings
from rule_engine.redundancy_tracker import RedundancyTracker

log = structlog.get_logger(__name__)


class SensorWatchdog:
    """Periodically scans Redis for sensors that have gone silent."""

    def __init__(
        self,
        redis_client: Redis,  # type: ignore[type-arg]
        tracker: RedundancyTracker,
    ) -> None:
        self._redis = redis_client
        self._tracker = tracker

    async def run(self) -> None:
        log.info("watchdog.started", interval_s=settings.watchdog_interval_s)
        while True:
            await asyncio.sleep(settings.watchdog_interval_s)
            try:
                await self._scan()
            except Exception:
                log.exception("watchdog.scan_error")

    async def _scan(self) -> None:
        now = datetime.now(timezone.utc)
        pattern = "sensor:*:latest"
        cursor = 0
        silent_count = 0

        while True:
            cursor, keys = await self._redis.scan(cursor, match=pattern, count=100)  # type: ignore[misc]
            for key in keys:
                raw = await self._redis.get(key)
                if raw is None:
                    continue
                try:
                    data = json.loads(raw)
                except Exception:
                    continue

                ingested_at_str = data.get("ingested_at") or data.get("ts")
                if not ingested_at_str:
                    continue

                try:
                    ingested_at = datetime.fromisoformat(ingested_at_str.replace("Z", "+00:00"))
                except ValueError:
                    continue

                age_s = (now - ingested_at).total_seconds()
                if age_s > settings.sensor_silence_timeout_s:
                    sensor_id = data.get("sensor_id")
                    area_id = data.get("area_id")
                    measurements = data.get("measurements", {})
                    params = [k for k, v in measurements.items() if v is not None]

                    if sensor_id and area_id and params:
                        await self._tracker.on_sensor_reading(
                            sensor_id=sensor_id,
                            area_id=area_id,
                            parameters=params,
                            status=0,
                            ts_event=ingested_at_str,
                        )
                        silent_count += 1

            if cursor == 0:
                break

        if silent_count:
            log.warning("watchdog.silent_sensors_detected", count=silent_count)
