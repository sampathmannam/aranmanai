"""Pydantic settings for Aranmanai. All env vars prefixed ARANMANAI_."""
from __future__ import annotations

import os
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings. Override via env vars (ARANMANAI_*) or .env file."""

    model_config = SettingsConfigDict(
        env_prefix="ARANMANAI_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── Application ──
    app_name: str = "Aranmanai"
    version: str = "0.1.0"
    environment: Literal["development", "staging", "production"] = "development"
    district: str = Field(default="default-district", description="District name (single-district v1)")

    # ── Server ──
    host: str = "127.0.0.1"
    port: int = 8080
    workers: int = 1
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:8501", "http://127.0.0.1:8501"])

    # ── Database ──
    db_path: Path = Path("data/aranmanai.db")
    db_key: str = ""  # MUST be set via ARANMANAI_DB_KEY env var; refused at startup if empty
    db_echo: bool = False

    @field_validator("db_key")
    @classmethod
    def _db_key_required(cls, v):
        if not v or len(v) < 32:
            raise ValueError(
                "ARANMANAI_DB_KEY must be set to a 32+ char secret via env var or .env file. "
                "Run `python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"` to generate one."
            )
        return v

    # ── LLM ──
    llm_backend: Literal["mock", "llama_cpp", "ollama"] = "mock"
    llm_model_path: Path = Path("models/llm/qwen-1.5b-instruct/qwen2.5-1.5b-instruct-q4_k_m.gguf")
    llm_n_ctx: int = 4096
    llm_n_threads: int = 8
    llm_n_gpu_layers: int = 35  # 0 = CPU only
    llm_temperature: float = 0.1
    llm_max_tokens: int = 2048
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "phi3.5:3.8b-mini-instruct-q4_K_M"

    # ── Vector store ──
    chroma_persist_dir: Path = Path("data/chroma")
    chroma_collection_bns: str = "bns_bnss_bsa_corpus"
    chroma_collection_judgments: str = "hc_sc_judgments"
    chroma_collection_bprd: str = "bprd_studies"

    # ── DPDP / Audit ──
    enable_audit_log: bool = True
    audit_log_path: Path = Path("data/audit.log")

    @field_validator("audit_log_path")
    @classmethod
    def _audit_log_path_safe(cls, v: Path, info: ValidationInfo) -> Path:
        # M-3 fix: the tamper-evident audit log must live on durable
        # storage. Reject pointing it at the OS temp dir (the one concrete
        # attack the security audit named — an ephemeral location that
        # loses the DPDP §8(3) chain on reboot/cleanup).
        #
        # Scoped to production only: the hermetic test suite legitimately
        # isolates every run under the OS temp dir (see tests/conftest.py
        # tmp_env, which uses tempfile.mkdtemp), so an unconditional ban
        # would make the audit log un-testable. `environment` is defined
        # above this field, so it is already validated and present in
        # info.data by the time this runs.
        resolved = v.resolve()
        if info.data.get("environment") != "production":
            return resolved
        temp_root = Path(tempfile.gettempdir()).resolve()
        if resolved == temp_root or temp_root in resolved.parents:
            raise ValueError(
                f"ARANMANAI_AUDIT_LOG_PATH must not be under the OS temp directory "
                f"({temp_root}); the tamper-evident audit log needs durable storage. "
                f"Got: {resolved}"
            )
        return resolved

    # ── Security ──
    jwt_secret: str = ""  # MUST be set via ARANMANAI_JWT_SECRET env var
    jwt_algorithm: str = "HS256"
    jwt_expiry_minutes: int = 60
    bcrypt_rounds: int = 12

    @field_validator("jwt_secret")
    @classmethod
    def _jwt_secret_required(cls, v):
        if not v or len(v) < 32:
            raise ValueError(
                "ARANMANAI_JWT_SECRET must be set to a 32+ char secret via env var or .env file. "
                "Run `python -c \"import secrets; print(secrets.token_urlsafe(48))\"` to generate one."
            )
        return v

    # ── Logging ──
    log_level: str = "INFO"
    log_format: Literal["json", "text"] = "json"
    log_file: Path | None = None

    @field_validator("log_file", mode="before")
    @classmethod
    def _empty_log_file_to_none(cls, v):
        # Pydantic-settings + empty env string would otherwise coerce to Path('.')
        # which then makes the logging factory try to open the CWD as a file.
        if v is None or v == "":
            return None
        return v

    # ── Mock state integrations ──
    mock_cctns_data_dir: Path = Path("data/mock_cctns")
    mock_esakshya_data_dir: Path = Path("data/mock_esakshya")
    mock_icjs_data_dir: Path = Path("data/mock_icjs")

    # ── Feature flags ──
    enable_voice_input: bool = False
    enable_tamil_ui: bool = True
    enable_risk_scoring: bool = True
    enable_mock_integrations: bool = True

    # ── Voice (STT / TTS) ──
    whisper_model: str = Field(default="small", description="tiny|base|small|medium")
    whisper_device: str = "cpu"  # CPU is fine for Whisper small on Ryzen
    vad_threshold: float = 0.5
    max_audio_size_mb: int = 50

    # ── Tamil (translation / embeddings) ──
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    translation_model_enta: str = "Helsinki-NLP/opus-mt-en-ta"
    translation_model_taen: str = "Helsinki-NLP/opus-mt-ta-en"
    translation_model_enhi: str = "Helsinki-NLP/opus-mt-en-hi"
    translation_model_hien: str = "Helsinki-NLP/opus-mt-hi-en"

    def is_production(self) -> bool:
        return self.environment == "production"

    def ensure_dirs(self) -> None:
        """Create all required directories if they don't exist."""
        for path in [
            self.db_path.parent,
            self.chroma_persist_dir,
            self.audit_log_path.parent,
            self.mock_cctns_data_dir,
            self.mock_esakshya_data_dir,
            self.mock_icjs_data_dir,
            self.llm_model_path.parent,
        ]:
            path.mkdir(parents=True, exist_ok=True)
        # M-3: verify the audit log's directory is actually writable. A
        # field_validator must stay side-effect-free, so this runtime probe
        # (which needs the dir to already exist) lives here instead. Fail
        # loudly at startup rather than silently losing audit writes later.
        audit_parent = self.audit_log_path.parent
        if not os.access(str(audit_parent), os.W_OK):
            raise RuntimeError(
                f"Audit log directory is not writable: {audit_parent}. "
                f"The DPDP §8(3) audit log cannot be persisted here."
            )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings instance."""
    s = Settings()
    s.ensure_dirs()
    return s
