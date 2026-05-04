"""asyncpg pool lifecycle and query helpers for the dashboard BFF."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

import asyncpg
import structlog

from dashboard_bff.config import settings

log = structlog.get_logger(__name__)

_pool: asyncpg.Pool | None = None


async def create_pool() -> asyncpg.Pool:
    global _pool
    _pool = await asyncpg.create_pool(
        dsn=settings.POSTGRES_DSN,
        min_size=2,
        max_size=10,
        command_timeout=30,
    )
    log.info("db.pool.ready")
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("Database pool not initialised.")
    return _pool


def _row_to_dict(record: asyncpg.Record) -> dict[str, Any]:
    return {k: (str(v) if hasattr(v, "hex") else v) for k, v in record.items()}


async def get_telemetry(
    pool: asyncpg.Pool,
    area_ids: list[str],
    start: Optional[datetime],
    end: Optional[datetime],
    limit: int = 1000,
) -> list[dict[str, Any]]:
    conditions = ["area_id = ANY($1::uuid[])"]
    params: list[Any] = [area_ids]
    idx = 2
    if start:
        conditions.append(f"ts >= ${idx}")
        params.append(start)
        idx += 1
    if end:
        conditions.append(f"ts <= ${idx}")
        params.append(end)
        idx += 1
    params.extend([limit])
    query = f"""
        SELECT ts, sensor_id, area_id, status, mode,
               water_level_m, river_flow_velocity_m_s, rainfall_mm_h,
               soil_saturation_pct, wind_speed_m_s, wind_direction_deg, ingested_at
        FROM tsdb.telemetry
        WHERE {' AND '.join(conditions)}
        ORDER BY ts DESC
        LIMIT ${idx}
    """
    rows = await pool.fetch(query, *params)
    return [_row_to_dict(r) for r in rows]


async def get_alerts_for_user(
    pool: asyncpg.Pool,
    area_ids: list[str],
    severity: Optional[str],
    acknowledged: Optional[bool],
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    conditions = ["area_id = ANY($1::uuid[])"]
    params: list[Any] = [area_ids]
    idx = 2
    if severity:
        conditions.append(f"severity = ${idx}")
        params.append(severity)
        idx += 1
    if acknowledged is True:
        conditions.append("acknowledged_at IS NOT NULL")
    elif acknowledged is False:
        conditions.append("acknowledged_at IS NULL")
    params.extend([limit, offset])
    query = f"""
        SELECT alert_id, kind, severity, area_id, sensor_id, parameter,
               value, threshold, ts_event, ts_emitted, ts_persisted,
               acknowledged_at, acknowledged_by, ack_reason
        FROM opdb.alert
        WHERE {' AND '.join(conditions)}
        ORDER BY ts_emitted DESC
        LIMIT ${idx} OFFSET ${idx + 1}
    """
    rows = await pool.fetch(query, *params)
    return [_row_to_dict(r) for r in rows]


async def get_areas_for_user(
    pool: asyncpg.Pool,
    area_ids: list[str],
) -> list[dict[str, Any]]:
    rows = await pool.fetch(
        """
        SELECT a.area_id, a.city_id, a.name, a.risk_profile, a.created_at,
               c.region_id,
               COUNT(s.sensor_id) AS sensor_count
        FROM opdb.area a
        JOIN opdb.city c ON a.city_id = c.city_id
        LEFT JOIN opdb.sensor s ON s.area_id = a.area_id AND s.decommissioned_at IS NULL
        WHERE a.area_id = ANY($1::uuid[])
        GROUP BY a.area_id, c.region_id
        ORDER BY a.name
        """,
        area_ids,
    )
    return [_row_to_dict(r) for r in rows]


async def get_area_thresholds(
    pool: asyncpg.Pool,
    area_id: str,
) -> list[dict[str, Any]]:
    rows = await pool.fetch(
        "SELECT * FROM opdb.threshold WHERE area_id = $1::uuid",
        area_id,
    )
    return [_row_to_dict(r) for r in rows]
