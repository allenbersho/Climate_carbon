"""Integration tests for LandParcel management, acreage validation, nested farmer routes, and RBAC."""

from fastapi import status
from fastapi.testclient import TestClient

from app.models.user import UserRole


def _create_user_and_login(
    client: TestClient, email: str, role: UserRole
) -> dict[str, str]:
    """Helper to register and login a user with a specific role, returning auth headers."""
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


def _create_test_farmer(
    client: TestClient, headers: dict[str, str], name: str = "Farmer Test"
) -> int:
    """Helper to create an active farmer and return their ID."""
    res = client.post(
        "/api/v1/farmers",
        json={
            "name": name,
            "district": "Mysuru",
            "state": "Karnataka",
            "consent_given": True,
        },
        headers=headers,
    )
    return res.json()["id"]


def test_create_parcel_success(client: TestClient) -> None:
    """Verify field officer can create a land parcel linked to an active farmer."""
    officer_headers = _create_user_and_login(
        client, "officer.parcel1@carbontrack.org", UserRole.FIELD_OFFICER
    )
    farmer_id = _create_test_farmer(client, officer_headers, "Somaiah K")

    payload = {
        "farmer_id": farmer_id,
        "area_acres": 12.5,
        "soil_type": "red_loam",
        "crop": "Millets",
    }
    response = client.post("/api/v1/parcels", json=payload, headers=officer_headers)
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    assert data["farmer_id"] == farmer_id
    assert data["area_acres"] == 12.5
    assert data["soil_type"] == "red_loam"
    assert data["crop"] == "Millets"
    assert data["id"] is not None


def test_create_parcel_area_validation_fails(client: TestClient) -> None:
    """Verify creating a parcel with area_acres <= 0 is rejected with 422."""
    officer_headers = _create_user_and_login(
        client, "officer.parcel2@carbontrack.org", UserRole.FIELD_OFFICER
    )
    farmer_id = _create_test_farmer(client, officer_headers, "Bheema R")

    # Zero area rejected
    res_zero = client.post(
        "/api/v1/parcels",
        json={"farmer_id": farmer_id, "area_acres": 0.0},
        headers=officer_headers,
    )
    assert res_zero.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    # Negative area rejected
    res_neg = client.post(
        "/api/v1/parcels",
        json={"farmer_id": farmer_id, "area_acres": -4.2},
        headers=officer_headers,
    )
    assert res_neg.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_create_parcel_nonexistent_farmer_fails(client: TestClient) -> None:
    """Verify creating a parcel for a non-existent farmer returns 404."""
    officer_headers = _create_user_and_login(
        client, "officer.parcel3@carbontrack.org", UserRole.FIELD_OFFICER
    )

    response = client.post(
        "/api/v1/parcels",
        json={"farmer_id": 99999, "area_acres": 5.0},
        headers=officer_headers,
    )
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_get_parcel_by_id(client: TestClient) -> None:
    """Verify fetching parcel by ID returns 200 OK, and missing parcel returns 404."""
    officer_headers = _create_user_and_login(
        client, "officer.parcel4@carbontrack.org", UserRole.FIELD_OFFICER
    )
    farmer_id = _create_test_farmer(client, officer_headers, "Chennaiah")

    create_res = client.post(
        "/api/v1/parcels",
        json={"farmer_id": farmer_id, "area_acres": 8.0, "crop": "Teak"},
        headers=officer_headers,
    )
    parcel_id = create_res.json()["id"]

    get_res = client.get(f"/api/v1/parcels/{parcel_id}", headers=officer_headers)
    assert get_res.status_code == status.HTTP_200_OK
    assert get_res.json()["area_acres"] == 8.0
    assert get_res.json()["crop"] == "Teak"

    not_found_res = client.get("/api/v1/parcels/77777", headers=officer_headers)
    assert not_found_res.status_code == status.HTTP_404_NOT_FOUND


def test_get_farmer_parcels_nested_endpoint(client: TestClient) -> None:
    """Verify GET /api/v1/farmers/{id}/parcels returns all parcels owned by that farmer."""
    officer_headers = _create_user_and_login(
        client, "officer.parcel5@carbontrack.org", UserRole.FIELD_OFFICER
    )
    farmer_id = _create_test_farmer(client, officer_headers, "Laxmi Bai")

    # Create 3 parcels for this farmer
    client.post(
        "/api/v1/parcels",
        json={"farmer_id": farmer_id, "area_acres": 2.5, "crop": "Paddy"},
        headers=officer_headers,
    )
    client.post(
        "/api/v1/parcels",
        json={"farmer_id": farmer_id, "area_acres": 4.0, "crop": "Mustard"},
        headers=officer_headers,
    )
    client.post(
        "/api/v1/parcels",
        json={"farmer_id": farmer_id, "area_acres": 1.5, "crop": "Pulses"},
        headers=officer_headers,
    )

    nested_res = client.get(
        f"/api/v1/farmers/{farmer_id}/parcels", headers=officer_headers
    )
    assert nested_res.status_code == status.HTTP_200_OK
    parcels = nested_res.json()
    assert len(parcels) == 3
    assert all(p["farmer_id"] == farmer_id for p in parcels)

    # Missing farmer returns 404
    missing_res = client.get("/api/v1/farmers/99999/parcels", headers=officer_headers)
    assert missing_res.status_code == status.HTTP_404_NOT_FOUND


def test_list_parcels_pagination_and_filters(client: TestClient) -> None:
    """Verify paginated listing and filtering by farmer_id, crop, and soil_type."""
    officer_headers = _create_user_and_login(
        client, "officer.parcel6@carbontrack.org", UserRole.FIELD_OFFICER
    )
    farmer1 = _create_test_farmer(client, officer_headers, "Farmer 1")
    farmer2 = _create_test_farmer(client, officer_headers, "Farmer 2")

    client.post(
        "/api/v1/parcels",
        json={
            "farmer_id": farmer1,
            "area_acres": 10.0,
            "crop": "Coffee",
            "soil_type": "laterite",
        },
        headers=officer_headers,
    )
    client.post(
        "/api/v1/parcels",
        json={
            "farmer_id": farmer1,
            "area_acres": 5.0,
            "crop": "Pepper",
            "soil_type": "laterite",
        },
        headers=officer_headers,
    )
    client.post(
        "/api/v1/parcels",
        json={
            "farmer_id": farmer2,
            "area_acres": 20.0,
            "crop": "Coffee",
            "soil_type": "clay",
        },
        headers=officer_headers,
    )

    # Pagination: page_size=2
    paged_res = client.get(
        "/api/v1/parcels?page=1&page_size=2", headers=officer_headers
    )
    assert paged_res.status_code == status.HTTP_200_OK
    assert paged_res.json()["total"] == 3
    assert len(paged_res.json()["items"]) == 2

    # Filter by farmer_id
    farmer1_res = client.get(
        f"/api/v1/parcels?farmer_id={farmer1}", headers=officer_headers
    )
    assert farmer1_res.status_code == status.HTTP_200_OK
    assert farmer1_res.json()["total"] == 2

    # Filter by crop="Coffee"
    crop_res = client.get("/api/v1/parcels?crop=coffee", headers=officer_headers)
    assert crop_res.status_code == status.HTTP_200_OK
    assert crop_res.json()["total"] == 2


def test_update_and_delete_parcel(client: TestClient) -> None:
    """Verify partial updates by officer and deletion by administrator."""
    admin_headers = _create_user_and_login(
        client, "super.admin@carbontrack.org", UserRole.ADMIN
    )
    officer_headers = _create_user_and_login(
        client, "officer.parcel7@carbontrack.org", UserRole.FIELD_OFFICER
    )
    farmer_id = _create_test_farmer(client, admin_headers, "Kallappa")

    create_res = client.post(
        "/api/v1/parcels",
        json={"farmer_id": farmer_id, "area_acres": 6.0, "crop": "Cotton"},
        headers=officer_headers,
    )
    parcel_id = create_res.json()["id"]

    # Officer updates parcel
    update_res = client.patch(
        f"/api/v1/parcels/{parcel_id}",
        json={"area_acres": 7.5, "crop": "Organic Cotton"},
        headers=officer_headers,
    )
    assert update_res.status_code == status.HTTP_200_OK
    assert update_res.json()["area_acres"] == 7.5
    assert update_res.json()["crop"] == "Organic Cotton"

    # Admin deletes parcel -> 204
    del_res = client.delete(f"/api/v1/parcels/{parcel_id}", headers=admin_headers)
    assert del_res.status_code == status.HTTP_204_NO_CONTENT

    # Verification: parcel is gone -> 404
    assert (
        client.get(f"/api/v1/parcels/{parcel_id}", headers=admin_headers).status_code
        == status.HTTP_404_NOT_FOUND
    )


def test_parcel_role_permissions(client: TestClient) -> None:
    """Verify RBAC: Verifiers cannot write, Officers cannot delete."""
    admin_headers = _create_user_and_login(
        client, "super.admin@carbontrack.org", UserRole.ADMIN
    )
    officer_headers = _create_user_and_login(
        client, "officer.rbac_p@carbontrack.org", UserRole.FIELD_OFFICER
    )
    verifier_headers = _create_user_and_login(
        client, "verifier.rbac_p@carbontrack.org", UserRole.VERIFIER
    )
    farmer_id = _create_test_farmer(client, admin_headers, "Parvati Amma")

    # 1. Officer creates parcel -> 201
    create_res = client.post(
        "/api/v1/parcels",
        json={"farmer_id": farmer_id, "area_acres": 10.0},
        headers=officer_headers,
    )
    assert create_res.status_code == status.HTTP_201_CREATED
    parcel_id = create_res.json()["id"]

    # 2. Verifier can read -> 200
    assert (
        client.get(f"/api/v1/parcels/{parcel_id}", headers=verifier_headers).status_code
        == status.HTTP_200_OK
    )

    # 3. Verifier CANNOT create parcel -> 403 Forbidden
    ver_create = client.post(
        "/api/v1/parcels",
        json={"farmer_id": farmer_id, "area_acres": 5.0},
        headers=verifier_headers,
    )
    assert ver_create.status_code == status.HTTP_403_FORBIDDEN

    # 4. Officer CANNOT delete parcel -> 403 Forbidden
    officer_del = client.delete(f"/api/v1/parcels/{parcel_id}", headers=officer_headers)
    assert officer_del.status_code == status.HTTP_403_FORBIDDEN

    # 5. Unauthenticated request -> 401
    assert client.get("/api/v1/parcels").status_code == status.HTTP_401_UNAUTHORIZED
