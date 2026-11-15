"""Integration tests for CSV bulk import of farmers (Task 8.1).

Verifies row-by-row validation, error reporting with row numbers, partial success
handling with messy CSVs, UTF-8 BOM decoding, and role-based access control.
"""

import io

from fastapi import status
from fastapi.testclient import TestClient

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


def test_bulk_import_messy_csv_partial_success(client: TestClient) -> None:
    """Verify that a messy CSV imports valid rows and reports failures without crashing."""
    officer_headers = _create_user_and_login(
        client, "officer.import1@carbontrack.org", UserRole.FIELD_OFFICER
    )

    # Messy CSV fixture:
    # Row 1: Header
    # Row 2: Valid
    # Row 3: Missing name (empty) -> Error
    # Row 4: Explicit false consent -> Error
    # Row 5: Missing consent cell -> Error
    # Row 6: Valid with uppercase 'YES' and whitespace
    # Row 7: Name too short (1 char) -> Error
    # Row 8: Valid with '1' as consent
    # Row 9: Blank line (should be ignored)
    csv_content = (
        "Name, Phone, Village, District, State, Consent\n"
        "Ramesh Kumar, 9876543210, Shivamogga, Shivamogga, Karnataka, true\n"
        ", 9876543211, Bellary, Bellary, Karnataka, true\n"
        "Suresh Gowda, 9876543212, Mandya, Mandya, Karnataka, false\n"
        "Girish Patel, 9876543213, Kolar, Kolar, Karnataka, \n"
        "  Laxmi Devi  , 9876543214, Hassan, Hassan, Karnataka, YES \n"
        "A, 9876543215, Tumkur, Tumkur, Karnataka, 1\n"
        "Basavaraj, 9876543216, Haveri, Haveri, Karnataka, 1\n"
        "   \n"
    )

    files = {
        "file": (
            "farmers_messy.csv",
            io.BytesIO(csv_content.encode("utf-8")),
            "text/csv",
        )
    }
    response = client.post(
        "/api/v1/farmers/bulk-import", files=files, headers=officer_headers
    )

    assert response.status_code == status.HTTP_200_OK
    result = response.json()

    assert result["total_rows"] == 7
    assert result["imported_count"] == 3
    assert result["failed_count"] == 4
    assert len(result["errors"]) == 4

    # Verify individual row error details
    errors_by_row = {err["row_number"]: err for err in result["errors"]}

    # Row 3: missing name
    assert 3 in errors_by_row
    assert "name" in errors_by_row[3]["reason"].lower()

    # Row 4: false consent
    assert 4 in errors_by_row
    assert "consent" in errors_by_row[4]["reason"].lower()

    # Row 5: empty consent
    assert 5 in errors_by_row
    assert "consent" in errors_by_row[5]["reason"].lower()

    # Row 7: name too short
    assert 7 in errors_by_row
    assert "name" in errors_by_row[7]["reason"].lower()

    # Verify that valid farmers were actually persisted in the database
    farmers_res = client.get("/api/v1/farmers?page_size=50", headers=officer_headers)
    assert farmers_res.status_code == status.HTTP_200_OK
    persisted_names = [f["name"] for f in farmers_res.json()["items"]]

    assert "Ramesh Kumar" in persisted_names
    assert "Laxmi Devi" in persisted_names
    assert "Basavaraj" in persisted_names

    # Verify invalid farmers were NOT created
    assert "Suresh Gowda" not in persisted_names
    assert "Girish Patel" not in persisted_names
    assert "A" not in persisted_names


def test_bulk_import_utf8_bom_and_alternative_headers(client: TestClient) -> None:
    """Verify that CSVs exported from Excel with UTF-8 BOM and aliased headers work cleanly."""
    officer_headers = _create_user_and_login(
        client, "officer.import2@carbontrack.org", UserRole.FIELD_OFFICER
    )

    # Excel often adds a UTF-8 Byte Order Mark (\xef\xbb\xbf)
    csv_bytes = (
        b"\xef\xbb\xbfFarmer Name,Contact,Village,District,State,Farmer Consent\n"
        b"Anand Hegde,9123456780,Sirsi,Uttara Kannada,Karnataka,true\n"
        b"Parvati Bai,9123456781,Kumta,Uttara Kannada,Karnataka,yes\n"
    )

    files = {"file": ("excel_export.csv", io.BytesIO(csv_bytes), "text/csv")}
    response = client.post(
        "/api/v1/farmers/bulk-import", files=files, headers=officer_headers
    )

    assert response.status_code == status.HTTP_200_OK
    result = response.json()
    assert result["total_rows"] == 2
    assert result["imported_count"] == 2
    assert result["failed_count"] == 0
    assert result["errors"] == []


def test_bulk_import_empty_file(client: TestClient) -> None:
    """Verify that an empty CSV file returns 0 counts without error."""
    officer_headers = _create_user_and_login(
        client, "officer.import3@carbontrack.org", UserRole.FIELD_OFFICER
    )

    files = {"file": ("empty.csv", io.BytesIO(b""), "text/csv")}
    response = client.post(
        "/api/v1/farmers/bulk-import", files=files, headers=officer_headers
    )

    assert response.status_code == status.HTTP_200_OK
    result = response.json()
    assert result["total_rows"] == 0
    assert result["imported_count"] == 0
    assert result["failed_count"] == 0
    assert result["errors"] == []


def test_bulk_import_invalid_file_extension(client: TestClient) -> None:
    """Verify 400 Bad Request when attempting to upload a non-CSV file."""
    admin_headers = _create_user_and_login(
        client, "super.admin@carbontrack.org", UserRole.ADMIN
    )

    files = {
        "file": ("malicious.exe", io.BytesIO(b"not a csv"), "application/octet-stream")
    }
    response = client.post(
        "/api/v1/farmers/bulk-import", files=files, headers=admin_headers
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "CSV" in response.json()["error"]["message"]


def test_bulk_import_role_permissions(client: TestClient) -> None:
    """Verify unauthenticated (401), verifier (403), and field officer / admin (200)."""
    admin_headers = _create_user_and_login(
        client, "super.admin@carbontrack.org", UserRole.ADMIN
    )
    verifier_headers = _create_user_and_login(
        client, "verifier.import@carbontrack.org", UserRole.VERIFIER
    )

    csv_data = "Name,Consent\nChannappa,true\n"
    files = {"file": ("valid.csv", io.BytesIO(csv_data.encode("utf-8")), "text/csv")}

    # 1. Unauthenticated -> 401
    unauth = client.post(
        "/api/v1/farmers/bulk-import",
        files={"file": ("test.csv", io.BytesIO(csv_data.encode("utf-8")), "text/csv")},
    )
    assert unauth.status_code == status.HTTP_401_UNAUTHORIZED

    # 2. Verifier role -> 403 Forbidden (verifiers cannot create/import farmers)
    verif = client.post(
        "/api/v1/farmers/bulk-import",
        files={"file": ("test.csv", io.BytesIO(csv_data.encode("utf-8")), "text/csv")},
        headers=verifier_headers,
    )
    assert verif.status_code == status.HTTP_403_FORBIDDEN

    # 3. Admin -> 200 OK
    adm = client.post("/api/v1/farmers/bulk-import", files=files, headers=admin_headers)
    assert adm.status_code == status.HTTP_200_OK
    assert adm.json()["imported_count"] == 1


def test_bulk_import_edge_cases_and_parsers(db_session) -> None:
    """Verify internal CSV parsing edge cases, blank lines, Latin-1 encodings, and boolean parsing."""
    from app.services.farmer_service import (
        _parse_boolean_consent,
        bulk_import_farmers_from_csv,
        list_farmers,
    )

    # 1. Test _parse_boolean_consent
    assert _parse_boolean_consent(None) is False
    assert _parse_boolean_consent(True) is True
    assert _parse_boolean_consent(False) is False
    assert _parse_boolean_consent("yes") is True
    assert _parse_boolean_consent("0") is False

    # 2. Test empty string or empty bytes
    res_empty = bulk_import_farmers_from_csv(db_session, file_content="")
    assert res_empty.total_rows == 0
    assert res_empty.imported_count == 0

    # 3. Test empty header only
    res_hdr_only = bulk_import_farmers_from_csv(
        db_session, file_content="Name,Consent\n"
    )
    assert res_hdr_only.total_rows == 0

    # 4. Test Latin-1 encoding fallback with row containing fewer columns than header
    latin1_bytes = "Name,Phone,Consent\nKäthe\n".encode("latin-1")
    res_latin1 = bulk_import_farmers_from_csv(db_session, file_content=latin1_bytes)
    assert res_latin1.total_rows == 1
    assert res_latin1.failed_count == 1

    # 5. Test list_farmers with state filter
    farmers, total = list_farmers(db_session, state="Karnataka")
    assert isinstance(farmers, list)
    assert total >= 0
