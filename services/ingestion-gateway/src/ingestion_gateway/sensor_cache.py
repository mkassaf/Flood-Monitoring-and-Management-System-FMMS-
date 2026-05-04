"""In-memory sensor→area cache backed by Postgres, with configurable TTL."""

import time
from typing import Optional

import asyncpg
import structlog

log = structlog.get_logger(__name__)

# Sentinel to distinguish "we cached a miss" from "never looked up"
_MISS = object()


class _CacheEntry:
    __slots__ = ("value", "expires_at")

    def __init__(self, value: Optional[str], ttl_s: int) -> None:
        self.value = value  # area_id string or None (for known-missing sensors)
        self.expires_at = time.monotonic() + ttl_s


class SensorCache:
    """Thread-safe (single asyncio event loop) cache mapping sensor_id→area_id.

    Both positive hits and negative misses are cached for ``ttl_s`` seconds so
    that bursts of unknown sensor IDs don't hammer Postgres.
    """

    def __init__(self, pool: asyncpg.Pool, ttl_s: int) -> None:
        self._pool = pool
        self._ttl_s = ttl_s
        self._store: dict[str, _CacheEntry] = {}

    async def get_area_id(self, sensor_id: str) -> Optional[str]:
        """Return the area_id for an active sensor, or None if unknown/decommissioned.

        Results are cached (positive and negative) for ``self._ttl_s`` seconds.
        """
        now = time.monotonic()
        entry = self._store.get(sensor_id)
        if entry is not None and entry.expires_at > now:
            return entry.value  # type: ignore[return-value]  # value is Optional[str]

        area_id = await self._fetch_from_db(sensor_id)
        self._store[sensor_id] = _CacheEntry(area_id, self._ttl_s)

        if area_id is None:
            log.debug("sensor_cache.miss", sensor_id=sensor_id)
        else:
            log.debug("sensor_cache.hit", sensor_id=sensor_id, area_id=area_id)

        return area_id

    async def _fetch_from_db(self, sensor_id: str) -> Optional[str]:
        """Query Postgres for an active sensor; returns area_id or None."""
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT area_id::text
                    FROM opdb.sensor
                    WHERE sensor_id = $1::uuid
                      AND decommissioned_at IS NULL
                    """,
                    sensor_id,
                )
            return str(row["area_id"]) if row else None
        except Exception:
            log.exception("sensor_cache.db_error", sensor_id=sensor_id)
            # Do not cache DB errors — let the next call retry.
            return None
