"""Shared pytest fixtures with an isolated test database."""

import os
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.deps import get_db
from app.core.rate_limit import api_rate_limiter, auth_rate_limiter
from app.db.session import Base
from app.main import app

# Dedicated test database (defaults to sqlite for fast local testing, or postgresql via env in CI)
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "sqlite:///./test.db")

connect_args = (
    {"check_same_thread": False} if TEST_DATABASE_URL.startswith("sqlite") else {}
)

test_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args=connect_args,
)

TestingSessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=test_engine,
)


@pytest.fixture(autouse=True)
def clean_database() -> Generator[None, None, None]:
    """Ensure every individual test runs against a clean, isolated database."""
    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture(autouse=True)
def override_db_session_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure background tasks and services use the isolated test database session factory."""
    monkeypatch.setattr("app.db.session.SessionLocal", TestingSessionLocal)


@pytest.fixture(autouse=True)
def reset_rate_limiters() -> Generator[None, None, None]:
    """Ensure in-memory rate limiters start fresh for every individual test."""
    auth_rate_limiter.reset()
    api_rate_limiter.reset()
    yield
    auth_rate_limiter.reset()
    api_rate_limiter.reset()


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_file() -> Generator[None, None, None]:
    """Remove test.db from disk after all tests finish if running against local SQLite."""
    yield
    test_engine.dispose()
    if TEST_DATABASE_URL.startswith("sqlite") and os.path.exists("./test.db"):
        try:
            os.remove("./test.db")
        except OSError:
            pass


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    """Provide a transactional test database session for direct DB testing."""
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db_session: Session) -> Generator[TestClient, None, None]:
    """Provide a TestClient with get_db overridden to use the test database."""

    def override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
