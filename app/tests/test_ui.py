"""Tests for the lightweight HTML/CSS visual MRV platform dashboard."""

from fastapi import status
from fastapi.testclient import TestClient


def test_dashboard_endpoint_serves_html(client: TestClient) -> None:
    """Verify that GET /dashboard serves the static HTML dashboard with 200 OK."""
    response = client.get("/dashboard")
    assert response.status_code == status.HTTP_200_OK
    assert "text/html" in response.headers.get("content-type", "")
    assert "CarbonTrack" in response.text
    assert "MRV Dashboard" in response.text


def test_root_endpoint_references_dashboard(client: TestClient) -> None:
    """Verify that root welcome JSON includes the /dashboard route."""
    response = client.get("/")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["dashboard"] == "/dashboard"
