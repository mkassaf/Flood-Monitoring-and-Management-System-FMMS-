"""Entry point for the alert-service."""

from __future__ import annotations

import asyncio
import signal

import structlog
import uvicorn
from redis.asyncio import Redis

from alert_service.api import app
from alert_service.config import settings
from alert_service.consumer import AlertConsumer
from alert_service.db import close_pool, create_pool
from alert_service.publisher import AlertPublisher

log = structlog.get_logger(__name__)


async def main() -> None:
    pool = await create_pool()
    app.state.db_pool = pool  # type: ignore[attr-defined]

    redis_client: Redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)  # type: ignore[type-arg]
    publisher = AlertPublisher(redis_client=redis_client)
    consumer = AlertConsumer(db_pool=pool, publisher=publisher)

    server_config = uvicorn.Config(
        app, host="0.0.0.0", port=8000, log_level=settings.log_level.lower()  # noqa: S104
    )
    server = uvicorn.Server(server_config)

    stop_event = asyncio.Event()

    def _handle_signal() -> None:
        log.info("alert_service.shutdown_signal")
        stop_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal)

    log.info("alert_service.starting")
    tasks = [
        asyncio.create_task(consumer.start(), name="consumer"),
        asyncio.create_task(server.serve(), name="api"),
    ]
    try:
        await asyncio.gather(*tasks)
    except Exception:
        log.exception("alert_service.fatal_error")
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await redis_client.aclose()
        await close_pool()
        log.info("alert_service.stopped")


if __name__ == "__main__":
    asyncio.run(main())
