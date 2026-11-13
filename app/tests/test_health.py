"""Tests for health check and database session functionality."""

from unittest.mock import MagicMock
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.main import app


def test_health_check_returns_200(client: TestClient) -> None:
    """Test 1: Verify /health returns 200 and database is reported connected."""
    response = client.get("/health")
    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    assert data["status"] == "healthy"
    assert data["database"] == "connected"


def test_database_session_works(db_session: Session) -> None:
    """Test 2: Verify the test database session fixture works and executes queries."""
    result = db_session.execute(text("SELECT 1")).scalar()
    assert result == 1


def test_health_check_database_failure(client: TestClient) -> None:
    """Verify /health returns 503 when the database connectivity fails."""
    mock_db = MagicMock()
    mock_db.execute.side_effect = Exception("Simulated DB connection failure")

    def override_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        response = client.get("/health")
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert "connectivity check failed" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()
