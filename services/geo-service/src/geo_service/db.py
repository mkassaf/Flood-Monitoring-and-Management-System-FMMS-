"""Asyncpg connection pool lifecycle management."""

from __future__ import annotations

import asyncpg
import structlog

from geo_service.config import settings

log = structlog.get_logger(__name__)

_pool: asyncpg.Pool[asyncpg.Record] | None = None


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
