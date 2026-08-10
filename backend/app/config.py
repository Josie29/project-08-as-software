from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, PostgresDsn, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[2]


class AppEnv(StrEnum):
    LOCAL = "local"
    CI = "ci"
    PRODUCTION = "production"


class Settings(BaseSettings):
    """Application configuration, loaded from environment variables.

    Every field here must have a corresponding placeholder entry in the repo's
    committed `.env.example` (brief: Security, Privacy & Compliance).
    """

    # The repo keeps a single .env at its root so the backend and frontend read the
    # same values. Anchoring on the package location rather than the process CWD means
    # `uv run uvicorn` works from either the repo root or backend/.
    model_config = SettingsConfigDict(
        env_file=(_REPO_ROOT / ".env", _REPO_ROOT / "backend" / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: AppEnv = AppEnv.LOCAL
    log_level: str = "INFO"
    # NoDecode suppresses pydantic-settings' default JSON decoding of complex types so
    # CORS_ORIGINS can be written as a plain comma-separated string in .env.
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000"]
    )

    database_url: PostgresDsn

    supabase_url: str
    supabase_service_role_key: str
    supabase_storage_bucket: str = "phi-assets"

    resend_api_key: str = ""
    resend_from_email: str = "noreply@example.com"

    # Public base URL of the patient-facing frontend; share links are built from it.
    frontend_base_url: str = "http://localhost:3000"

    share_link_ttl_hours: int = Field(default=48, ge=1, le=168)
    identity_verification_ttl_minutes: int = Field(default=30, ge=1)
    identity_max_attempts: int = Field(default=5, ge=1)
    identity_lockout_minutes: int = Field(default=15, ge=1)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: str | list[str]) -> list[str]:
        """Allow CORS_ORIGINS to be given as a comma-separated string in .env.

        Args:
            value: Raw value from the environment or a already-parsed list.

        Returns:
            A list of origin strings with surrounding whitespace stripped.
        """
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @property
    def supabase_jwks_url(self) -> str:
        """Return the JWKS endpoint used to verify Supabase Auth tokens.

        The project signs tokens with an asymmetric ES256 key, so the backend needs
        only the public half — there is no shared secret to configure, and the backend
        therefore cannot mint tokens even if compromised.

        Returns:
            The project's JWKS URL.
        """
        return f"{self.supabase_url}/auth/v1/.well-known/jwks.json"

    @property
    def sqlalchemy_url(self) -> str:
        """Return the database URL forced onto the asyncpg driver.

        Supabase hands out `postgresql://` URLs; SQLAlchemy's async engine needs the
        `postgresql+asyncpg://` form.

        Returns:
            A SQLAlchemy-compatible async connection string.
        """
        url = str(self.database_url)
        if url.startswith("postgresql+"):
            return url
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings singleton.

    Returns:
        The cached `Settings` instance.

    Raises:
        pydantic.ValidationError: If a required environment variable is missing.
    """
    # Required fields are populated by pydantic-settings from the environment and the
    # .env file, which type checkers cannot see — hence no constructor arguments here.
    return Settings()  # pyright: ignore[reportCallIssue]
