"""Entry point for the telemetry-service worker.

Starts three concurrent tasks:
1. BatchWriter.run() — periodic/size-triggered flush to TimescaleDB
2. TelemetryConsumer.start() — Kafka consumer loop
3. uvicorn — FastAPI (health, readyz, metrics, REST API)

All shared resources (asyncpg pool, Redis client) are created here and stored
on app.state so the API handlers can access them via the Request object.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

import asyncpg
import redis.asyncio as aioredis
import structlog
import uvicorn
from fastapi import FastAPI

from telemetry_service.api import app
from telemetry_service.config import settings
from telemetry_service.consumer import TelemetryConsumer
from telemetry_service.hot_state import HotStateUpdater
from telemetry_service.writer import BatchWriter

log = structlog.get_logger(__name__)


# ─── Logging setup ────────────────────────────────────────────────────────────


def _configure_logging() -> None:
    processors: list[structlog.types.Processor]
    if settings.log_format == "json":
        processors = [
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ]
    else:
        processors = [
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ]
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
    )


# ─── Application lifespan ─────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator[None, None]:
    """Create shared resources, wire background tasks, then clean up on exit."""
    _configure_logging()
    log.info("telemetry_service.startup", service=settings.service_name)

    # Asyncpg connection pool
    pool: asyncpg.Pool[asyncpg.Record] = await asyncpg.create_pool(
        dsn=settings.POSTGRES_DSN,
        min_size=2,
        max_size=10,
        command_timeout=30,
    )
    application.state.db_pool = pool
    log.info("telemetry_service.db_pool_ready")

    # Redis client
    redis_client: aioredis.Redis = aioredis.from_url(  # type: ignore[type-arg]
        settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=True,
    )
    application.state.redis = redis_client
    log.info("telemetry_service.redis_ready")

    # Background task handles
    writer = BatchWriter(
        pool=pool,
        batch_interval_s=settings.BATCH_INTERVAL_S,
        batch_max_size=settings.BATCH_MAX_SIZE,
    )
    hot_state = HotStateUpdater(redis_client=redis_client, ttl_s=settings.REDIS_HOT_STATE_TTL_S)
    consumer = TelemetryConsumer()

    writer_task = asyncio.create_task(writer.run(), name="batch-writer")
    consumer_task = asyncio.create_task(
        consumer.start(writer, hot_state), name="kafka-consumer"
    )
    log.info("telemetry_service.background_tasks_started")

    try:
        yield
    finally:
        log.info("telemetry_service.shutting_down")
        writer_task.cancel()
        consumer_task.cancel()
        await asyncio.gather(writer_task, consumer_task, return_exceptions=True)
        await redis_client.aclose()
        await pool.close()
        log.info("telemetry_service.shutdown_complete")


# Attach lifespan to the FastAPI app imported from api.py
app.router.lifespan_context = lifespan


def main() -> None:
    uvicorn.run(
        app,
        host="0.0.0.0",  # noqa: S104 — container binds all interfaces by design
        port=8000,
        log_level=settings.log_level.lower(),
        # Let uvicorn manage the event loop; we hook into lifespan instead
        loop="asyncio",
    )


if __name__ == "__main__":
    main()
