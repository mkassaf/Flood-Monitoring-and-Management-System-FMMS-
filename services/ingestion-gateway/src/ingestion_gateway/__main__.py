"""Entry point for the ingestion-gateway worker."""

import asyncio
import logging
import signal

import asyncpg
import structlog
import uvicorn
from aiokafka import AIOKafkaProducer
from codecarbon import EmissionsTracker

from ingestion_gateway.api import app, set_readiness_dependencies
from ingestion_gateway.config import settings
from ingestion_gateway.gateway import Gateway
from ingestion_gateway.sensor_cache import SensorCache

log = structlog.get_logger(__name__)


def _configure_logging() -> None:
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(level),
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer()
            if settings.log_format == "json"
            else structlog.dev.ConsoleRenderer(),
        ],
    )


async def run_gateway(loop: asyncio.AbstractEventLoop) -> None:
    """Create infra connections, wire up the Gateway, and keep it running."""
    pool = await asyncpg.create_pool(settings.postgres_dsn, min_size=2, max_size=10)
    log.info("postgres.pool_created", dsn=settings.postgres_dsn)

    producer = AIOKafkaProducer(
        bootstrap_servers=settings.kafka_bootstrap,
        compression_type="gzip",
        linger_ms=settings.kafka_linger_ms,
        max_batch_size=settings.kafka_batch_size,
    )

    cache = SensorCache(pool=pool, ttl_s=settings.sensor_cache_ttl_s)
    gateway = Gateway(
        config=settings,
        pool=pool,
        producer=producer,
        cache=cache,
        loop=loop,
    )

    # Expose readiness state to the HTTP health endpoint.
    set_readiness_dependencies(producer=producer, pool=pool)

    await gateway.start()
    log.info("ingestion_gateway.running")

    # Block until cancelled (SIGINT / SIGTERM).
    try:
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        pass
    finally:
        log.info("ingestion_gateway.shutting_down")
        await gateway.stop()
        await pool.close()
        log.info("ingestion_gateway.stopped")


async def run_metrics_server() -> None:
    config = uvicorn.Config(
        app,
        host="0.0.0.0",  # noqa: S104
        port=8000,
        log_level=settings.log_level.lower(),
    )
    server = uvicorn.Server(config)
    await server.serve()


async def main() -> None:
    _configure_logging()
    loop = asyncio.get_running_loop()

    tracker = EmissionsTracker(
        project_name=settings.service_name,
        output_dir="/tmp",  # noqa: S108
        log_level="error",
    )
    tracker.start()

    gateway_task = asyncio.create_task(run_gateway(loop))
    metrics_task = asyncio.create_task(run_metrics_server())

    def _handle_signal() -> None:
        log.info("ingestion_gateway.signal_received")
        gateway_task.cancel()
        metrics_task.cancel()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal)

    try:
        await asyncio.gather(gateway_task, metrics_task, return_exceptions=True)
    finally:
        tracker.stop()


if __name__ == "__main__":
    asyncio.run(main())
