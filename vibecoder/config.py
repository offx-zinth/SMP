from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    """Application configuration loaded from environment variables and `.env` files."""

    model_config = SettingsConfigDict(
        env_file=(".env", ".env.local"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    gemini_api_key: str = Field(..., min_length=1)
    workspace_dir: Path = Field(default_factory=Path.cwd)
    log_level: str = Field(default="INFO")
    smp_db_dir: Path = Field(default=Path(".vibecoder"))
