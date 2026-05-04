"""Entry point for the rule-engine worker."""

from __future__ import annotations

import asyncio
import signal

import httpx
import structlog
import uvicorn
from redis.asyncio import Redis

from rule_engine.api import app
from rule_engine.config import settings
from rule_engine.consumer import RuleEngineConsumer
from rule_engine.redundancy_tracker import RedundancyTracker
from rule_engine.threshold_cache import ThresholdCache
from rule_engine.watchdog import SensorWatchdog

log = structlog.get_logger(__name__)


async def main() -> None:
    redis_client: Redis = Redis.from_url(settings.redis_url, decode_responses=True)  # type: ignore[type-arg]
    http_client = httpx.AsyncClient()

    threshold_cache = ThresholdCache(
        geo_service_url=settings.geo_service_url,
        ttl_s=settings.threshold_cache_ttl_s,
        http_client=http_client,
    )
    redundancy_tracker = RedundancyTracker(redis_client=redis_client)
    consumer = RuleEngineConsumer(
        redis_client=redis_client,
        threshold_cache=threshold_cache,
        redundancy_tracker=redundancy_tracker,
    )
    watchdog = SensorWatchdog(redis_client=redis_client, tracker=redundancy_tracker)

    # Metrics / health server
    server_config = uvicorn.Config(
        app, host="0.0.0.0", port=8000, log_level=settings.log_level.lower()  # noqa: S104
    )
    server = uvicorn.Server(server_config)

    stop_event = asyncio.Event()

    def _handle_signal() -> None:
        log.info("rule_engine.shutdown_signal")
        stop_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal)

    log.info("rule_engine.starting")

    tasks = [
        asyncio.create_task(consumer.start(), name="consumer"),
        asyncio.create_task(watchdog.run(), name="watchdog"),
        asyncio.create_task(server.serve(), name="metrics"),
    ]

    try:
        await asyncio.gather(*tasks)
    except Exception:
        log.exception("rule_engine.fatal_error")
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await redis_client.aclose()
        await http_client.aclose()
        log.info("rule_engine.stopped")


if __name__ == "__main__":
    asyncio.run(main())
