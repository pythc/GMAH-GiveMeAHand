"""Tests for JWT and API Key authentication."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from agent_workflow.api.app import create_app
from agent_workflow.config import AppSettings
from agent_workflow.security.auth import (
    AuthSettings,
    AuthUser,
    create_access_token,
    generate_api_key,
    verify_token,
)


@pytest.fixture()
def auth_settings() -> AuthSettings:
    """Create test AuthSettings with auth enabled."""
    return AuthSettings(
        jwt_secret_key="test-secret-key-for-unit-tests",
        jwt_algorithm="HS256",
        jwt_expire_minutes=60,
        api_keys=["test-api-key-123", "test-api-key-456"],
        enabled=True,
        admin_username="admin",
        admin_password="testpass123",
    )


@pytest.fixture()
def app_settings_auth_enabled() -> AppSettings:
    """AppSettings with auth enabled."""
    return AppSettings(
        auth_enabled=True,
        jwt_secret_key="test-secret-for-integration",  # type: ignore[arg-type]
        admin_username="admin",
        admin_password="testpass123",  # type: ignore[arg-type]
        api_keys="integration-key-1,integration-key-2",
    )


@pytest.fixture()
def app_settings_auth_disabled() -> AppSettings:
    """AppSettings with auth disabled."""
    return AppSettings(
        auth_enabled=False,
        jwt_secret_key="test-secret",  # type: ignore[arg-type]
        admin_username="admin",
        admin_password="admin",  # type: ignore[arg-type]
        api_keys="",
    )


@pytest.fixture()
def client_auth_enabled(app_settings_auth_enabled: AppSettings) -> TestClient:
    """TestClient with auth enabled."""
    app = create_app(settings=app_settings_auth_enabled)
    return TestClient(app)


@pytest.fixture()
def client_auth_disabled(app_settings_auth_disabled: AppSettings) -> TestClient:
    """TestClient with auth disabled."""
    app = create_app(settings=app_settings_auth_disabled)
    return TestClient(app)


# ---------------------------------------------------------------------------
# Unit tests: JWT creation and verification
# ---------------------------------------------------------------------------


class TestJWT:
    """Test JWT token generation and verification."""

    def test_create_access_token(self, auth_settings: AuthSettings) -> None:
        token = create_access_token(subject="user1", settings=auth_settings, role="admin")
        assert isinstance(token, str)
        assert len(token) > 0

    def test_verify_valid_token(self, auth_settings: AuthSettings) -> None:
        token = create_access_token(
            subject="user1", settings=auth_settings, role="user", scopes=["read"]
        )
        payload = verify_token(token, auth_settings)
        assert payload["sub"] == "user1"
        assert payload["role"] == "user"
        assert payload["scopes"] == ["read"]

    def test_verify_expired_token(self, auth_settings: AuthSettings) -> None:
        """An expired token should raise HTTP 401."""
        token = create_access_token(
            subject="user1",
            settings=auth_settings,
            expires_delta=timedelta(seconds=-1),
        )
        with pytest.raises(HTTPException) as exc_info:
            verify_token(token, auth_settings)
        assert exc_info.value.status_code == 401
        assert "expired" in exc_info.value.detail.lower()

    def test_verify_invalid_token(self, auth_settings: AuthSettings) -> None:
        """A malformed token should raise HTTP 401."""
        with pytest.raises(HTTPException) as exc_info:
            verify_token("not.a.valid.token", auth_settings)
        assert exc_info.value.status_code == 401

    def test_verify_wrong_secret(self, auth_settings: AuthSettings) -> None:
        """Token signed with a different secret should fail verification."""
        token = create_access_token(subject="user1", settings=auth_settings)
        wrong_settings = AuthSettings(jwt_secret_key="wrong-secret")

        with pytest.raises(HTTPException) as exc_info:
            verify_token(token, wrong_settings)
        assert exc_info.value.status_code == 401

    def test_custom_expiry(self, auth_settings: AuthSettings) -> None:
        token = create_access_token(
            subject="user1",
            settings=auth_settings,
            expires_delta=timedelta(hours=2),
        )
        payload = verify_token(token, auth_settings)
        assert payload["sub"] == "user1"


class TestApiKeyGeneration:
    """Test API key generation."""

    def test_generate_api_key_format(self) -> None:
        key = generate_api_key()
        assert key.startswith("aw-")
        assert len(key) > 10

    def test_generate_unique_keys(self) -> None:
        keys = {generate_api_key() for _ in range(100)}
        assert len(keys) == 100


class TestAuthUser:
    """Test AuthUser model."""

    def test_default_values(self) -> None:
        user = AuthUser(user_id="test")
        assert user.role == "user"
        assert user.scopes == []

    def test_admin_user(self) -> None:
        user = AuthUser(user_id="admin", role="admin", scopes=["*"])
        assert user.role == "admin"
        assert user.scopes == ["*"]


# ---------------------------------------------------------------------------
# Integration tests: HTTP endpoints
# ---------------------------------------------------------------------------


class TestHealthzNoAuth:
    """Test that /healthz is always accessible."""

    def test_healthz_auth_enabled(self, client_auth_enabled: TestClient) -> None:
        resp = client_auth_enabled.get("/healthz")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"

    def test_healthz_auth_disabled(self, client_auth_disabled: TestClient) -> None:
        resp = client_auth_disabled.get("/healthz")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"


class TestLogin:
    """Test /auth/login endpoint."""

    def test_login_success(self, client_auth_enabled: TestClient) -> None:
        resp = client_auth_enabled.post(
            "/auth/login",
            json={"username": "admin", "password": "testpass123"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["expires_in"] > 0

    def test_login_wrong_password(self, client_auth_enabled: TestClient) -> None:
        resp = client_auth_enabled.post(
            "/auth/login",
            json={"username": "admin", "password": "wrong"},
        )
        assert resp.status_code == 401

    def test_login_wrong_username(self, client_auth_enabled: TestClient) -> None:
        resp = client_auth_enabled.post(
            "/auth/login",
            json={"username": "nobody", "password": "testpass123"},
        )
        assert resp.status_code == 401


class TestApiKeyAuth:
    """Test API Key authentication."""

    def test_api_key_via_header(self, client_auth_enabled: TestClient) -> None:
        resp = client_auth_enabled.get(
            "/auth/me",
            headers={"X-API-Key": "integration-key-1"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["user_id"] == "api-key-user"
        assert data["role"] == "admin"

    def test_api_key_via_bearer(self, client_auth_enabled: TestClient) -> None:
        resp = client_auth_enabled.get(
            "/auth/me",
            headers={"Authorization": "Bearer integration-key-2"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["user_id"] == "api-key-user"

    def test_invalid_api_key_rejected(self, client_auth_enabled: TestClient) -> None:
        resp = client_auth_enabled.get(
            "/auth/me",
            headers={"X-API-Key": "invalid-key"},
        )
        assert resp.status_code == 401


class TestJWTAuth:
    """Test JWT Bearer authentication."""

    def test_jwt_auth_flow(self, client_auth_enabled: TestClient) -> None:
        # Login to get token
        login_resp = client_auth_enabled.post(
            "/auth/login",
            json={"username": "admin", "password": "testpass123"},
        )
        token = login_resp.json()["access_token"]

        # Use token to access protected endpoint
        resp = client_auth_enabled.get(
            "/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["user_id"] == "admin"
        assert data["role"] == "admin"

    def test_no_auth_rejected(self, client_auth_enabled: TestClient) -> None:
        """Request without credentials should be rejected with 401."""
        resp = client_auth_enabled.get("/auth/me")
        assert resp.status_code == 401
        data = resp.json()
        assert "not authenticated" in data["detail"].lower()

    def test_expired_jwt_rejected(
        self, app_settings_auth_enabled: AppSettings, client_auth_enabled: TestClient
    ) -> None:
        """Expired JWT should return 401."""
        auth_s = AuthSettings(
            jwt_secret_key=app_settings_auth_enabled.jwt_secret_key.get_secret_value()
        )
        token = create_access_token(
            subject="user",
            settings=auth_s,
            expires_delta=timedelta(seconds=-1),
        )
        resp = client_auth_enabled.get(
            "/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 401


class TestCreateApiKey:
    """Test POST /auth/api-keys endpoint."""

    def test_admin_can_create_api_key(self, client_auth_enabled: TestClient) -> None:
        """Admin users can generate new API keys."""
        # Login as admin
        login_resp = client_auth_enabled.post(
            "/auth/login",
            json={"username": "admin", "password": "testpass123"},
        )
        token = login_resp.json()["access_token"]

        resp = client_auth_enabled.post(
            "/auth/api-keys",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["api_key"].startswith("aw-")

    def test_unauthenticated_cannot_create_api_key(self, client_auth_enabled: TestClient) -> None:
        """Unauthenticated requests cannot generate API keys."""
        resp = client_auth_enabled.post("/auth/api-keys")
        assert resp.status_code == 401


class TestAuthDisabled:
    """Test behavior when auth is disabled."""

    def test_endpoints_accessible_without_auth(self, client_auth_disabled: TestClient) -> None:
        resp = client_auth_disabled.get("/auth/me")
        assert resp.status_code == 200
        data = resp.json()
        assert data["user_id"] == "anonymous"
        assert data["role"] == "admin"
