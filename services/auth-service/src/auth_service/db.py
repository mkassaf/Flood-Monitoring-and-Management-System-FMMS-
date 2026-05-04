"""asyncpg connection pool management."""

from collections.abc import AsyncGenerator
from typing import Any

import asyncpg
import structlog
from fastapi import Request

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


async def create_pool(dsn: str) -> asyncpg.Pool:  # type: ignore[type-arg]
    """Create and return an asyncpg connection pool."""
    pool: asyncpg.Pool[Any] = await asyncpg.create_pool(dsn=dsn, min_size=2, max_size=10)
    log.info("db_pool_created")
    return pool


async def close_pool(pool: asyncpg.Pool) -> None:  # type: ignore[type-arg]
    """Close an asyncpg connection pool."""
    await pool.close()
    log.info("db_pool_closed")


async def get_pool(request: Request) -> AsyncGenerator[asyncpg.Pool, None]:  # type: ignore[type-arg]
    """FastAPI dependency that yields the shared connection pool."""
    pool: asyncpg.Pool[Any] = request.app.state.db_pool  # type: ignore[assignment]
    yield pool
