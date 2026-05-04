"""Entry point for the dashboard-bff."""

from __future__ import annotations

import asyncio
import signal

import structlog
import uvicorn
from redis.asyncio import Redis

from dashboard_bff.api import app
from dashboard_bff.auth import load_public_key
from dashboard_bff.config import settings
from dashboard_bff.db import close_pool, create_pool

log = structlog.get_logger(__name__)


async def main() -> None:
    pool = await create_pool()
    app.state.db_pool = pool  # type: ignore[attr-defined]

    redis_client: Redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)  # type: ignore[type-arg]
    app.state.redis = redis_client  # type: ignore[attr-defined]

    load_public_key()

    server_config = uvicorn.Config(
        app, host="0.0.0.0", port=8000, log_level=settings.log_level.lower()  # noqa: S104
    )
    server = uvicorn.Server(server_config)

    def _handle_signal() -> None:
        log.info("dashboard_bff.shutdown_signal")

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal)

    log.info("dashboard_bff.starting")
    try:
        await server.serve()
    finally:
        await redis_client.aclose()
        await close_pool()
        log.info("dashboard_bff.stopped")


if __name__ == "__main__":
    asyncio.run(main())
