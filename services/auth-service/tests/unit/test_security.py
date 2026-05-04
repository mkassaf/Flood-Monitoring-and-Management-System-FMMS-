"""Unit tests for auth_service.security."""

import uuid
from unittest.mock import patch

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException

from auth_service.models import UserInfo
from auth_service.security import (
    _ALGORITHM,
    decode_token,
    hash_password,
    verify_password,
)


# ---------------------------------------------------------------------------
# RSA key fixture (generated once per test session — cheap enough)
# ---------------------------------------------------------------------------


def _generate_rsa_key_pair() -> tuple[str, str]:
    """Return (private_pem, public_pem) for a fresh 2048-bit RSA key pair."""
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    return private_pem, public_pem


@pytest.fixture(scope="module")
def rsa_key_pair() -> tuple[str, str]:
    return _generate_rsa_key_pair()


@pytest.fixture()
def sample_user() -> UserInfo:
    return UserInfo(
        user_id=str(uuid.uuid4()),
        email="test@example.com",
        role="area_manager",
        jurisdiction=[str(uuid.uuid4())],
    )


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------


class TestPasswordHashing:
    def test_hash_verify_roundtrip(self) -> None:
        """A hashed password should verify against the original plaintext."""
        plaintext = "SuperSecret123!"
        hashed = hash_password(plaintext)

        assert hashed != plaintext, "Hash must differ from plaintext"
        assert verify_password(plaintext, hashed) is True

    def test_wrong_password_fails_verify(self) -> None:
        """verify_password must return False for an incorrect plaintext."""
        hashed = hash_password("CorrectHorse42")
        assert verify_password("WrongPassword", hashed) is False

    def test_empty_password_hashes_and_verifies(self) -> None:
        """Edge case: empty string password round-trips cleanly."""
        hashed = hash_password("")
        assert verify_password("", hashed) is True
        assert verify_password("notempty", hashed) is False

    def test_hash_is_not_deterministic(self) -> None:
        """argon2 uses a random salt; two hashes of the same input must differ."""
        hashed_a = hash_password("same-input")
        hashed_b = hash_password("same-input")
        assert hashed_a != hashed_b


# ---------------------------------------------------------------------------
# Token creation and decoding
# ---------------------------------------------------------------------------


class TestTokenDecode:
    def test_decode_valid_token(self, rsa_key_pair: tuple[str, str], sample_user: UserInfo) -> None:
        """A token signed with the private key should decode cleanly."""
        private_pem, public_pem = rsa_key_pair
        from jose import jwt

        claims = {
            "sub": sample_user.user_id,
            "email": sample_user.email,
            "role": sample_user.role,
            "jurisdiction": sample_user.jurisdiction,
            "jti": str(uuid.uuid4()),
            "iat": 0,
            "exp": 9_999_999_999,  # far future
        }
        token = jwt.encode(claims, private_pem, algorithm=_ALGORITHM)

        with patch("auth_service.security._public_key", public_pem):
            decoded = decode_token(token)

        assert decoded["sub"] == sample_user.user_id
        assert decoded["email"] == sample_user.email
        assert decoded["role"] == sample_user.role

    def test_decode_expired_token_raises_401(self, rsa_key_pair: tuple[str, str]) -> None:
        """An expired token must raise HTTP 401."""
        private_pem, public_pem = rsa_key_pair
        from jose import jwt

        claims = {
            "sub": "some-user",
            "jti": str(uuid.uuid4()),
            "iat": 1,
            "exp": 1,  # already expired
        }
        token = jwt.encode(claims, private_pem, algorithm=_ALGORITHM)

        with patch("auth_service.security._public_key", public_pem):
            with pytest.raises(HTTPException) as exc_info:
                decode_token(token)

        assert exc_info.value.status_code == 401

    def test_decode_tampered_token_raises_401(self, rsa_key_pair: tuple[str, str]) -> None:
        """A token whose signature has been tampered with must raise HTTP 401."""
        private_pem, public_pem = rsa_key_pair
        other_private_pem, _ = _generate_rsa_key_pair()
        from jose import jwt

        claims = {
            "sub": "some-user",
            "jti": str(uuid.uuid4()),
            "iat": 0,
            "exp": 9_999_999_999,
        }
        # Sign with the *other* private key so verification with the correct
        # public key fails.
        token = jwt.encode(claims, other_private_pem, algorithm=_ALGORITHM)

        with patch("auth_service.security._public_key", public_pem):
            with pytest.raises(HTTPException) as exc_info:
                decode_token(token)

        assert exc_info.value.status_code == 401

    def test_decode_garbage_string_raises_401(self, rsa_key_pair: tuple[str, str]) -> None:
        """An arbitrary string must raise HTTP 401, not crash."""
        _, public_pem = rsa_key_pair
        with patch("auth_service.security._public_key", public_pem):
            with pytest.raises(HTTPException) as exc_info:
                decode_token("this.is.not.a.jwt")

        assert exc_info.value.status_code == 401

    def test_token_claims_include_jurisdiction(
        self, rsa_key_pair: tuple[str, str], sample_user: UserInfo
    ) -> None:
        """Decoded token must include the jurisdiction list."""
        private_pem, public_pem = rsa_key_pair
        from jose import jwt

        jurisdiction = [str(uuid.uuid4()), str(uuid.uuid4())]
        claims = {
            "sub": sample_user.user_id,
            "email": sample_user.email,
            "role": sample_user.role,
            "jurisdiction": jurisdiction,
            "jti": str(uuid.uuid4()),
            "iat": 0,
            "exp": 9_999_999_999,
        }
        token = jwt.encode(claims, private_pem, algorithm=_ALGORITHM)

        with patch("auth_service.security._public_key", public_pem):
            decoded = decode_token(token)

        assert decoded["jurisdiction"] == jurisdiction
