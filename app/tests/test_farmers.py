"""Integration tests for Farmer endpoints, pagination, filters, soft delete, and RBAC."""

from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.farmer import Farmer
from app.models.user import UserRole


def _create_user_and_login(client: TestClient, email: str, role: UserRole) -> dict[str, str]:
    """Helper to register and login a user with a specific role, returning auth headers."""
    # Register (first user becomes admin, subsequent registered by admin)
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

    # Admin registers target user
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


def test_create_farmer_success(client: TestClient) -> None:
    """Verify field officer can create a farmer when consent_given is True."""
    headers = _create_user_and_login(client, "officer1@carbontrack.org", UserRole.FIELD_OFFICER)

    payload = {
        "name": "Ramesh Kumar",
        "phone": "+91 9876543210",
        "village": "Hunsur",
        "district": "Mysuru",
        "state": "Karnataka",
        "consent_given": True,
    }
    response = client.post("/api/v1/farmers", json=payload, headers=headers)
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    assert data["name"] == "Ramesh Kumar"
    assert data["consent_given"] is True
    assert data["is_deleted"] is False
    assert data["id"] is not None


def test_create_farmer_without_consent_fails(client: TestClient) -> None:
    """Verify creating a farmer with consent_given=False is rejected with 422."""
    headers = _create_user_and_login(client, "officer2@carbontrack.org", UserRole.FIELD_OFFICER)

    payload = {
        "name": "Suresh Patel",
        "phone": "+91 9876543211",
        "consent_given": False,  # Missing consent
    }
    response = client.post("/api/v1/farmers", json=payload, headers=headers)
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_get_farmer_by_id(client: TestClient) -> None:
    """Verify fetching an existing farmer by ID returns 200 OK."""
    headers = _create_user_and_login(client, "officer3@carbontrack.org", UserRole.FIELD_OFFICER)

    create_res = client.post(
        "/api/v1/farmers",
        json={"name": "Anita Devi", "district": "Patna", "state": "Bihar", "consent_given": True},
        headers=headers,
    )
    farmer_id = create_res.json()["id"]

    get_res = client.get(f"/api/v1/farmers/{farmer_id}", headers=headers)
    assert get_res.status_code == status.HTTP_200_OK
    assert get_res.json()["name"] == "Anita Devi"


def test_get_farmer_not_found(client: TestClient) -> None:
    """Verify requesting a non-existent farmer ID returns 404 Not Found."""
    headers = _create_user_and_login(client, "officer4@carbontrack.org", UserRole.FIELD_OFFICER)
    response = client.get("/api/v1/farmers/99999", headers=headers)
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_list_farmers_pagination_and_filters(client: TestClient) -> None:
    """Verify paginated listing, district/state filters, and name substring search."""
    headers = _create_user_and_login(client, "officer5@carbontrack.org", UserRole.FIELD_OFFICER)

    # Seed 4 farmers
    farmers_data = [
        {"name": "Aarav Sharma", "district": "Mysuru", "state": "Karnataka", "consent_given": True},
        {"name": "Bhavna Patel", "district": "Mysuru", "state": "Karnataka", "consent_given": True},
        {"name": "Chirag Joshi", "district": "Mandya", "state": "Karnataka", "consent_given": True},
        {"name": "Deepak Verma", "district": "Pune", "state": "Maharashtra", "consent_given": True},
    ]
    for f in farmers_data:
        client.post("/api/v1/farmers", json=f, headers=headers)

    # Test pagination: page=1, page_size=2
    paged_res = client.get("/api/v1/farmers?page=1&page_size=2", headers=headers)
    assert paged_res.status_code == status.HTTP_200_OK
    paged_data = paged_res.json()
    assert paged_data["total"] == 4
    assert paged_data["page"] == 1
    assert paged_data["page_size"] == 2
    assert len(paged_data["items"]) == 2

    # Test filter by district="Mysuru"
    filter_res = client.get("/api/v1/farmers?district=Mysuru", headers=headers)
    assert filter_res.status_code == status.HTTP_200_OK
    assert filter_res.json()["total"] == 2

    # Test name search substring (case-insensitive "patel")
    search_res = client.get("/api/v1/farmers?search=patel", headers=headers)
    assert search_res.status_code == status.HTTP_200_OK
    assert search_res.json()["total"] == 1
    assert search_res.json()["items"][0]["name"] == "Bhavna Patel"


def test_update_farmer(client: TestClient) -> None:
    """Verify updating farmer phone and location attributes."""
    headers = _create_user_and_login(client, "officer6@carbontrack.org", UserRole.FIELD_OFFICER)

    create_res = client.post(
        "/api/v1/farmers",
        json={"name": "Kavita Rao", "phone": "111", "consent_given": True},
        headers=headers,
    )
    farmer_id = create_res.json()["id"]

    patch_res = client.patch(
        f"/api/v1/farmers/{farmer_id}",
        json={"phone": "9998887776", "village": "New Village"},
        headers=headers,
    )
    assert patch_res.status_code == status.HTTP_200_OK
    updated_data = patch_res.json()
    assert updated_data["phone"] == "9998887776"
    assert updated_data["village"] == "New Village"
    assert updated_data["name"] == "Kavita Rao"


def test_soft_delete_farmer(client: TestClient, db_session: Session) -> None:
    """Verify soft deletion marks is_deleted=True without purging the database row."""
    admin_headers = _create_user_and_login(client, "super.admin@carbontrack.org", UserRole.ADMIN)

    create_res = client.post(
        "/api/v1/farmers",
        json={"name": "Target Delete", "consent_given": True},
        headers=admin_headers,
    )
    farmer_id = create_res.json()["id"]

    # 1. Admin issues DELETE -> 204 No Content
    delete_res = client.delete(f"/api/v1/farmers/{farmer_id}", headers=admin_headers)
    assert delete_res.status_code == status.HTTP_204_NO_CONTENT

    # 2. Subsequent GET returns 404 Not Found
    get_res = client.get(f"/api/v1/farmers/{farmer_id}", headers=admin_headers)
    assert get_res.status_code == status.HTTP_404_NOT_FOUND

    # 3. Excluded from general listing
    list_res = client.get("/api/v1/farmers", headers=admin_headers)
    assert not any(f["id"] == farmer_id for f in list_res.json()["items"])

    # 4. Direct DB verification: row still exists, is_deleted is True!
    farmer_in_db = db_session.get(Farmer, farmer_id)
    assert farmer_in_db is not None
    assert farmer_in_db.is_deleted is True


def test_farmer_role_permissions(client: TestClient) -> None:
    """Verify RBAC: Verifiers can read but cannot write; Officers cannot delete."""
    admin_headers = _create_user_and_login(client, "super.admin@carbontrack.org", UserRole.ADMIN)
    officer_headers = _create_user_and_login(client, "officer.rbac@carbontrack.org", UserRole.FIELD_OFFICER)
    verifier_headers = _create_user_and_login(client, "verifier.rbac@carbontrack.org", UserRole.VERIFIER)

    # 1. Officer can create farmer (201)
    create_res = client.post(
        "/api/v1/farmers",
        json={"name": "RBAC Farmer", "consent_given": True},
        headers=officer_headers,
    )
    assert create_res.status_code == status.HTTP_201_CREATED
    farmer_id = create_res.json()["id"]

    # 2. Verifier can read farmer (200)
    assert client.get(f"/api/v1/farmers/{farmer_id}", headers=verifier_headers).status_code == status.HTTP_200_OK

    # 3. Verifier CANNOT create or update farmer (403 Forbidden)
    create_forbidden = client.post(
        "/api/v1/farmers",
        json={"name": "Verifier Illegally Creates", "consent_given": True},
        headers=verifier_headers,
    )
    assert create_forbidden.status_code == status.HTTP_403_FORBIDDEN

    # 4. Officer CANNOT delete farmer (403 Forbidden)
    delete_forbidden = client.delete(f"/api/v1/farmers/{farmer_id}", headers=officer_headers)
    assert delete_forbidden.status_code == status.HTTP_403_FORBIDDEN

    # 5. Unauthenticated request gets 401
    assert client.get("/api/v1/farmers").status_code == status.HTTP_401_UNAUTHORIZED
