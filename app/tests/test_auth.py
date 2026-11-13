"""Integration tests for authentication, user registration, and access control."""

from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.user import UserRole
from app.services import user_service
from scripts.seed_admin import seed_admin


def test_auth_full_lifecycle(client: TestClient) -> None:
    """Verify first user registration, login, profile inspection, and admin-only user creation."""
    # 1. Register the very first user (bootstrapped as admin)
    first_user_payload = {
        "email": "first.admin@carbontrack.org",
        "password": "AdminPassword123!",
        "role": "field_officer",  # Requesting field_officer, but bootstrap promotes to admin
    }
    reg_response = client.post("/api/v1/auth/register", json=first_user_payload)
    assert reg_response.status_code == status.HTTP_201_CREATED
    first_user_data = reg_response.json()
    assert first_user_data["email"] == "first.admin@carbontrack.org"
    assert first_user_data["role"] == UserRole.ADMIN
    assert "hashed_password" not in first_user_data

    # 2. Login as the newly created admin
    login_payload = {
        "email": "first.admin@carbontrack.org",
        "password": "AdminPassword123!",
    }
    login_response = client.post("/api/v1/auth/login", json=login_payload)
    assert login_response.status_code == status.HTTP_200_OK
    token_data = login_response.json()
    assert "access_token" in token_data
    assert token_data["token_type"] == "bearer"
    admin_token = token_data["access_token"]

    # 3. Access /auth/me with Bearer token
    headers = {"Authorization": f"Bearer {admin_token}"}
    me_response = client.get("/api/v1/auth/me", headers=headers)
    assert me_response.status_code == status.HTTP_200_OK
    me_data = me_response.json()
    assert me_data["email"] == "first.admin@carbontrack.org"
    assert me_data["role"] == UserRole.ADMIN

    # 4. Admin registers a secondary user (field officer)
    officer_payload = {
        "email": "field.officer@carbontrack.org",
        "password": "OfficerPassword123!",
        "role": "field_officer",
    }
    officer_reg_response = client.post(
        "/api/v1/auth/register",
        json=officer_payload,
        headers=headers,
    )
    assert officer_reg_response.status_code == status.HTTP_201_CREATED
    officer_data = officer_reg_response.json()
    assert officer_data["email"] == "field.officer@carbontrack.org"
    assert officer_data["role"] == UserRole.FIELD_OFFICER

    # 5. Officer logs in successfully
    officer_login = client.post(
        "/api/v1/auth/login",
        json={"email": "field.officer@carbontrack.org", "password": "OfficerPassword123!"},
    )
    assert officer_login.status_code == status.HTTP_200_OK
    officer_token = officer_login.json()["access_token"]

    # 6. Non-admin (officer) attempting to register a 3rd user is forbidden (403)
    officer_headers = {"Authorization": f"Bearer {officer_token}"}
    forbidden_reg = client.post(
        "/api/v1/auth/register",
        json={"email": "verifier@carbontrack.org", "password": "VerifierPass123!", "role": "verifier"},
        headers=officer_headers,
    )
    assert forbidden_reg.status_code == status.HTTP_403_FORBIDDEN
    assert forbidden_reg.json()["error"]["code"] == "FORBIDDEN"


def test_login_wrong_password(client: TestClient) -> None:
    """Verify login with invalid password returns 401 Unauthorized."""
    # Ensure a user exists
    client.post(
        "/api/v1/auth/register",
        json={"email": "user.test@carbontrack.org", "password": "CorrectPassword123!"},
    )

    response = client.post(
        "/api/v1/auth/login",
        json={"email": "user.test@carbontrack.org", "password": "IncorrectPassword999!"},
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    error_data = response.json()
    assert error_data["error"]["code"] == "UNAUTHENTICATED"
    assert "Incorrect email or password" in error_data["error"]["message"]


def test_login_nonexistent_email(client: TestClient) -> None:
    """Verify login with an unknown email returns 401 Unauthorized."""
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "ghost.user@carbontrack.org", "password": "AnyPassword123!"},
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_register_duplicate_email(client: TestClient) -> None:
    """Verify registering an existing email returns 409 Conflict."""
    # First registration (bootstrapped)
    client.post(
        "/api/v1/auth/register",
        json={"email": "duplicate.target@carbontrack.org", "password": "SecurePassword123!"},
    )

    # Login to obtain admin token
    login_res = client.post(
        "/api/v1/auth/login",
        json={"email": "duplicate.target@carbontrack.org", "password": "SecurePassword123!"},
    )
    token = login_res.json()["access_token"]

    # Attempt to register the exact same email again
    dup_response = client.post(
        "/api/v1/auth/register",
        json={"email": "duplicate.target@carbontrack.org", "password": "AnotherPassword123!"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert dup_response.status_code == status.HTTP_409_CONFLICT
    error_data = dup_response.json()
    assert error_data["error"]["code"] == "CONFLICT"
    assert "already exists" in error_data["error"]["message"]


def test_get_me_unauthenticated(client: TestClient) -> None:
    """Verify calling /auth/me without Bearer token returns 401 Unauthorized."""
    response = client.get("/api/v1/auth/me")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_seed_admin_script(client: TestClient, db_session: Session) -> None:
    """Verify the seed_admin script creates the admin and can login."""
    # Run seed script targeting the test database session
    seed_admin(db=db_session)

    # Verify admin can log in
    login_res = client.post(
        "/api/v1/auth/login",
        json={"email": settings.FIRST_ADMIN_EMAIL, "password": settings.FIRST_ADMIN_PASSWORD},
    )
    assert login_res.status_code == status.HTTP_200_OK
    assert "access_token" in login_res.json()
