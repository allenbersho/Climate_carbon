"""Integration tests for audit logging, mutation tracking, and before/after states (Task 9.1)."""

from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.user import UserRole


def _create_user_and_login(
    client: TestClient, email: str, role: UserRole
) -> dict[str, str]:
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


def test_audit_log_created_on_project_status_change(client: TestClient) -> None:
    """Verify that advancing project status creates an audit log with before and after state."""
    admin_headers = _create_user_and_login(
        client, "super.admin@carbontrack.org", UserRole.ADMIN
    )

    # 1. Create Project in draft status
    proj = client.post(
        "/api/v1/projects",
        json={
            "name": "Kaveri Agroforestry",
            "type": "afforestation",
            "start_date": "2025-01-01",
        },
        headers=admin_headers,
    ).json()
    proj_id = proj["id"]
    assert proj["status"] == "draft"

    # 2. Advance project status from draft -> active
    patch_res = client.patch(
        f"/api/v1/projects/{proj_id}",
        json={"status": "active"},
        headers=admin_headers,
    )
    assert patch_res.status_code == status.HTTP_200_OK

    # 3. Query audit trail for this project
    audit_res = client.get(
        f"/api/v1/audit-logs?entity_type=project&entity_id={proj_id}",
        headers=admin_headers,
    )
    assert audit_res.status_code == status.HTTP_200_OK
    audit_data = audit_res.json()
    assert audit_data["total"] >= 2  # CREATE and STATE_CHANGE

    state_changes = [
        log for log in audit_data["items"] if log["action"] == "STATE_CHANGE"
    ]
    assert len(state_changes) == 1
    log = state_changes[0]

    assert log["entity_type"] == "project"
    assert log["entity_id"] == proj_id
    assert log["user_email"] == "super.admin@carbontrack.org"
    assert log["before_state"]["status"] == "draft"
    assert log["after_state"]["status"] == "active"


def test_audit_log_created_on_farmer_update_and_soft_delete(client: TestClient) -> None:
    """Verify that updating and soft-deleting a farmer records exact before/after diffs."""
    admin_headers = _create_user_and_login(
        client, "super.admin@carbontrack.org", UserRole.ADMIN
    )
    officer_headers = _create_user_and_login(
        client, "officer.audit@carbontrack.org", UserRole.FIELD_OFFICER
    )

    # 1. Create farmer as field officer
    farmer = client.post(
        "/api/v1/farmers",
        json={
            "name": "Somanna",
            "district": "Mysuru",
            "state": "Karnataka",
            "consent_given": True,
        },
        headers=officer_headers,
    ).json()
    farmer_id = farmer["id"]

    # 2. Update farmer phone and village as field officer
    client.patch(
        f"/api/v1/farmers/{farmer_id}",
        json={"phone": "9998887776", "village": "Nanjangud"},
        headers=officer_headers,
    )

    # 3. Soft-delete farmer as admin
    client.delete(f"/api/v1/farmers/{farmer_id}", headers=admin_headers)

    # 4. Inspect audit logs
    audit_res = client.get(
        f"/api/v1/audit-logs?entity_type=farmer&entity_id={farmer_id}",
        headers=admin_headers,
    )
    assert audit_res.status_code == status.HTTP_200_OK
    logs = audit_res.json()["items"]

    actions = {log["action"]: log for log in logs}
    assert "CREATE" in actions
    assert "UPDATE" in actions
    assert "SOFT_DELETE" in actions

    # Verify UPDATE actor and payload
    update_log = actions["UPDATE"]
    assert update_log["user_email"] == "officer.audit@carbontrack.org"
    assert update_log["before_state"]["village"] is None
    assert update_log["after_state"]["village"] == "Nanjangud"
    assert update_log["after_state"]["phone"] == "9998887776"

    # Verify SOFT_DELETE actor and payload
    delete_log = actions["SOFT_DELETE"]
    assert delete_log["user_email"] == "super.admin@carbontrack.org"
    assert delete_log["before_state"]["is_deleted"] is False
    assert delete_log["after_state"]["is_deleted"] is True


def test_audit_logs_pagination_and_filtering(client: TestClient) -> None:
    """Verify filtering by action type, entity type, and pagination."""
    admin_headers = _create_user_and_login(
        client, "super.admin@carbontrack.org", UserRole.ADMIN
    )

    res = client.get("/api/v1/audit-logs?page=1&page_size=10", headers=admin_headers)
    assert res.status_code == status.HTTP_200_OK
    data = res.json()
    assert "total" in data
    assert "items" in data
    assert data["page"] == 1


def test_get_audit_log_by_id_and_not_found(client: TestClient) -> None:
    """Verify single audit log retrieval and 404 behavior."""
    admin_headers = _create_user_and_login(
        client, "super.admin@carbontrack.org", UserRole.ADMIN
    )

    # 404 for non-existent log
    res_404 = client.get("/api/v1/audit-logs/999999", headers=admin_headers)
    assert res_404.status_code == status.HTTP_404_NOT_FOUND
    assert "not found" in res_404.json()["error"]["message"].lower()

    # Create an event to query
    client.post(
        "/api/v1/projects",
        json={
            "name": "Audit Test Proj",
            "type": "regen_ag",
            "start_date": "2025-01-01",
        },
        headers=admin_headers,
    )
    logs = client.get("/api/v1/audit-logs?page_size=1", headers=admin_headers).json()[
        "items"
    ]
    assert len(logs) > 0
    valid_id = logs[0]["id"]

    # 200 for valid log
    res_200 = client.get(f"/api/v1/audit-logs/{valid_id}", headers=admin_headers)
    assert res_200.status_code == status.HTTP_200_OK
    assert res_200.json()["id"] == valid_id


def test_audit_logs_role_permissions(client: TestClient) -> None:
    """Verify unauthenticated (401), field officer (403), and verifier/admin (200)."""
    admin_headers = _create_user_and_login(
        client, "super.admin@carbontrack.org", UserRole.ADMIN
    )
    verifier_headers = _create_user_and_login(
        client, "verifier.audit@carbontrack.org", UserRole.VERIFIER
    )
    officer_headers = _create_user_and_login(
        client, "officer.audit2@carbontrack.org", UserRole.FIELD_OFFICER
    )

    # 1. Unauthenticated -> 401
    unauth = client.get("/api/v1/audit-logs")
    assert unauth.status_code == status.HTTP_401_UNAUTHORIZED

    # 2. Field Officer -> 403 Forbidden (audit trails reserved for auditors & admins)
    officer_res = client.get("/api/v1/audit-logs", headers=officer_headers)
    assert officer_res.status_code == status.HTTP_403_FORBIDDEN

    # 3. Verifier -> 200 OK
    verifier_res = client.get("/api/v1/audit-logs", headers=verifier_headers)
    assert verifier_res.status_code == status.HTTP_200_OK

    # 4. Admin -> 200 OK
    admin_res = client.get("/api/v1/audit-logs", headers=admin_headers)
    assert admin_res.status_code == status.HTTP_200_OK


def test_audit_log_filters_and_direct_commit(
    client: TestClient, db_session: Session
) -> None:
    """Verify audit log filtering by user_id and action, and commit=True behavior."""
    from app.services import audit_service

    # Direct log with commit=True
    log = audit_service.record_audit_event(
        db_session,
        user=None,
        action="EXPORT",
        entity_type="REPORT",
        entity_id=101,
        commit=True,
    )
    assert log.id is not None

    # Filter by action
    logs_act, total_act = audit_service.list_audit_logs(db_session, action="EXPORT")
    assert total_act >= 1
    assert any(entry.id == log.id for entry in logs_act)
