"""Entry point for the geo-service service."""

from __future__ import annotations

from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

import structlog
import uvicorn
from fastapi import FastAPI

from geo_service.config import settings
from geo_service.db import close_pool, create_pool

log = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator[None, None]:
    """Manage startup and shutdown of shared resources."""
    pool = await create_pool()
    application.state.db_pool = pool
    log.info("geo_service.startup.complete")
    try:
        yield
    finally:
        await close_pool()
        log.info("geo_service.shutdown.complete")


def _build_app() -> FastAPI:
    """Import the app and attach the lifespan handler."""
    # Import after lifespan is defined to avoid circular imports
    from geo_service.api import app  # noqa: PLC0415

    app.router.lifespan_context = lifespan
    return app


def main() -> None:
    application = _build_app()
    uvicorn.run(
        application,
        host="0.0.0.0",  # noqa: S104 — container binds to all interfaces by design
        port=8000,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
