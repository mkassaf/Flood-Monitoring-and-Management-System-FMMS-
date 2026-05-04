"""JWT creation/validation and password hashing for auth-service."""

import uuid
from pathlib import Path

import structlog
from fastapi import HTTPException, status
from jose import JWTError, jwt
from passlib.context import CryptContext

from auth_service.config import settings
from auth_service.models import UserInfo

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

_ALGORITHM = "RS256"

# Loaded once on startup; accessed by load_keys() below.
_private_key: str = ""
_public_key: str = ""

_pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")


def load_keys() -> None:
    """Read RSA PEM files from paths declared in settings.

    Called from the application lifespan so keys are loaded exactly once.
    Raises RuntimeError if the files cannot be read — this prevents the service
    from starting without valid key material.
    """
    global _private_key, _public_key  # noqa: PLW0603

    priv_path = Path(settings.JWT_PRIVATE_KEY_PATH)
    pub_path = Path(settings.JWT_PUBLIC_KEY_PATH)

    if not priv_path.is_file():
        raise RuntimeError(f"JWT private key not found at {priv_path}")
    if not pub_path.is_file():
        raise RuntimeError(f"JWT public key not found at {pub_path}")

    _private_key = priv_path.read_text(encoding="utf-8")
    _public_key = pub_path.read_text(encoding="utf-8")
    log.info("jwt_keys_loaded")


def _build_claims(user: UserInfo, jti: str, ttl_s: int) -> dict[str, object]:
    """Assemble a JWT claims dict (without signing)."""
    import time

    now = int(time.time())
    return {
        "sub": user.user_id,
        "email": user.email,
        "role": user.role,
        "jurisdiction": user.jurisdiction,
        "jti": jti,
        "iat": now,
        "exp": now + ttl_s,
    }


def create_access_token(user: UserInfo) -> str:
    """Create a short-lived RS256 access token.  jti is generated internally."""
    jti = str(uuid.uuid4())
    claims = _build_claims(user, jti, settings.JWT_ACCESS_TTL_S)
    return jwt.encode(claims, _private_key, algorithm=_ALGORITHM)  # type: ignore[no-any-return]


def create_refresh_token(user: UserInfo, jti: uuid.UUID) -> str:
    """Create a long-lived RS256 refresh token with the given jti.

    The caller must persist the jti in the refresh_token table before returning
    the token to the client.
    """
    claims = _build_claims(user, str(jti), settings.JWT_REFRESH_TTL_S)
    return jwt.encode(claims, _private_key, algorithm=_ALGORITHM)  # type: ignore[no-any-return]


def decode_token(token: str) -> dict[str, object]:
    """Verify and decode a JWT.  Raises HTTP 401 on any failure."""
    try:
        payload: dict[str, object] = jwt.decode(token, _public_key, algorithms=[_ALGORITHM])
    except JWTError as exc:
        log.warning("jwt_decode_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    return payload


def hash_password(plaintext: str) -> str:
    """Hash a plaintext password with argon2id via passlib."""
    return _pwd_context.hash(plaintext)  # type: ignore[no-any-return]


def verify_password(plaintext: str, hashed: str) -> bool:
    """Return True if *plaintext* matches *hashed*, False otherwise."""
    return _pwd_context.verify(plaintext, hashed)  # type: ignore[no-any-return]
