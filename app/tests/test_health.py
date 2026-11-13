"""Tests for health check and root endpoints."""

from unittest.mock import MagicMock

from fastapi import status
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.main import app


def test_health_check_success(client: TestClient) -> None:
    """Verify /health returns 200 with status healthy and database connected."""
    response = client.get("/health")
    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    assert data["status"] == "healthy"
    assert data["database"] == "connected"
    assert "environment" in data


def test_root_endpoint(client: TestClient) -> None:
    """Verify root endpoint returns basic project metadata and navigation."""
    response = client.get("/")
    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    assert data["project"] == "CarbonTrack"
    assert data["docs"] == "/docs"
    assert data["health"] == "/health"


def test_health_check_database_failure(client: TestClient) -> None:
    """Verify /health returns 503 when the database connection fails."""
    mock_db = MagicMock()
    mock_db.execute.side_effect = Exception("Simulated DB connection failure")

    def override_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        response = client.get("/health")
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        data = response.json()
        assert "connectivity check failed" in data["detail"]
    finally:
        app.dependency_overrides.clear()
