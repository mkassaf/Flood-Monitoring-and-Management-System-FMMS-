"""Redis hot-state updater.

Writes the latest telemetry reading for each sensor (and a timestamp per area)
into Redis so the rule-engine and dashboard-bff can retrieve recent state
without hitting TimescaleDB.

Keys
----
sensor:{sensor_id}:latest  — JSON-serialised TelemetryMessage, TTL = REDIS_HOT_STATE_TTL_S
area:{area_id}:latest_ts   — ISO 8601 UTC string of the most recent reading, same TTL
"""

from __future__ import annotations

import redis.asyncio as aioredis
import structlog
from prometheus_client import Counter

from telemetry_service.models import TelemetryMessage

log = structlog.get_logger(__name__)

# ─── Prometheus metrics ────────────────────────────────────────────────────────

hot_state_updates_total = Counter(
    "telemetry_hot_state_updates_total",
    "Total successful Redis hot-state updates",
)


class HotStateUpdater:
    """Write sensor and area latest-state into Redis using a pipeline."""

    def __init__(self, redis_client: aioredis.Redis, ttl_s: int) -> None:  # type: ignore[type-arg]
        self._redis = redis_client
        self._ttl_s = ttl_s

    async def update(self, msg: TelemetryMessage) -> None:
        """Atomically set sensor:{sensor_id}:latest and area:{area_id}:latest_ts.

        Uses a pipeline so both writes land in a single round-trip.
        """
        sensor_key = f"sensor:{msg.sensor_id}:latest"
        area_key = f"area:{msg.area_id}:latest_ts"

        # model_dump_json gives us compact, validated JSON — cheaper than json.dumps
        payload = msg.model_dump_json()

        async with self._redis.pipeline(transaction=False) as pipe:
            pipe.set(sensor_key, payload, ex=self._ttl_s)
            pipe.set(area_key, msg.ts, ex=self._ttl_s)
            await pipe.execute()

        hot_state_updates_total.inc()
        log.debug(
            "hot_state.updated",
            sensor_id=msg.sensor_id,
            area_id=msg.area_id,
            ts=msg.ts,
        )
