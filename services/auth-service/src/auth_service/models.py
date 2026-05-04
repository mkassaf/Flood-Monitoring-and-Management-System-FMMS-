"""Pydantic request/response models for auth-service."""

from pydantic import BaseModel, EmailStr, field_validator

VALID_ROLES = frozenset({"area_manager", "city_manager", "regional_manager"})


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class UserInfo(BaseModel):
    user_id: str
    email: str
    role: str
    jurisdiction: list[str]


class CreateUserRequest(BaseModel):
    email: str
    password: str
    role: str
    jurisdiction: list[str]

    @field_validator("role")
    @classmethod
    def role_must_be_valid(cls, v: str) -> str:
        if v not in VALID_ROLES:
            raise ValueError(f"role must be one of {sorted(VALID_ROLES)}, got {v!r}")
        return v
