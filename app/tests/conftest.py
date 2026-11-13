"""Shared pytest fixtures for CarbonTrack."""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="session")
def client() -> TestClient:
    """Test client for dispatching HTTP requests to the FastAPI application."""
    with TestClient(app) as test_client:
        yield test_client
