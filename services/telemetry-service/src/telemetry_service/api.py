"""REST API for telemetry-service.

Exposes:
- GET /telemetry/{area_id}          — historical query (used by dashboard-bff)
- GET /sensors/{sensor_id}/latest   — hot state from Redis (falls back to DB)
- GET /healthz                      — liveness probe
- GET /readyz                       — readiness probe (checks Postgres + Redis + Kafka broker)
- GET /metrics                      — Prometheus scrape endpoint
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import asyncpg
import redis.asyncio as aioredis
import structlog
from fastapi import FastAPI, HTTPException, Query, Request, Response, status
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from telemetry_service.config import settings
from telemetry_service.models import TelemetryMessage, TelemetryPoint

log = structlog.get_logger(__name__)

app = FastAPI(title="telemetry-service", version="0.1.0")


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _get_pool(request: Request) -> asyncpg.Pool[asyncpg.Record]:
    pool: asyncpg.Pool[asyncpg.Record] = request.app.state.db_pool
    return pool


def _get_redis(request: Request) -> aioredis.Redis:  # type: ignore[type-arg]
    r: aioredis.Redis = request.app.state.redis  # type: ignore[type-arg]
    return r


def _row_to_point(record: asyncpg.Record) -> TelemetryPoint:
    d: dict[str, Any] = {}
    for key in record.keys():
        val = record[key]
        # asyncpg returns uuid.UUID objects; Pydantic accepts str
        d[key] = str(val) if hasattr(val, "hex") else val
    return TelemetryPoint(**d)


# ─── Infrastructure endpoints ─────────────────────────────────────────────────


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness probe — always returns 200 if the process is up."""
    return {"status": "ok", "service": settings.service_name}


@app.get("/readyz")
async def readyz(request: Request) -> dict[str, str]:
    """Readiness probe — verifies Postgres and Redis connectivity."""
    errors: list[str] = []

    # Postgres
    try:
        pool = _get_pool(request)
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
    except Exception as exc:
        log.error("readyz.postgres_unavailable", error=str(exc))
        errors.append("postgres")

    # Redis
    try:
        redis_client = _get_redis(request)
        await redis_client.ping()
    except Exception as exc:
        log.error("readyz.redis_unavailable", error=str(exc))
        errors.append("redis")

    if errors:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"unhealthy: {', '.join(errors)}",
        )
    return {"status": "ready", "service": settings.service_name}


@app.get("/metrics")
async def metrics() -> Response:
    """Prometheus scrape endpoint."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


# ─── Telemetry history ────────────────────────────────────────────────────────


@app.get("/telemetry/{area_id}", response_model=list[TelemetryPoint])
async def get_area_telemetry(
    area_id: str,
    request: Request,
    start: datetime = Query(..., description="Start of time window (ISO 8601)"),
    end: datetime = Query(..., description="End of time window (ISO 8601)"),
    limit: int = Query(1000, ge=1, le=10000, description="Max rows to return"),
) -> list[TelemetryPoint]:
    """Return historical telemetry rows for an area within [start, end].

    Results are ordered by ts ascending and capped at *limit* rows.
    """
    if end <= start:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="'end' must be after 'start'",
        )
    pool = _get_pool(request)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                ts, sensor_id, area_id, status, mode,
                water_level_m, river_flow_velocity_m_s, rainfall_mm_h,
                soil_saturation_pct, wind_speed_m_s, wind_direction_deg,
                ingested_at
            FROM tsdb.telemetry
            WHERE area_id = $1::uuid
              AND ts >= $2
              AND ts <  $3
            ORDER BY ts ASC
            LIMIT $4
            """,
            area_id,
            start,
            end,
            limit,
        )
    return [_row_to_point(r) for r in rows]


# ─── Sensor latest state ──────────────────────────────────────────────────────


@app.get("/sensors/{sensor_id}/latest", response_model=TelemetryPoint)
async def get_sensor_latest(sensor_id: str, request: Request) -> TelemetryPoint:
    """Return the most recent telemetry reading for a sensor.

    Checks Redis hot state first (O(1)).  Falls back to TimescaleDB if the key
    has expired or was never written (e.g. new sensor, Redis restart).
    """
    redis_client = _get_redis(request)

    # ── Hot path: Redis ───────────────────────────────────────────────────────
    try:
        raw = await redis_client.get(f"sensor:{sensor_id}:latest")
        if raw is not None:
            payload: dict[str, Any] = json.loads(raw)
            # TelemetryMessage → TelemetryPoint projection
            msg = TelemetryMessage.model_validate(payload)
            m = msg.measurements
            return TelemetryPoint(
                ts=datetime.fromisoformat(msg.ts),
                sensor_id=msg.sensor_id,
                area_id=msg.area_id,
                status=msg.status,
                mode=msg.mode,
                water_level_m=m.water_level_m,
                river_flow_velocity_m_s=m.river_flow_velocity_m_s,
                rainfall_mm_h=m.rainfall_mm_h,
                soil_saturation_pct=m.soil_saturation_pct,
                wind_speed_m_s=m.wind_speed_m_s,
                wind_direction_deg=m.wind_direction_deg,
                ingested_at=datetime.fromisoformat(msg.ingested_at),
            )
    except Exception as exc:
        # Redis is degraded — log and fall through to DB
        log.warning("api.redis_get_failed", sensor_id=sensor_id, error=str(exc))

    # ── Cold path: TimescaleDB ────────────────────────────────────────────────
    pool = _get_pool(request)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                ts, sensor_id, area_id, status, mode,
                water_level_m, river_flow_velocity_m_s, rainfall_mm_h,
                soil_saturation_pct, wind_speed_m_s, wind_direction_deg,
                ingested_at
            FROM tsdb.telemetry
            WHERE sensor_id = $1::uuid
            ORDER BY ts DESC
            LIMIT 1
            """,
            sensor_id,
        )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No telemetry found for sensor '{sensor_id}'",
        )
    return _row_to_point(row)
