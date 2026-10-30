"""Application settings loaded from environment variables and the repo-root .env file."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", REPO_ROOT / "backend" / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Model providers
    gemini_api_key: SecretStr | None = None
    gemini_model: str = ""
    nvidia_api_key: SecretStr | None = None
    nvidia_model: str = "nvidia/nemotron-3.5-super-vl-120b-a12b"
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"

    # Search
    tavily_api_key: SecretStr | None = None
    search_provider: str = "tavily"
    enable_duckduckgo_fallback: bool = True

    # Storage
    database_url: str = "sqlite:///./data/arven_ai.db"
    data_dir: Path = REPO_ROOT / "data"

    # Server
    backend_host: str = "127.0.0.1"
    backend_port: int = 8000
    frontend_origin: str = "http://localhost:5173"
    # Host headers the API answers to (comma-separated). Blocks DNS-rebinding attacks from other websites.
    allowed_hosts: str = "127.0.0.1,localhost"
    # Required when the backend is reachable from the internet; empty means no login (local use only).
    access_password: SecretStr | None = None

    # Research budgets (conservative defaults)
    max_search_rounds: int = Field(default=2, ge=1, le=4)
    max_unique_sources: int = Field(default=20, ge=3, le=60)
    max_concurrent_requests: int = Field(default=4, ge=1, le=16)
    request_timeout_seconds: float = Field(default=20.0, ge=3, le=120)
    max_report_words: int = Field(default=2500, ge=300, le=8000)
    max_retry_attempts: int = Field(default=2, ge=0, le=5)
    job_timeout_seconds: int = Field(default=900, ge=60, le=3600)

    # Provider circuit breaker
    provider_cooldown_seconds: int = Field(default=60, ge=5)
    provider_quota_cooldown_seconds: int = Field(default=1800, ge=60)
    max_retry_wait_seconds: float = Field(default=8.0, ge=0)

    # Uploads
    max_upload_mb: int = Field(default=20, ge=1, le=100)

    @property
    def gemini_default_model(self) -> str:
        # Verified against ai.google.dev/gemini-api/docs/models on 2026-10-29.
        return self.gemini_model or "gemini-3.5-flash-lite"

    @property
    def sqlite_path(self) -> Path:
        raw = self.database_url.removeprefix("sqlite:///")
        path = Path(raw)
        return path if path.is_absolute() else (REPO_ROOT / path).resolve()

    @property
    def async_database_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.sqlite_path.as_posix()}"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def reports_dir(self) -> Path:
        return self.data_dir / "reports"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def secret(value: SecretStr | None) -> str:
    return value.get_secret_value().strip() if value else ""
