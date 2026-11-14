"""Application configuration loaded from environment variables and .env file."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central settings for the CarbonTrack application."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    PROJECT_NAME: str = "CarbonTrack"
    API_V1_STR: str = "/api/v1"
    ENVIRONMENT: str = "development"

    # Authentication & Security
    SECRET_KEY: str = "dev-secret-key-carbontrack-local-super-secure-32chars"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # First Admin Bootstrap Seed Credentials
    FIRST_ADMIN_EMAIL: str = "admin@carbontrack.org"
    FIRST_ADMIN_PASSWORD: str = "AdminPassword123!"

    # CORS Settings
    BACKEND_CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:8000",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:8000",
    ]

    # Rate Limiting & Upload Protections
    RATE_LIMIT_PER_MINUTE: int = 60
    AUTH_RATE_LIMIT_PER_MINUTE: int = 10
    MAX_UPLOAD_SIZE_BYTES: int = 10 * 1024 * 1024  # 10 MB limit

    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"

    # Database
    DATABASE_URL: str = "sqlite:///./carbontrack.db"


settings = Settings()
