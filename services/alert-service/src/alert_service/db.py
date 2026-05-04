"""asyncpg pool lifecycle + alert persistence helpers."""

from __future__ import annotations

from typing import Any

import asyncpg
import structlog

from alert_service.config import settings
from alert_service.models import Alert

log = structlog.get_logger(__name__)

_pool: asyncpg.Pool[asyncpg.Record] | None = None


# ─── Pool lifecycle ───────────────────────────────────────────────────────────


async def create_pool() -> asyncpg.Pool[asyncpg.Record]:
    """Create the asyncpg connection pool and store it as a module-level singleton."""
    global _pool
    log.info("db.pool.creating", dsn_prefix=settings.POSTGRES_DSN[:30])
    _pool = await asyncpg.create_pool(
        dsn=settings.POSTGRES_DSN,
        min_size=2,
        max_size=10,
        command_timeout=30,
    )
    log.info("db.pool.ready")
    return _pool


async def close_pool() -> None:
    """Close the asyncpg connection pool gracefully."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        log.info("db.pool.closed")


def get_pool() -> asyncpg.Pool[asyncpg.Record]:
    """Return the active connection pool; raises RuntimeError if not initialised."""
    if _pool is None:
        raise RuntimeError("Database pool has not been initialised. Call create_pool() first.")
    return _pool


# ─── Alert helpers ────────────────────────────────────────────────────────────


async def insert_alert(pool: asyncpg.Pool[asyncpg.Record], alert: Alert) -> bool:
    """Insert an alert.  Returns True if the row was new, False if it was a duplicate.

    Deduplication is implemented via ON CONFLICT (alert_id) DO NOTHING so that the
    alert path never raises an exception on replay.
    """
    result: str = await pool.execute(
        """
        INSERT INTO opdb.alert (
            alert_id, kind, severity, area_id, sensor_id, parameter,
            value, threshold, ts_event, ts_emitted, context
        )
        VALUES (
            $1::uuid, $2, $3, $4::uuid, $5::uuid, $6,
            $7, $8, $9, $10, $11::jsonb
        )
        ON CONFLICT (alert_id) DO NOTHING
        """,
        alert.alert_id,
        alert.kind,
        alert.severity,
        alert.area_id,
        alert.sensor_id,  # may be None → NULL
        alert.parameter,  # may be None → NULL
        alert.value,
        alert.threshold,
        alert.ts_event,
        alert.ts_emitted,
        alert.context.model_dump_json(),
    )
    # asyncpg returns e.g. "INSERT 0 1" or "INSERT 0 0"
    inserted = int(result.split()[-1])
    return inserted == 1


async def get_alerts(
    pool: asyncpg.Pool[asyncpg.Record],
    area_ids: list[str] | None,
    severity: str | None,
    acknowledged: bool | None,
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    """Return a filtered, paginated list of alerts as plain dicts."""
    conditions: list[str] = []
    params: list[Any] = []
    idx = 1  # asyncpg uses $1, $2, …

    if area_ids:
        placeholders = ", ".join(f"${i + idx}::uuid" for i in range(len(area_ids)))
        conditions.append(f"area_id IN ({placeholders})")
        params.extend(area_ids)
        idx += len(area_ids)

    if severity is not None:
        conditions.append(f"severity = ${idx}")
        params.append(severity)
        idx += 1

    if acknowledged is True:
        conditions.append("acknowledged_at IS NOT NULL")
    elif acknowledged is False:
        conditions.append("acknowledged_at IS NULL")

    where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    params.extend([limit, offset])
    query = f"""
        SELECT
            alert_id, kind, severity, area_id, sensor_id, parameter,
            value, threshold, ts_event, ts_emitted, ts_persisted,
            acknowledged_at, acknowledged_by, ack_reason
        FROM opdb.alert
        {where_clause}
        ORDER BY ts_emitted DESC
        LIMIT ${idx} OFFSET ${idx + 1}
    """

    rows = await pool.fetch(query, *params)
    return [_row_to_dict(r) for r in rows]


async def get_alert_by_id(
    pool: asyncpg.Pool[asyncpg.Record], alert_id: str
) -> dict[str, Any] | None:
    """Return a single alert dict or None if not found."""
    row = await pool.fetchrow(
        """
        SELECT
            alert_id, kind, severity, area_id, sensor_id, parameter,
            value, threshold, ts_event, ts_emitted, ts_persisted,
            acknowledged_at, acknowledged_by, ack_reason
        FROM opdb.alert
        WHERE alert_id = $1::uuid
        """,
        alert_id,
    )
    return _row_to_dict(row) if row is not None else None


async def acknowledge_alert(
    pool: asyncpg.Pool[asyncpg.Record],
    alert_id: str,
    user_id: str,
    reason: str,
) -> bool:
    """Set acknowledged_at, acknowledged_by, and ack_reason on an alert.

    Returns True if the row was updated (i.e. it existed and was not yet acked),
    False if no row was changed.
    """
    result: str = await pool.execute(
        """
        UPDATE opdb.alert
        SET acknowledged_at  = now(),
            acknowledged_by  = $2,
            ack_reason       = $3
        WHERE alert_id = $1::uuid
          AND acknowledged_at IS NULL
        """,
        alert_id,
        user_id,
        reason,
    )
    updated = int(result.split()[-1])
    return updated == 1


# ─── Utility ──────────────────────────────────────────────────────────────────


def _row_to_dict(record: asyncpg.Record) -> dict[str, Any]:
    """Convert an asyncpg Record to a plain dict, stringifying UUIDs."""
    result: dict[str, Any] = {}
    for key in record.keys():
        val = record[key]
        # asyncpg returns uuid.UUID objects; convert to str for Pydantic
        result[key] = str(val) if hasattr(val, "hex") else val
    return result
