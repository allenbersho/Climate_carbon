"""FastAPI main application entrypoint with security hardening and structured logging."""

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.api.deps import SessionDep
from app.api.routes import api_router
from app.core.config import settings
from app.core.logging import setup_logging

# Initialize structured logging on application boot
setup_logging(log_level=settings.LOG_LEVEL, log_format=settings.LOG_FORMAT)
logger = logging.getLogger(__name__)

if settings.ENVIRONMENT == "production" and "dev-secret-key" in settings.SECRET_KEY:
    logger.warning(
        "SECURITY WARNING: Running in production with default development SECRET_KEY!"
    )

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Backend MRV platform for carbon removal projects.",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Cross-Origin Resource Sharing (CORS) Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Standardized error code mapping per PROJECT_SPEC.md Section 8
_STATUS_CODE_MAP = {
    400: "BAD_REQUEST",
    401: "UNAUTHENTICATED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMIT_EXCEEDED",
    500: "INTERNAL_SERVER_ERROR",
    503: "SERVICE_UNAVAILABLE",
}


@app.exception_handler(HTTPException)
async def custom_http_exception_handler(
    request: Request, exc: HTTPException
) -> JSONResponse:
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


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Format Pydantic schema validation errors with standard error structure."""
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Request validation failed.",
                "details": jsonable_encoder(exc.errors()),
            }
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Global catch-all exception handler to prevent leaking raw internal stack traces."""
    logger.exception(
        f"Unhandled server error on {request.method} {request.url.path}: {exc}"
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "An unexpected internal server error occurred. Please contact system support.",
                "details": None,
            }
        },
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


# Mount static assets for lightweight browser UI
STATIC_DIR = Path(__file__).resolve().parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/dashboard", tags=["System"], response_class=FileResponse)
def dashboard() -> FileResponse:
    """Serve lightweight HTML/CSS visual MRV platform dashboard."""
    html_path = STATIC_DIR / "index.html"
    if not html_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dashboard UI not found.",
        )
    return FileResponse(html_path)


@app.get("/", tags=["System"])
def root() -> dict[str, str]:
    """Root welcome endpoint."""
    return {
        "project": settings.PROJECT_NAME,
        "docs": "/docs",
        "health": "/health",
        "dashboard": "/dashboard",
    }


if settings.ENVIRONMENT != "production":

    @app.get("/test-unhandled-error", include_in_schema=False)
    def test_unhandled_error() -> None:
        """Endpoint used exclusively in test suites to verify 500 error sanitization."""
        raise RuntimeError(
            "Deliberate internal explosion to verify global 500 error sanitization"
        )
