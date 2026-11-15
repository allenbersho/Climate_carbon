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


def test_dependency_injection_and_token_edge_cases(client: TestClient, db_session) -> None:
    """Verify get_db generator, inactive user token rejection, and get_current_user_optional edge cases."""
    from app.api.deps import get_current_user, get_current_user_optional, get_db
    from app.core.security import create_access_token
    from app.models.user import User

    # 1. Direct get_db generator
    gen = get_db()
    session = next(gen)
    assert session is not None
    try:
        next(gen)
    except StopIteration:
        pass

    # 2. get_current_user_optional with malformed token
    assert get_current_user_optional(token=None, db=db_session) is None
    assert get_current_user_optional(token="invalid.jwt.token", db=db_session) is None

    # 3. get_current_user with token missing sub or nonexistent user
    token_bad_sub = create_access_token(subject="999999", role=UserRole.FIELD_OFFICER.value)
    from fastapi import HTTPException
    import pytest
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(token=token_bad_sub, db=db_session)
    assert exc_info.value.status_code == 401

    # 4. Inactive user token -> 403 Forbidden
    inactive_user = User(email="inactive@example.com", hashed_password="x", role=UserRole.FIELD_OFFICER, is_active=False)
    db_session.add(inactive_user)
    db_session.commit()
    db_session.refresh(inactive_user)

    inactive_token = create_access_token(subject=str(inactive_user.id), role=UserRole.FIELD_OFFICER.value)
    with pytest.raises(HTTPException) as exc_403:
        get_current_user(token=inactive_token, db=db_session)
    assert exc_403.value.status_code == 403
    assert "inactive" in exc_403.value.detail.lower()


def test_logging_extra_data_and_setup_modes() -> None:
    """Verify JSONFormatter extra_data support and setup_logging text/re-exec modes."""
    from app.core.logging import JSONFormatter, setup_logging

    # 1. JSONFormatter with extra_data and exception info
    formatter = JSONFormatter()
    try:
        raise ValueError("Simulated log exception")
    except ValueError:
        import sys
        exc_info = sys.exc_info()

    record = logging.LogRecord(
        name="test.logger",
        level=logging.ERROR,
        pathname="test.py",
        lineno=10,
        msg="Error with extra",
        args=(),
        exc_info=exc_info,
    )
    record.extra_data = {"tenant_id": 42, "request_id": "abc-123"}
    formatted = formatter.format(record)
    parsed = json.loads(formatted)
    assert parsed["tenant_id"] == 42
    assert parsed["request_id"] == "abc-123"
    assert "exception" in parsed

    # 2. setup_logging modes
    setup_logging(log_level="DEBUG", log_format="text")
    setup_logging(log_level="INFO", log_format="json")


def test_model_repr_methods(db_session) -> None:
    """Verify string representations (__repr__) across domain models."""
    from datetime import date, datetime, timezone
    from app.models.activity import Activity, ActivityType
    from app.models.audit_log import AuditLog
    from app.models.carbon_estimate import CarbonEstimate, EstimateStatus
    from app.models.enrollment import Enrollment, EnrollmentStatus
    from app.models.farmer import Farmer
    from app.models.job import Job, JobStatus
    from app.models.land_parcel import LandParcel
    from app.models.methodology import Methodology
    from app.models.observation import Observation, ObservationType
    from app.models.project import Project, ProjectStatus, ProjectType
    from app.models.user import User
    from app.models.validation_issue import ValidationIssue, ValidationSeverity

    assert "Activity" in repr(Activity(id=1, enrollment_id=1, type=ActivityType.PLANTING, activity_date=date(2026, 1, 1)))
    assert "AuditLog" in repr(AuditLog(id=1, action="CREATE", entity_type="project", entity_id=1, user_email="admin@test.com"))
    assert "CarbonEstimate" in repr(CarbonEstimate(id=1, enrollment_id=1, methodology_version="v1", net_credits=8.5, status=EstimateStatus.DRAFT))
    assert "Enrollment" in repr(Enrollment(id=1, project_id=1, parcel_id=1, status=EnrollmentStatus.ACTIVE))
    assert "Farmer" in repr(Farmer(id=1, name="Ramesh", state="Karnataka"))
    assert "Job" in repr(Job(id=1, job_type="bulk_import", status=JobStatus.COMPLETED))
    assert "LandParcel" in repr(LandParcel(id=1, farmer_id=1, area_acres=5.0))
    assert "Methodology" in repr(Methodology(id=1, name="Afforestation", version="v1"))
    assert "Observation" in repr(Observation(id=1, type=ObservationType.TREE_COUNT, observed_at=datetime.now(timezone.utc), is_baseline=True))
    assert "Project" in repr(Project(id=1, name="Project Alpha", type=ProjectType.AFFORESTATION, status=ProjectStatus.ACTIVE))
    assert "User" in repr(User(id=1, email="test@test.com", role=UserRole.ADMIN, is_active=True))
    assert "ValidationIssue" in repr(ValidationIssue(id=1, observation_id=1, rule="rule_soc_range", severity=ValidationSeverity.ERROR))

