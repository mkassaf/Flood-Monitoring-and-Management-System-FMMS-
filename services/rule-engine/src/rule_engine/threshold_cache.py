"""In-memory TTL cache for area thresholds fetched from the geo-service.

Cache entries expire after `ttl_s` seconds. On geo-service failure we log a
warning and return an empty list — the rule engine fails open (no false
positives) rather than blocking the alert path.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import httpx
import structlog

from rule_engine.metrics import THRESHOLD_CACHE_HITS, THRESHOLD_CACHE_MISSES
from rule_engine.models import AreaThreshold

log = structlog.get_logger(__name__)


@dataclass
class _CacheEntry:
    thresholds: list[AreaThreshold]
    expires_at: float  # monotonic time


class ThresholdCache:
    """Thread-safe (asyncio-safe) TTL cache for geo-service threshold data."""

    def __init__(
        self,
        geo_service_url: str,
        ttl_s: int,
        http_client: httpx.AsyncClient,
    ) -> None:
        self._geo_url = geo_service_url.rstrip("/")
        self._ttl_s = ttl_s
        self._client = http_client
        self._store: dict[str, _CacheEntry] = {}

    async def get_thresholds(self, area_id: str) -> list[AreaThreshold]:
        """Return thresholds for *area_id*, fetching from geo-service if stale."""
        entry = self._store.get(area_id)
        if entry is not None and time.monotonic() < entry.expires_at:
            THRESHOLD_CACHE_HITS.inc()
            return entry.thresholds

        THRESHOLD_CACHE_MISSES.inc()
        thresholds = await self._fetch(area_id)
        self._store[area_id] = _CacheEntry(
            thresholds=thresholds,
            expires_at=time.monotonic() + self._ttl_s,
        )
        return thresholds

    async def invalidate(self, area_id: str) -> None:
        """Remove a cached entry so the next call re-fetches from geo-service."""
        self._store.pop(area_id, None)

    async def _fetch(self, area_id: str) -> list[AreaThreshold]:
        url = f"{self._geo_url}/areas/{area_id}/thresholds"
        try:
            resp = await self._client.get(url, timeout=5.0)
            resp.raise_for_status()
            raw: list[dict[str, object]] = resp.json()
            thresholds = [AreaThreshold.model_validate(item) for item in raw]
            log.debug(
                "threshold_cache.fetched",
                area_id=area_id,
                count=len(thresholds),
            )
            return thresholds
        except httpx.HTTPStatusError as exc:
            log.warning(
                "threshold_cache.http_error",
                area_id=area_id,
                status=exc.response.status_code,
            )
        except httpx.RequestError as exc:
            log.warning(
                "threshold_cache.request_error",
                area_id=area_id,
                error=str(exc),
            )
        # Fail open — return empty list; no threshold checks this cycle
        return []
