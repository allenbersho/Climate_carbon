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

    # Database
    DATABASE_URL: str = "sqlite:///./carbontrack.db"


settings = Settings()
