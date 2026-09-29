"""Application configuration.

Values come from environment variables and/or a ``.env`` file (never committed).
Every setting has a safe default so the project runs out of the box in mock mode.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

from .errors import ConfigurationError

Provider = Literal["mock", "openai", "auto"]
EffectiveProvider = Literal["mock", "openai"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM provider
    llm_provider: Provider = "auto"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    openai_base_url: str | None = None
    openai_timeout_seconds: float = 30.0
    openai_max_retries: int = 2
    max_llm_chars: int = 12_000  # cap on document text sent to the model

    # Storage
    database_path: Path = Path("data") / "processor.db"
    upload_dir: Path = Path("data") / "uploads"
    export_dir: Path = Path("output")

    # Upload / processing limits
    max_upload_size_mb: int = 15
    max_pdf_pages: int = 50
    max_batch_files: int = 20
    min_native_text_chars: int = 100  # below this, OCR is attempted if available

    # HTTP server
    app_host: str = "127.0.0.1"
    app_port: int = 8000

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    def effective_provider(self) -> EffectiveProvider:
        """Resolve the configured provider into a concrete implementation."""
        if self.llm_provider == "openai":
            if not self.openai_api_key:
                raise ConfigurationError(
                    "LLM_PROVIDER is 'openai' but OPENAI_API_KEY is not set"
                )
            return "openai"
        if self.llm_provider == "auto":
            return "openai" if self.openai_api_key else "mock"
        return "mock"

    def ensure_dirs(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.export_dir.mkdir(parents=True, exist_ok=True)


def get_settings() -> Settings:
    return Settings()
