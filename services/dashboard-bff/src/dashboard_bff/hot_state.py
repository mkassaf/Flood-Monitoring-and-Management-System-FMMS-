"""Redis hot-state reader for the dashboard BFF."""

from __future__ import annotations

import json
from typing import Any, Optional

import structlog
from redis.asyncio import Redis

log = structlog.get_logger(__name__)


async def get_sensor_latest(redis_client: Redis, sensor_id: str) -> Optional[dict[str, Any]]:  # type: ignore[type-arg]
    raw = await redis_client.get(f"sensor:{sensor_id}:latest")
    if raw is None:
        return None
    try:
        return json.loads(raw)  # type: ignore[no-any-return]
    except Exception:
        return None


async def get_area_summary(
    redis_client: Redis,  # type: ignore[type-arg]
    area_id: str,
    sensor_ids: list[str],
) -> dict[str, Any]:
    """Return aggregated latest readings for all sensors in an area."""
    readings: list[dict[str, Any]] = []
    for sid in sensor_ids:
        data = await get_sensor_latest(redis_client, sid)
        if data:
            readings.append(data)

    if not readings:
        return {"area_id": area_id, "sensor_count": 0, "latest_readings": []}

    # Aggregate: pick max water level, latest ts
    max_water = None
    latest_ts = None
    for r in readings:
        m = r.get("measurements", {})
        wl = m.get("water_level_m")
        if wl is not None:
            max_water = max(max_water, wl) if max_water is not None else wl
        ts = r.get("ingested_at") or r.get("ts")
        if ts and (latest_ts is None or ts > latest_ts):
            latest_ts = ts

    return {
        "area_id": area_id,
        "sensor_count": len(readings),
        "max_water_level_m": max_water,
        "latest_ts": latest_ts,
        "latest_readings": readings[:5],  # cap for payload size
    }
