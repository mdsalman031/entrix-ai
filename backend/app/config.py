"""Application configuration via Pydantic Settings.

Loads from environment variables and .env file. All secrets must come from
environment — never hard-coded.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from secrets import token_urlsafe

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Database ──────────────────────────────────────────────────────
    # Resolve the local database relative to the backend, not the shell's
    # current directory, so `python run.py` works consistently from the root.
    database_url: str = f"sqlite+aiosqlite:///{Path(__file__).resolve().parents[1] / 'entrix.db'}"

    # ── Qdrant ────────────────────────────────────────────────────────
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_in_memory: bool = True
    qdrant_collection: str = "entrix_chunks"

    # ── Security ──────────────────────────────────────────────────────
    # A process-local development key avoids a source-controlled signing key.
    # Production must provide SECRET_KEY via a secret manager/environment.
    secret_key: str = Field(default_factory=lambda: token_urlsafe(48))
    access_token_expire_minutes: int = 60
    algorithm: str = "HS256"

    # ── Embedding ─────────────────────────────────────────────────────
    embedding_model: str = "all-MiniLM-L6-v2"
    embedding_dimension: int = 384
    embedding_backend: str = "hash"  # hash (offline demo) | sentence_transformer

    # ── LLM Provider ─────────────────────────────────────────────────
    llm_provider: str = "mock"  # mock | openai | anthropic
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-20250514"

    # ── Retrieval ─────────────────────────────────────────────────────
    retrieval_top_k: int = 5
    chunk_size: int = 512
    chunk_overlap: int = 50

    # ── Sufficiency Controller ───────────────────────────────────────
    sufficiency_estimator: str = "heuristic"  # heuristic | llm | structured
    sufficiency_threshold: float = 0.6
    max_retry_attempts: int = 1
    auto_create_schema: bool = True  # development only; production runs Alembic

    # ── Logging ──────────────────────────────────────────────────────
    log_level: str = "INFO"

    # ── Paths ────────────────────────────────────────────────────────
    data_dir: Path = Path("data")


@lru_cache
def get_settings() -> Settings:
    return Settings()
