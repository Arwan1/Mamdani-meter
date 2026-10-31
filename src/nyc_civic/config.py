from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Configuration for a laptop-only instance of the platform."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env", env_prefix="NYCP_", extra="ignore"
    )

    gemini_api_key: str | None = Field(
        default=None,
        repr=False,
        validation_alias=AliasChoices("GEMINI_API_KEY", "NYCP_GEMINI_API_KEY"),
    )
    gemini_model_fast: str = Field(
        default="gemini-flash-latest",
        validation_alias=AliasChoices("GEMINI_MODEL_FAST", "NYCP_GEMINI_MODEL_FAST"),
    )
    gemini_model_pro: str = Field(
        default="gemini-pro-latest",
        validation_alias=AliasChoices("GEMINI_MODEL_PRO", "NYCP_GEMINI_MODEL_PRO"),
    )
    storage_dir: Path = PROJECT_ROOT / "data"
    database_path: Path = PROJECT_ROOT / "data" / "nyc_civic.sqlite3"
    allowed_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    min_coverage: float = 0.6
    max_upload_bytes: int = 10 * 1024 * 1024

    @property
    def upload_dir(self) -> Path:
        return self.storage_dir / "uploads"

    @property
    def policy_dir(self) -> Path:
        return self.storage_dir / "policy"

    @property
    def origins(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
