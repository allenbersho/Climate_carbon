"""Integration tests for security hardening: rate limiting, CORS, structured logging, and global error formats."""

import io
import json
import logging
from unittest.mock import patch
from fastapi import status
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.logging import JSONFormatter
from app.core.rate_limit import SlidingWindowRateLimiter, auth_rate_limiter
from app.main import app
from app.models.user import UserRole


def _create_user_and_login(client: TestClient, email: str, role: UserRole) -> dict[str, str]:
    """Helper to bootstrap an admin, register an actor with a specific role, and return auth headers."""
    client.post(
        "/api/v1/auth/register",
        json={"email": "super.admin@carbontrack.org", "password": "AdminPassword123!"},
    )
    admin_login = client.post(
        "/api/v1/auth/login",
        json={"email": "super.admin@carbontrack.org", "password": "AdminPassword123!"},
    )
    admin_token = admin_login.json()["access_token"]

    if role == UserRole.ADMIN and email == "super.admin@carbontrack.org":
        return {"Authorization": f"Bearer {admin_token}"}

    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "UserPassword123!", "role": role.value},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    user_login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "UserPassword123!"},
    )
    user_token = user_login.json()["access_token"]
    return {"Authorization": f"Bearer {user_token}"}


def test_auth_rate_limiting_enforcement(client: TestClient) -> None:
    """Verify that exceeding login rate limit returns HTTP 429 with standard error structure and Retry-After header."""
    auth_rate_limiter.reset()

    # Rate limit is 10 requests per minute
    for _ in range(10):
        res = client.post(
            "/api/v1/auth/login",
            json={"email": "attacker@example.com", "password": "WrongPassword!"},
        )
        assert res.status_code == status.HTTP_401_UNAUTHORIZED

    # The 11th request must be throttled
    throttled_res = client.post(
        "/api/v1/auth/login",
        json={"email": "attacker@example.com", "password": "WrongPassword!"},
    )
    assert throttled_res.status_code == status.HTTP_429_TOO_MANY_REQUESTS
    data = throttled_res.json()

    assert data["error"]["code"] == "RATE_LIMIT_EXCEEDED"
    assert "rate limit exceeded" in data["error"]["message"].lower()
    assert "retry-after" in throttled_res.headers

    # Reset limiter for subsequent tests
    auth_rate_limiter.reset()


def test_cors_preflight_headers(client: TestClient) -> None:
    """Verify that CORS preflight OPTIONS request returns allowed origins and methods."""
    origin = "http://localhost:3000"
    headers = {
        "Origin": origin,
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "Authorization,Content-Type",
    }

    res = client.options("/api/v1/auth/login", headers=headers)
    assert res.status_code == status.HTTP_200_OK
    assert res.headers.get("access-control-allow-origin") == origin
    assert res.headers.get("access-control-allow-credentials") == "true"


def test_standardized_validation_error_format_422(client: TestClient) -> None:
    """Verify that Pydantic validation errors return standard error structure with details."""
    admin_headers = _create_user_and_login(client, "super.admin@carbontrack.org", UserRole.ADMIN)

    # Missing required 'type' and invalid start_date format
    res = client.post(
        "/api/v1/projects",
        json={"name": "X", "start_date": "not-a-date"},
        headers=admin_headers,
    )
    assert res.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    body = res.json()

    assert "error" in body
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["message"] == "Request validation failed."
    assert isinstance(body["error"]["details"], list)
    assert len(body["error"]["details"]) > 0


def test_unhandled_server_error_500_sanitization() -> None:
    """Verify that unhandled server exceptions return 500 without leaking stack traces or internal details."""
    with TestClient(app, raise_server_exceptions=False) as no_raise_client:
        res = no_raise_client.get("/test-unhandled-error")

    assert res.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    body = res.json()

    assert "error" in body
    assert body["error"]["code"] == "INTERNAL_SERVER_ERROR"
    assert "unexpected internal server error" in body["error"]["message"].lower()
    assert body["error"]["details"] is None

    # Verify sensitive internals are not exposed in response
    assert "RuntimeError" not in res.text
    assert "explosion" not in res.text
    assert "Traceback" not in res.text


def test_structured_json_logging_format() -> None:
    """Verify that JSONFormatter outputs valid JSON with required log fields."""
    formatter = JSONFormatter()
    record = logging.LogRecord(
        name="carbontrack.security",
        level=logging.WARNING,
        pathname="app/core/security.py",
        lineno=42,
        msg="Suspicious rate limit activity detected",
        args=(),
        exc_info=None,
    )
    record.funcName = "check_security"
    record.module = "security"

    formatted = formatter.format(record)
    parsed = json.loads(formatted)

    assert parsed["level"] == "WARNING"
    assert parsed["logger"] == "carbontrack.security"
    assert parsed["message"] == "Suspicious rate limit activity detected"
    assert parsed["module"] == "security"
    assert parsed["function"] == "check_security"
    assert "timestamp" in parsed


def test_max_upload_size_limit_enforcement(client: TestClient) -> None:
    """Verify that files exceeding the maximum allowed size are rejected with HTTP 413."""
    officer_headers = _create_user_and_login(client, "officer.sec@carbontrack.org", UserRole.FIELD_OFFICER)

    # Create dummy payload larger than allowed (simulate 11MB file with mocked setting)
    with patch.object(settings, "MAX_UPLOAD_SIZE_BYTES", 100):
        oversized_data = b"Name,Consent\n" + b"FarmerName,true\n" * 20
        files = {"file": ("massive.csv", io.BytesIO(oversized_data), "text/csv")}

        res = client.post("/api/v1/farmers/bulk-import", files=files, headers=officer_headers)
        assert res.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
        assert res.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"
        assert "upload limit" in res.json()["error"]["message"].lower()
