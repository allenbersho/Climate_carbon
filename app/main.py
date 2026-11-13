"""FastAPI main application entrypoint."""

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.deps import SessionDep
from app.api.routes import api_router
from app.core.config import settings

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Backend MRV platform for carbon removal projects.",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Standardized error code mapping per PROJECT_SPEC.md Section 8
_STATUS_CODE_MAP = {
    400: "BAD_REQUEST",
    401: "UNAUTHENTICATED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    409: "CONFLICT",
    422: "VALIDATION_ERROR",
    500: "INTERNAL_SERVER_ERROR",
    503: "SERVICE_UNAVAILABLE",
}


@app.exception_handler(HTTPException)
async def custom_http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Format HTTP errors as {"error": {"code": "...", "message": "...", "details": ...}}."""
    code = _STATUS_CODE_MAP.get(exc.status_code, "ERROR")
    headers = getattr(exc, "headers", None)
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": code,
                "message": exc.detail,
                "details": None,
            }
        },
        headers=headers,
    )


# Register API v1 routes
app.include_router(api_router, prefix=settings.API_V1_STR)


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
