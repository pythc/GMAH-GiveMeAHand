"""Authentication routes: login, user info, API key management."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from agent_workflow.security.auth import (
    AuthSettings,
    AuthUser,
    create_access_token,
    generate_api_key,
    get_current_user,
    require_role,
)

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    """Login request body."""

    username: str
    password: str


class LoginResponse(BaseModel):
    """Login response with access token."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int


class ApiKeyResponse(BaseModel):
    """Response when generating a new API key."""

    api_key: str
    message: str = "Store this key securely. It cannot be retrieved again."


def _get_auth_settings(request: Request) -> AuthSettings:
    return request.app.state.auth_settings  # type: ignore[no-any-return]


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest, request: Request) -> LoginResponse:
    """Authenticate with username/password and receive a JWT token."""
    settings = _get_auth_settings(request)

    if body.username != settings.admin_username or body.password != settings.admin_password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    token = create_access_token(
        subject=body.username,
        settings=settings,
        role="admin",
        scopes=["*"],
    )

    return LoginResponse(
        access_token=token,
        expires_in=settings.jwt_expire_minutes * 60,
    )


@router.get("/me", response_model=AuthUser)
async def me(user: Annotated[AuthUser, Depends(get_current_user)]) -> AuthUser:
    """Return the current authenticated user's information."""
    return user


@router.post(
    "/api-keys",
    response_model=ApiKeyResponse,
    dependencies=[Depends(require_role("admin"))],
)
async def create_api_key(request: Request) -> ApiKeyResponse:
    """Generate a new API key. Requires admin role."""
    settings = _get_auth_settings(request)
    new_key = generate_api_key()
    settings.api_keys.append(new_key)
    return ApiKeyResponse(api_key=new_key)
