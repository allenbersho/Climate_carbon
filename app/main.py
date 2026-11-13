"""FastAPI main application entrypoint."""

from fastapi import FastAPI, HTTPException, status
from sqlalchemy import text

from app.api.deps import SessionDep
from app.core.config import settings

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Backend MRV platform for carbon removal projects.",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)


@app.get("/health", tags=["System"])
def health_check(db: SessionDep) -> dict[str, str]:
    """Verify application liveness and database connectivity."""
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database connectivity check failed: {exc!s}",
        ) from exc

    return {
        "status": "healthy",
        "database": "connected",
        "environment": settings.ENVIRONMENT,
    }


@app.get("/", tags=["System"])
def root() -> dict[str, str]:
    """Root welcome endpoint."""
    return {
        "project": settings.PROJECT_NAME,
        "docs": "/docs",
        "health": "/health",
    }
