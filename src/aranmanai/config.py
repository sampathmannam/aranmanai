"""Application configuration loaded from environment / .env.

Single source of truth for runtime settings. Every secret in
.env (DB encryption key, JWT secret, future state-platform tokens)
loads here. Defaults are workstation-friendly so the app boots
on `uvicorn src.aranmanai.main:app` with zero config.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Read from env + .env at project root."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- App ---
    app_name: str = "Aranmanai"
    app_version: str = "0.1.0"
    environment: str = Field(default="development", description="development|staging|production")
    log_level: str = Field(default="INFO", description="DEBUG|INFO|WARNING|ERROR|CRITICAL")
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:8501"])

    # --- Storage ---
    data_dir: Path = Field(default=Path("data"))
    db_path: Path = Field(default=Path("data/aranmanai.db"))
    chroma_dir: Path = Field(default=Path("data/chroma"))
    models_dir: Path = Field(default=Path("models"))
    backups_dir: Path = Field(default=Path("data/backups"))

    # --- Security ---
    db_encryption_key: str = Field(
        default="dev-only-change-me-in-prod-7f3a9c2b8e1d4f6a",
        description="SQLCipher PRAGMA key. Override in .env for production.",
    )
    jwt_secret: str = Field(
        default="dev-only-change-me-in-prod-jwt-c4e8a1d9f2b3",
        description="JWT signing secret. Override in .env for production.",
    )
    jwt_algorithm: str = "HS256"
    jwt_access_ttl_minutes: int = 60
    bcrypt_rounds: int = 12

    # --- AI (local LLM) ---
    llm_backend: str = Field(
        default="llama-cpp-python",
        description="llama-cpp-python | ollama | mock",
    )
    llm_model_path: Path | None = Field(
        default=None,
        description="Path to GGUF model. If None, LLM calls return mock response.",
    )
    llm_n_ctx: int = 4096
    llm_n_gpu_layers: int = Field(
        default=20,
        description="Number of layers to offload to GPU. RTX 2050 4GB: 20-28 safe for 3.8B Q4_K_M.",
    )
    llm_temperature: float = 0.1
    llm_max_tokens: int = 1024

    # --- Voice ---
    whisper_model: str = Field(default="small", description="tiny|base|small|medium")
    whisper_device: str = "cpu"  # CPU is fine for Whisper small on Ryzen

    # --- Integrations (mock by default) ---
    cctns_mode: str = Field(default="mock", description="mock | real")
    esakshya_mode: str = Field(default="mock", description="mock | real")
    icjs_mode: str = Field(default="mock", description="mock | real")

    # --- Pilot / Tenant (single district v1) ---
    district: str = Field(default="Vellore", description="Default district for v1 pilot.")
    tenant_enabled: bool = Field(
        default=False,
        description="Multi-tenant is v2. v1 is single-district only.",
    )

    # --- Backup ---
    backup_encryption_key: str = Field(
        default="dev-only-change-me-in-prod-backup-9b4e7c1d5a8f",
    )
    backup_schedule_hours: int = 24

    def ensure_dirs(self) -> None:
        """Create all required directories. Idempotent."""
        for d in (self.data_dir, self.chroma_dir, self.models_dir, self.backups_dir):
            d.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings singleton. First call loads from env + .env."""
    s = Settings()
    s.ensure_dirs()
    return s


settings = get_settings()
