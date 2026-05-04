"""Entry point for the auth-service service."""

import uvicorn

from auth_service.api import app
from auth_service.config import settings


def main() -> None:
    uvicorn.run(
        app,
        host="0.0.0.0",  # noqa: S104 — container binds to all interfaces by design
        port=8000,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
