"""Metrics + health surface for the ingestion-gateway worker."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import FastAPI, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from ingestion_gateway.config import settings

# Import counters so they are registered before /metrics is first scraped.
import ingestion_gateway.metrics  # noqa: F401

if TYPE_CHECKING:
    import asyncpg
    from aiokafka import AIOKafkaProducer

app = FastAPI(title="ingestion-gateway", version="0.1.0")

# These are injected by __main__.py after the pool and producer are created.
_producer: AIOKafkaProducer | None = None
_pool: asyncpg.Pool | None = None


def set_readiness_dependencies(
    producer: AIOKafkaProducer,
    pool: asyncpg.Pool,
) -> None:
    """Called from __main__ once the producer and pool are initialised."""
    global _producer, _pool  # noqa: PLW0603
    _producer = producer
    _pool = pool


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "service": settings.service_name}


@app.get("/readyz")
async def readyz() -> Response:
    """Return 200 when both the Kafka producer and Postgres pool are available."""
    problems: list[str] = []

    if _producer is None or not getattr(_producer, "_started", False):
        problems.append("kafka_producer_not_started")

    if _pool is None or _pool.get_size() == 0:
        problems.append("postgres_pool_unavailable")

    if problems:
        body = {"status": "not_ready", "service": settings.service_name, "problems": problems}
        import json

        return Response(
            content=json.dumps(body),
            status_code=503,
            media_type="application/json",
        )

    import json

    return Response(
        content=json.dumps({"status": "ready", "service": settings.service_name}),
        status_code=200,
        media_type="application/json",
    )


@app.get("/metrics")
async def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
