"""Integration tests for asynchronous background jobs and status polling (Task 8.2)."""

import io
from unittest.mock import patch
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.job import JobStatus
from app.models.user import UserRole
from app.services import job_service


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


def test_async_bulk_import_job_lifecycle(client: TestClient) -> None:
    """Verify asynchronous job creation (202), execution in background, and GET /jobs/{id} polling."""
    officer_headers = _create_user_and_login(client, "officer.job1@carbontrack.org", UserRole.FIELD_OFFICER)

    csv_content = (
        "Name, Phone, Village, District, State, Consent\n"
        "Mahadevappa, 9876543220, Belagavi, Belagavi, Karnataka, true\n"
        ", 9876543221, Hubli, Dharwad, Karnataka, true\n"
        "Gangamma, 9876543222, Dharwad, Dharwad, Karnataka, YES\n"
    )

    files = {"file": ("async_farmers.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")}

    # 1. Dispatch asynchronous job -> expect HTTP 202 Accepted
    response = client.post(
        "/api/v1/farmers/bulk-import-async",
        files=files,
        headers=officer_headers,
    )
    assert response.status_code == status.HTTP_202_ACCEPTED
    job_ticket = response.json()
    job_id = job_ticket["id"]

    assert job_ticket["job_type"] == "farmer_bulk_import"
    assert job_ticket["status"] == "pending"
    assert job_ticket["payload"]["filename"] == "async_farmers.csv"

    # 2. Poll job status -> GET /api/v1/jobs/{job_id}
    # TestClient processes BackgroundTasks synchronously before returning
    status_res = client.get(f"/api/v1/jobs/{job_id}", headers=officer_headers)
    assert status_res.status_code == status.HTTP_200_OK
    job_data = status_res.json()

    assert job_data["id"] == job_id
    assert job_data["status"] == "completed"
    assert job_data["started_at"] is not None
    assert job_data["completed_at"] is not None
    assert job_data["error_message"] is None

    # Verify result payload
    result = job_data["result"]
    assert result["total_rows"] == 3
    assert result["imported_count"] == 2
    assert result["failed_count"] == 1
    assert len(result["errors"]) == 1
    assert result["errors"][0]["row_number"] == 3

    # 3. Verify valid farmers exist in database
    farmers_res = client.get("/api/v1/farmers?page_size=50", headers=officer_headers)
    names = [f["name"] for f in farmers_res.json()["items"]]
    assert "Mahadevappa" in names
    assert "Gangamma" in names


def test_get_nonexistent_job_returns_404(client: TestClient) -> None:
    """Verify 404 Not Found when polling a non-existent job ID."""
    admin_headers = _create_user_and_login(client, "super.admin@carbontrack.org", UserRole.ADMIN)
    res = client.get("/api/v1/jobs/999999", headers=admin_headers)
    assert res.status_code == status.HTTP_404_NOT_FOUND
    assert "not found" in res.json()["error"]["message"].lower()


def test_list_jobs_pagination_and_status_filter(client: TestClient) -> None:
    """Verify paginated listing and filtering by job status."""
    officer_headers = _create_user_and_login(client, "officer.job2@carbontrack.org", UserRole.FIELD_OFFICER)

    # Trigger two quick jobs
    csv_1 = "Name,Consent\nFarmerOne,true\n"
    csv_2 = "Name,Consent\nFarmerTwo,true\n"
    client.post("/api/v1/farmers/bulk-import-async", files={"file": ("f1.csv", io.BytesIO(csv_1.encode()), "text/csv")}, headers=officer_headers)
    client.post("/api/v1/farmers/bulk-import-async", files={"file": ("f2.csv", io.BytesIO(csv_2.encode()), "text/csv")}, headers=officer_headers)

    # List jobs
    list_res = client.get("/api/v1/jobs?page=1&page_size=10", headers=officer_headers)
    assert list_res.status_code == status.HTTP_200_OK
    data = list_res.json()
    assert data["total"] >= 2
    assert len(data["items"]) >= 2
    assert data["page"] == 1

    # Filter by completed status
    completed_res = client.get("/api/v1/jobs?status=completed", headers=officer_headers)
    assert completed_res.status_code == status.HTTP_200_OK
    for item in completed_res.json()["items"]:
        assert item["status"] == "completed"


def test_jobs_role_permissions(client: TestClient) -> None:
    """Verify role permissions for async job submission and status polling."""
    admin_headers = _create_user_and_login(client, "super.admin@carbontrack.org", UserRole.ADMIN)
    verifier_headers = _create_user_and_login(client, "verifier.job@carbontrack.org", UserRole.VERIFIER)

    csv_data = "Name,Consent\nRoleFarmer,true\n"
    files = {"file": ("role_test.csv", io.BytesIO(csv_data.encode()), "text/csv")}

    # 1. Unauthenticated -> 401
    unauth = client.get("/api/v1/jobs/1")
    assert unauth.status_code == status.HTTP_401_UNAUTHORIZED

    # 2. Verifier cannot submit async import -> 403 Forbidden
    verif_submit = client.post("/api/v1/farmers/bulk-import-async", files=files, headers=verifier_headers)
    assert verif_submit.status_code == status.HTTP_403_FORBIDDEN

    # 3. Admin submits -> 202 Accepted
    adm_submit = client.post("/api/v1/farmers/bulk-import-async", files=files, headers=admin_headers)
    assert adm_submit.status_code == status.HTTP_202_ACCEPTED
    job_id = adm_submit.json()["id"]

    # 4. Verifier CAN view job status -> 200 OK
    verif_view = client.get(f"/api/v1/jobs/{job_id}", headers=verifier_headers)
    assert verif_view.status_code == status.HTTP_200_OK


def test_job_worker_failure_handling(client: TestClient, db_session: Session) -> None:
    """Verify that worker runtime exceptions set status to FAILED and capture error message."""
    admin_headers = _create_user_and_login(client, "super.admin@carbontrack.org", UserRole.ADMIN)

    # Create job
    job = job_service.create_job(db_session, job_type="failing_task")
    job_id = job.id

    # Mock the bulk import to raise an unhandled exception
    with patch("app.services.job_service.bulk_import_farmers_from_csv", side_effect=RuntimeError("Simulated worker disk failure")):
        job_service.process_farmer_bulk_import_job(job_id, b"dummy content")

    db_session.expire_all()

    # Fetch status
    res = client.get(f"/api/v1/jobs/{job_id}", headers=admin_headers)
    assert res.status_code == status.HTTP_200_OK
    failed_job = res.json()
    assert failed_job["status"] == "failed"
    assert "Simulated worker disk failure" in failed_job["error_message"]
    assert failed_job["completed_at"] is not None
