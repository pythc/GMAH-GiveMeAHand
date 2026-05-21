"""JWT and API Key authentication for the Agent Workflow API."""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel


@dataclass
class AuthSettings:
    """Authentication configuration."""

    jwt_secret_key: str = "agent-workflow-dev-secret-change-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24
    api_keys: list[str] = field(default_factory=list)
    enabled: bool = False
    admin_username: str = "admin"
    admin_password: str = "admin"


class AuthUser(BaseModel):
    """Authenticated user model."""

    user_id: str
    role: str = "user"  # "admin" or "user"
    scopes: list[str] = []


# Public paths that do not require authentication
PUBLIC_PATHS: set[str] = {"/healthz", "/auth/login", "/docs", "/openapi.json", "/redoc"}
AUTH_PUBLIC_PATHS = PUBLIC_PATHS


def create_access_token(
    subject: str,
    settings: AuthSettings,
    expires_delta: timedelta | None = None,
    role: str = "user",
    scopes: list[str] | None = None,
) -> str:
    """Create a signed JWT access token."""
    now = datetime.now(UTC)
    expire = now + (expires_delta or timedelta(minutes=settings.jwt_expire_minutes))
    payload: dict[str, object] = {
        "sub": subject,
        "exp": expire,
        "iat": now,
        "role": role,
        "scopes": scopes or [],
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def verify_token(token: str, settings: AuthSettings) -> dict[str, object]:
    """Decode and verify a JWT token. Raises HTTPException on failure."""
    try:
        payload: dict[str, object] = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        return payload
    except jwt.ExpiredSignatureError as err:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        ) from err
    except jwt.InvalidTokenError as err:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from err


def generate_api_key() -> str:
    """Generate a cryptographically secure API key."""
    return f"aw-{secrets.token_urlsafe(32)}"


# FastAPI security schemes
_bearer_scheme = HTTPBearer(auto_error=False)
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def _get_auth_settings_from_request(request: Request) -> AuthSettings:
    """Extract AuthSettings stored on app state."""
    return request.app.state.auth_settings  # type: ignore[no-any-return]


async def get_current_user(
    request: Request,
    bearer: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)] = None,
    api_key: Annotated[str | None, Depends(_api_key_header)] = None,
) -> AuthUser:
    """FastAPI dependency: resolve the authenticated user from JWT or API Key.

    Skips authentication for public paths or when auth is disabled.
    """
    settings: AuthSettings = _get_auth_settings_from_request(request)

    # If auth is disabled, return a default admin user
    if not settings.enabled:
        return AuthUser(user_id="anonymous", role="admin", scopes=["*"])

    # Public paths bypass authentication
    if request.url.path in PUBLIC_PATHS:
        return AuthUser(user_id="anonymous", role="user", scopes=[])

    # Try X-API-Key header first
    if api_key and api_key in settings.api_keys:
        return AuthUser(user_id="api-key-user", role="admin", scopes=["*"])

    # Try Bearer token (could be JWT or API key)
    if bearer:
        token = bearer.credentials
        # Check if the bearer token is actually an API key
        if token in settings.api_keys:
            return AuthUser(user_id="api-key-user", role="admin", scopes=["*"])
        # Otherwise treat as JWT
        payload = verify_token(token, settings)
        return AuthUser(
            user_id=str(payload.get("sub", "")),
            role=str(payload.get("role", "user")),
            scopes=list(payload.get("scopes", [])),  # type: ignore[arg-type]
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_role(role: str):
    """Return a dependency that enforces a minimum role."""

    async def _check(user: Annotated[AuthUser, Depends(get_current_user)]) -> AuthUser:
        if user.role != role and user.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{role}' required",
            )
        return user

    return _check
