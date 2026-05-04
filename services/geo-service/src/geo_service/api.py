"""HTTP API for geo-service."""

from __future__ import annotations

import hashlib
import secrets

import asyncpg
import structlog
from fastapi import FastAPI, HTTPException, Response, status
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from geo_service.config import settings
from geo_service.db import get_pool
from geo_service.models import (
    Area,
    AreaCreate,
    AreaThreshold,
    AreaThresholdUpsert,
    City,
    CityCreate,
    Region,
    RegionCreate,
    Sensor,
    SensorAreaBinding,
    SensorCreate,
    SensorCreated,
)

log = structlog.get_logger(__name__)

app = FastAPI(title="geo-service", version="0.1.0")


# ─── Utilities ────────────────────────────────────────────────────────────────


def _row_to_dict(record: asyncpg.Record) -> dict[str, object]:
    """Convert an asyncpg Record to a plain dict, stringifying UUIDs."""
    result: dict[str, object] = {}
    for key in record.keys():
        val = record[key]
        # asyncpg returns uuid.UUID objects; convert to str for Pydantic
        result[key] = str(val) if hasattr(val, "hex") else val
    return result


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ─── Infrastructure endpoints ─────────────────────────────────────────────────


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok", "service": settings.service_name}


@app.get("/readyz")
async def readyz() -> dict[str, str]:
    """Readiness probe — verifies Postgres connectivity."""
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
    except Exception as exc:
        log.error("readyz.postgres_unavailable", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="postgres unavailable",
        ) from exc
    return {"status": "ready", "service": settings.service_name}


@app.get("/metrics")
async def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


# ─── Admin: seed / hierarchy creation ────────────────────────────────────────


@app.post("/regions", response_model=Region, status_code=status.HTTP_201_CREATED)
async def create_region(body: RegionCreate) -> Region:
    pool = get_pool()
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO opdb.region (name) VALUES ($1) RETURNING *",
                body.name,
            )
    except asyncpg.UniqueViolationError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Region '{body.name}' already exists.",
        ) from exc
    assert row is not None
    return Region(**_row_to_dict(row))


@app.post("/cities", response_model=City, status_code=status.HTTP_201_CREATED)
async def create_city(body: CityCreate) -> City:
    pool = get_pool()
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO opdb.city (region_id, name)
                VALUES ($1::uuid, $2)
                RETURNING *
                """,
                body.region_id,
                body.name,
            )
    except asyncpg.ForeignKeyViolationError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Region '{body.region_id}' not found.",
        ) from exc
    except asyncpg.UniqueViolationError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"City '{body.name}' already exists in that region.",
        ) from exc
    assert row is not None
    return City(**_row_to_dict(row))


@app.post("/areas", response_model=Area, status_code=status.HTTP_201_CREATED)
async def create_area(body: AreaCreate) -> Area:
    pool = get_pool()
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO opdb.area (city_id, name, risk_profile)
                VALUES ($1::uuid, $2, $3)
                RETURNING *
                """,
                body.city_id,
                body.name,
                body.risk_profile,
            )
    except asyncpg.ForeignKeyViolationError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"City '{body.city_id}' not found.",
        ) from exc
    except asyncpg.UniqueViolationError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Area '{body.name}' already exists in that city.",
        ) from exc
    assert row is not None
    return Area(**_row_to_dict(row))


@app.post("/sensors", response_model=SensorCreated, status_code=status.HTTP_201_CREATED)
async def create_sensor(body: SensorCreate) -> SensorCreated:
    """Create a sensor.

    Generates a cryptographically random token, stores only its SHA-256 hash,
    and returns the plaintext token exactly once in the response.
    """
    token = secrets.token_urlsafe(32)
    token_hash = _hash_token(token)

    pool = get_pool()
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO opdb.sensor (area_id, label, token_hash)
                VALUES ($1::uuid, $2, $3)
                RETURNING *
                """,
                body.area_id,
                body.label,
                token_hash,
            )
    except asyncpg.ForeignKeyViolationError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Area '{body.area_id}' not found.",
        ) from exc
    assert row is not None
    d = _row_to_dict(row)
    return SensorCreated(token=token, **d)


@app.delete("/sensors/{sensor_id}", status_code=status.HTTP_204_NO_CONTENT)
async def decommission_sensor(sensor_id: str) -> None:
    """Set decommissioned_at = now() for the sensor (soft delete)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE opdb.sensor
            SET decommissioned_at = now()
            WHERE sensor_id = $1::uuid
              AND decommissioned_at IS NULL
            """,
            sensor_id,
        )
    # asyncpg returns e.g. "UPDATE 1"
    updated = int(result.split()[-1])
    if updated == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Active sensor '{sensor_id}' not found.",
        )


# ─── Hierarchy queries ────────────────────────────────────────────────────────


@app.get("/areas", response_model=list[Area])
async def list_areas() -> list[Area]:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT area_id, city_id, name, risk_profile, created_at FROM opdb.area ORDER BY name"
        )
    return [Area(**_row_to_dict(r)) for r in rows]


@app.get("/areas/{area_id}", response_model=Area)
async def get_area(area_id: str) -> Area:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT area_id, city_id, name, risk_profile, created_at FROM opdb.area WHERE area_id = $1::uuid",
            area_id,
        )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Area not found.")
    return Area(**_row_to_dict(row))


@app.get("/areas/{area_id}/sensors", response_model=list[Sensor])
async def list_area_sensors(area_id: str) -> list[Sensor]:
    """Return active (not decommissioned) sensors for the given area."""
    pool = get_pool()
    async with pool.acquire() as conn:
        # Confirm area exists first so we return 404 rather than an empty list for unknown areas
        area_exists = await conn.fetchval(
            "SELECT 1 FROM opdb.area WHERE area_id = $1::uuid", area_id
        )
        if area_exists is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Area not found.")
        rows = await conn.fetch(
            """
            SELECT sensor_id, area_id, label, decommissioned_at, created_at
            FROM opdb.sensor
            WHERE area_id = $1::uuid
              AND decommissioned_at IS NULL
            ORDER BY created_at
            """,
            area_id,
        )
    return [Sensor(**_row_to_dict(r)) for r in rows]


@app.get("/sensors/{sensor_id}/area", response_model=SensorAreaBinding)
async def get_sensor_area_binding(sensor_id: str) -> SensorAreaBinding:
    """Hot path used by ingestion-gateway — single indexed query, no extra joins."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT sensor_id, area_id
            FROM opdb.sensor
            WHERE sensor_id = $1::uuid
              AND decommissioned_at IS NULL
            """,
            sensor_id,
        )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Active sensor not found.",
        )
    return SensorAreaBinding(**_row_to_dict(row))


# ─── Threshold management ─────────────────────────────────────────────────────


@app.get("/areas/{area_id}/thresholds", response_model=list[AreaThreshold])
async def list_area_thresholds(area_id: str) -> list[AreaThreshold]:
    pool = get_pool()
    async with pool.acquire() as conn:
        area_exists = await conn.fetchval(
            "SELECT 1 FROM opdb.area WHERE area_id = $1::uuid", area_id
        )
        if area_exists is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Area not found.")
        rows = await conn.fetch(
            """
            SELECT area_id, parameter, warning_lo, warning_hi, critical_lo, critical_hi
            FROM opdb.threshold
            WHERE area_id = $1::uuid
            ORDER BY parameter
            """,
            area_id,
        )
    return [AreaThreshold(**_row_to_dict(r)) for r in rows]


@app.put(
    "/areas/{area_id}/thresholds/{parameter}",
    response_model=AreaThreshold,
)
async def upsert_area_threshold(
    area_id: str,
    parameter: str,
    body: AreaThresholdUpsert,
) -> AreaThreshold:
    """Upsert a threshold record for (area_id, parameter)."""
    pool = get_pool()
    try:
        async with pool.acquire() as conn:
            area_exists = await conn.fetchval(
                "SELECT 1 FROM opdb.area WHERE area_id = $1::uuid", area_id
            )
            if area_exists is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Area not found."
                )
            row = await conn.fetchrow(
                """
                INSERT INTO opdb.threshold (area_id, parameter, warning_lo, warning_hi, critical_lo, critical_hi)
                VALUES ($1::uuid, $2, $3, $4, $5, $6)
                ON CONFLICT (area_id, parameter) DO UPDATE
                    SET warning_lo  = EXCLUDED.warning_lo,
                        warning_hi  = EXCLUDED.warning_hi,
                        critical_lo = EXCLUDED.critical_lo,
                        critical_hi = EXCLUDED.critical_hi
                RETURNING *
                """,
                area_id,
                parameter,
                body.warning_lo,
                body.warning_hi,
                body.critical_lo,
                body.critical_hi,
            )
    except asyncpg.ForeignKeyViolationError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Area not found."
        ) from exc
    assert row is not None
    return AreaThreshold(**_row_to_dict(row))
