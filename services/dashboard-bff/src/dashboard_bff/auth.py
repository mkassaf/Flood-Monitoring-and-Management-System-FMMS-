"""JWT validation and scope resolution for the dashboard-bff.

Every request must carry a valid RS256 JWT issued by auth-service.  The
`get_current_user` FastAPI dependency validates the token, then resolves the
user's jurisdiction to a concrete list of area_ids (querying Postgres for city-
and region-scoped managers) so that downstream helpers can apply a consistent
``WHERE area_id = ANY($1)`` filter.

Area-id resolution results are cached in-process for ``SCOPE_CACHE_TTL_S``
seconds to avoid hammering Postgres on every request.
"""

from __future__ import annotations

import time
from typing import Any

import asyncpg
import structlog
from fastapi import Depends, Header, HTTPException, status
from jose import ExpiredSignatureError, JWTError, jwt
from pydantic import BaseModel

from dashboard_bff.config import settings
from dashboard_bff.db import get_pool

log = structlog.get_logger(__name__)

# ─── JWT public key ───────────────────────────────────────────────────────────

_jwt_public_key: str | None = None


def load_public_key() -> str:
    """Load and cache the RS256 public key PEM from disk.

    Called once during startup via ``__main__.py``.
    """
    global _jwt_public_key
    with open(settings.JWT_PUBLIC_KEY_PATH) as fh:
        _jwt_public_key = fh.read()
    log.info("auth.public_key.loaded", path=settings.JWT_PUBLIC_KEY_PATH)
    return _jwt_public_key


def get_public_key() -> str:
    """Return the cached public key; raises RuntimeError if not yet loaded."""
    if _jwt_public_key is None:
        raise RuntimeError("JWT public key not loaded. Call load_public_key() first.")
    return _jwt_public_key


# ─── In-process scope cache ───────────────────────────────────────────────────

# key: (user_id, role, tuple(jurisdiction)) → (area_ids, expires_at)
_scope_cache: dict[tuple[str, str, tuple[str, ...]], tuple[list[str], float]] = {}


def _cache_key(user_id: str, role: str, jurisdiction: list[str]) -> tuple[str, str, tuple[str, ...]]:
    return (user_id, role, tuple(sorted(jurisdiction)))


def _get_cached_scope(
    user_id: str, role: str, jurisdiction: list[str]
) -> list[str] | None:
    key = _cache_key(user_id, role, jurisdiction)
    entry = _scope_cache.get(key)
    if entry is None:
        return None
    area_ids, expires_at = entry
    if time.monotonic() > expires_at:
        del _scope_cache[key]
        return None
    return area_ids


def _set_cached_scope(
    user_id: str, role: str, jurisdiction: list[str], area_ids: list[str]
) -> None:
    key = _cache_key(user_id, role, jurisdiction)
    _scope_cache[key] = (area_ids, time.monotonic() + settings.SCOPE_CACHE_TTL_S)


# ─── User context model ───────────────────────────────────────────────────────


class UserContext(BaseModel):
    """Fully resolved user identity, ready for RBAC enforcement in handlers."""

    user_id: str
    email: str
    role: str
    jurisdiction: list[str]
    area_ids: list[str]  # resolved from jurisdiction; used as the RBAC filter


# ─── Scope resolution ─────────────────────────────────────────────────────────


async def _resolve_area_ids(
    role: str,
    jurisdiction: list[str],
    pool: asyncpg.Pool,
) -> list[str]:
    """Translate jurisdiction UUIDs into concrete area_ids based on role.

    - area_manager   → jurisdiction IS area_ids; return as-is.
    - city_manager   → query areas in those cities.
    - regional_manager → query areas in cities in those regions.
    """
    if role == "area_manager":
        return list(jurisdiction)

    if role == "city_manager":
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT area_id FROM opdb.area WHERE city_id = ANY($1::uuid[])",
                jurisdiction,
            )
        return [str(r["area_id"]) for r in rows]

    if role == "regional_manager":
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT a.area_id
                FROM opdb.area a
                JOIN opdb.city c ON a.city_id = c.city_id
                WHERE c.region_id = ANY($1::uuid[])
                """,
                jurisdiction,
            )
        return [str(r["area_id"]) for r in rows]

    log.warning("auth.unknown_role", role=role)
    return []


# ─── FastAPI dependency ───────────────────────────────────────────────────────


async def get_current_user(
    authorization: str = Header(...),
    pool: asyncpg.Pool = Depends(get_pool),
) -> UserContext:
    """Extract, validate, and resolve the JWT into a ``UserContext``.

    Raises HTTP 401 for missing/invalid/expired tokens.
    Raises HTTP 403 if the role is unrecognised or jurisdiction is empty.
    """
    # ── 1. Extract Bearer token ────────────────────────────────────────────────
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        log.warning("auth.missing_bearer_token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header must be 'Bearer <token>'.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # ── 2. Decode + verify JWT with RS256 public key ───────────────────────────
    try:
        public_key = get_public_key()
        claims: dict[str, Any] = jwt.decode(
            token,
            public_key,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except ExpiredSignatureError:
        log.warning("auth.token_expired")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except JWTError as exc:
        log.warning("auth.token_invalid", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id: str = claims.get("sub", "")
    email: str = claims.get("email", "")
    role: str = claims.get("role", "")
    jurisdiction: list[str] = claims.get("jurisdiction", [])

    if not user_id or not role:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing required claims.",
        )

    if role not in {"area_manager", "city_manager", "regional_manager"}:
        log.warning("auth.unknown_role", user_id=user_id, role=role)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Unrecognised role: {role}.",
        )

    # ── 3. Resolve area_ids (with cache) ───────────────────────────────────────
    cached = _get_cached_scope(user_id, role, jurisdiction)
    if cached is not None:
        area_ids = cached
    else:
        area_ids = await _resolve_area_ids(role, jurisdiction, pool)
        _set_cached_scope(user_id, role, jurisdiction, area_ids)

    log.info(
        "auth.user_resolved",
        user_id=user_id,
        role=role,
        area_count=len(area_ids),
    )

    return UserContext(
        user_id=user_id,
        email=email,
        role=role,
        jurisdiction=jurisdiction,
        area_ids=area_ids,
    )


async def get_current_user_ws(
    token: str,
    pool: asyncpg.Pool,
) -> UserContext:
    """Variant of ``get_current_user`` for WebSocket connections.

    WebSocket handshakes cannot use ``Depends``; the token is passed as a
    query parameter and the pool is injected explicitly.

    Raises ValueError on invalid/expired tokens (callers close the WS with
    a 4001 code).
    """
    try:
        public_key = get_public_key()
        claims: dict[str, Any] = jwt.decode(
            token,
            public_key,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except ExpiredSignatureError as exc:
        raise ValueError("Token has expired.") from exc
    except JWTError as exc:
        raise ValueError(f"Invalid token: {exc}") from exc

    user_id: str = claims.get("sub", "")
    email: str = claims.get("email", "")
    role: str = claims.get("role", "")
    jurisdiction: list[str] = claims.get("jurisdiction", [])

    if not user_id or not role:
        raise ValueError("Token missing required claims.")

    if role not in {"area_manager", "city_manager", "regional_manager"}:
        raise ValueError(f"Unrecognised role: {role}.")

    cached = _get_cached_scope(user_id, role, jurisdiction)
    if cached is not None:
        area_ids = cached
    else:
        area_ids = await _resolve_area_ids(role, jurisdiction, pool)
        _set_cached_scope(user_id, role, jurisdiction, area_ids)

    return UserContext(
        user_id=user_id,
        email=email,
        role=role,
        jurisdiction=jurisdiction,
        area_ids=area_ids,
    )
