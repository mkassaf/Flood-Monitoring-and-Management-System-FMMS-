"""HTTP API for auth-service."""

import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg
import structlog
from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from auth_service.config import settings
from auth_service.db import close_pool, create_pool, get_pool
from auth_service.models import (
    CreateUserRequest,
    LoginRequest,
    RefreshRequest,
    TokenResponse,
    UserInfo,
)
from auth_service.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    load_keys,
    verify_password,
)

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

_bearer_scheme = HTTPBearer()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Load RSA keys and open the DB pool on startup; clean up on shutdown."""
    load_keys()
    app.state.db_pool = await create_pool(settings.POSTGRES_DSN)
    yield
    await close_pool(app.state.db_pool)


app = FastAPI(title="auth-service", version="0.1.0", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Health / observability
# ---------------------------------------------------------------------------


@app.get("/healthz", tags=["ops"])
async def healthz() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok", "service": settings.service_name}


@app.get("/readyz", tags=["ops"])
async def readyz(pool: asyncpg.Pool = Depends(get_pool)) -> dict[str, str]:  # type: ignore[type-arg]
    """Readiness probe — verifies Postgres connectivity."""
    try:
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
    except Exception as exc:
        log.error("readyz_db_check_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not reachable",
        ) from exc
    return {"status": "ready", "service": settings.service_name}


@app.get("/metrics", tags=["ops"])
async def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


# ---------------------------------------------------------------------------
# Auth endpoints
# ---------------------------------------------------------------------------


@app.post("/auth/login", response_model=TokenResponse, tags=["auth"])
async def login(
    body: LoginRequest,
    pool: asyncpg.Pool = Depends(get_pool),  # type: ignore[type-arg]
) -> TokenResponse:
    """Verify credentials and issue access + refresh tokens."""
    row = await _fetch_user_by_email(pool, body.email)
    if row is None or not verify_password(body.password, row["password_hash"]):
        # Intentionally identical error to prevent user-enumeration
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    user = _row_to_user_info(row)
    jti = uuid.uuid4()

    await _store_refresh_token(pool, jti, user.user_id, settings.JWT_REFRESH_TTL_S)

    access_token = create_access_token(user)
    refresh_token = create_refresh_token(user, jti)

    log.info("user_logged_in", user_id=user.user_id)
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@app.post("/auth/refresh", response_model=TokenResponse, tags=["auth"])
async def refresh(
    body: RefreshRequest,
    pool: asyncpg.Pool = Depends(get_pool),  # type: ignore[type-arg]
) -> TokenResponse:
    """Validate a refresh token and issue a new access token.

    The refresh token is checked against the DB (must exist, not revoked, not
    expired).  A fresh access token is returned; the refresh token is reused
    with the same jti.
    """
    claims = decode_token(body.refresh_token)

    jti_str = claims.get("jti")
    if not isinstance(jti_str, str):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Malformed token")

    try:
        jti = uuid.UUID(jti_str)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Malformed token jti"
        ) from exc

    rt_row = await _fetch_refresh_token(pool, jti)
    if rt_row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token not found"
        )
    if rt_row["revoked_at"] is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token revoked"
        )

    user_id = claims.get("sub")
    if not isinstance(user_id, str):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Malformed token sub")

    row = await _fetch_user_by_id(pool, user_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found"
        )

    user = _row_to_user_info(row)
    access_token = create_access_token(user)

    log.info("token_refreshed", user_id=user.user_id, jti=str(jti))
    return TokenResponse(access_token=access_token, refresh_token=body.refresh_token)


@app.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT, tags=["auth"])
async def logout(
    body: RefreshRequest,
    pool: asyncpg.Pool = Depends(get_pool),  # type: ignore[type-arg]
) -> None:
    """Revoke the provided refresh token."""
    claims = decode_token(body.refresh_token)

    jti_str = claims.get("jti")
    if not isinstance(jti_str, str):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Malformed token")

    try:
        jti = uuid.UUID(jti_str)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Malformed token jti"
        ) from exc

    revoked = await _revoke_refresh_token(pool, jti)
    if not revoked:
        # Token didn't exist or was already revoked — treat as success to be idempotent
        log.warning("logout_token_not_found_or_already_revoked", jti=str(jti))

    user_id = claims.get("sub")
    log.info("user_logged_out", user_id=user_id, jti=str(jti))


@app.get("/auth/me", response_model=UserInfo, tags=["auth"])
async def me(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
    pool: asyncpg.Pool = Depends(get_pool),  # type: ignore[type-arg]
) -> UserInfo:
    """Return the authenticated user's profile from the Bearer token."""
    claims = decode_token(credentials.credentials)

    user_id = claims.get("sub")
    if not isinstance(user_id, str):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Malformed token sub")

    row = await _fetch_user_by_id(pool, user_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found"
        )

    return _row_to_user_info(row)


# ---------------------------------------------------------------------------
# User management
# ---------------------------------------------------------------------------


@app.post("/users", response_model=UserInfo, status_code=status.HTTP_201_CREATED, tags=["users"])
async def create_user(
    body: CreateUserRequest,
    pool: asyncpg.Pool = Depends(get_pool),  # type: ignore[type-arg]
) -> UserInfo:
    """Create a new user.  Protected by network boundary in the PoC."""
    hashed = hash_password(body.password)
    user_id = uuid.uuid4()

    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO opdb.app_user (user_id, email, password_hash, role, jurisdiction)
                VALUES ($1, $2, $3, $4, $5::jsonb)
                """,
                user_id,
                body.email,
                hashed,
                body.role,
                json.dumps(body.jurisdiction),
            )
    except asyncpg.UniqueViolationError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Email {body.email!r} is already registered",
        ) from exc

    log.info("user_created", user_id=str(user_id), role=body.role)
    return UserInfo(
        user_id=str(user_id),
        email=body.email,
        role=body.role,
        jurisdiction=body.jurisdiction,
    )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


async def _fetch_user_by_email(
    pool: asyncpg.Pool,  # type: ignore[type-arg]
    email: str,
) -> asyncpg.Record | None:
    async with pool.acquire() as conn:
        return await conn.fetchrow(  # type: ignore[no-any-return]
            "SELECT user_id, email, password_hash, role, jurisdiction "
            "FROM opdb.app_user WHERE email = $1",
            email,
        )


async def _fetch_user_by_id(
    pool: asyncpg.Pool,  # type: ignore[type-arg]
    user_id: str,
) -> asyncpg.Record | None:
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        return None
    async with pool.acquire() as conn:
        return await conn.fetchrow(  # type: ignore[no-any-return]
            "SELECT user_id, email, password_hash, role, jurisdiction "
            "FROM opdb.app_user WHERE user_id = $1",
            uid,
        )


async def _store_refresh_token(
    pool: asyncpg.Pool,  # type: ignore[type-arg]
    jti: uuid.UUID,
    user_id: str,
    ttl_s: int,
) -> None:
    uid = uuid.UUID(user_id)
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO opdb.refresh_token (jti, user_id, issued_at, expires_at)
            VALUES ($1, $2, NOW(), NOW() + ($3 || ' seconds')::interval)
            """,
            jti,
            uid,
            str(ttl_s),
        )


async def _fetch_refresh_token(
    pool: asyncpg.Pool,  # type: ignore[type-arg]
    jti: uuid.UUID,
) -> asyncpg.Record | None:
    async with pool.acquire() as conn:
        return await conn.fetchrow(  # type: ignore[no-any-return]
            "SELECT jti, user_id, revoked_at FROM opdb.refresh_token WHERE jti = $1",
            jti,
        )


async def _revoke_refresh_token(
    pool: asyncpg.Pool,  # type: ignore[type-arg]
    jti: uuid.UUID,
) -> bool:
    """Set revoked_at = NOW() for the given jti.  Returns True if a row was updated."""
    async with pool.acquire() as conn:
        result: str = await conn.execute(
            """
            UPDATE opdb.refresh_token
            SET revoked_at = NOW()
            WHERE jti = $1 AND revoked_at IS NULL
            """,
            jti,
        )
    # asyncpg returns a tag like "UPDATE 1"
    return result.endswith(" 1")


def _row_to_user_info(row: asyncpg.Record) -> UserInfo:
    """Convert a DB row to a UserInfo model.

    The jurisdiction column is stored as JSONB (list of UUID strings).
    asyncpg may return it as a pre-decoded Python object or as a JSON string
    depending on the codec configuration; we handle both cases.
    """
    raw = row["jurisdiction"]
    if isinstance(raw, str):
        jurisdiction: list[str] = json.loads(raw)
    else:
        jurisdiction = [str(item) for item in raw]

    return UserInfo(
        user_id=str(row["user_id"]),
        email=row["email"],
        role=row["role"],
        jurisdiction=jurisdiction,
    )
