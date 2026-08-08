"""Application configuration management.

Uses pydantic-settings to load configuration from environment variables
and .env files. All settings are accessible via the `get_settings`
cached function for dependency injection.
"""
from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field, PostgresDsn, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent
PROJECT_ROOT = BASE_DIR.parent
# The .env lives at the project root (see README), but a backend-local one is
# honoured as an override. Later files win in pydantic-settings.
ENV_FILES = (PROJECT_ROOT / ".env", BASE_DIR / ".env")


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=tuple(str(path) for path in ENV_FILES),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Application ---
    app_name: str = "Lumina AI"
    app_version: str = "1.0.0"
    app_env: Literal["development", "staging", "production"] = "development"
    debug: bool = False
    # Verbose per-query SQL logging - kept separate from `debug` since it adds
    # real per-request I/O overhead and most debug work doesn't need it.
    sql_echo: bool = False
    secret_key: str = Field(default_factory=secrets.token_urlsafe)
    api_v1_prefix: str = "/api/v1"
    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 4

    # --- CORS ---
    cors_origins: Annotated[list[str], NoDecode] = [
        "http://localhost:5173",
        "http://localhost:3000",
    ]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: Any) -> Any:
        """Parse CORS origins from a JSON string or list."""
        if isinstance(value, str):
            if value.startswith("["):
                import json

                return json.loads(value)
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    # --- Database ---
    database_url: PostgresDsn | str = "sqlite+aiosqlite:///./ai_chatbot.db"
    database_sync_url: PostgresDsn | str = "sqlite:///./ai_chatbot.db"
    redis_url: str = "redis://localhost:6379/0"

    # --- Vector DB ---
    vector_db_type: Literal["faiss", "chroma"] = "chroma"
    chroma_persist_dir: str = "./data/chroma"
    faiss_index_path: str = "./data/faiss"

    # --- LLM Providers ---
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o"
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.5-flash"
    groq_api_key: str | None = None
    groq_model: str = "llama-3.3-70b-versatile"
    openrouter_api_key: str | None = None
    openrouter_model: str = "openai/gpt-4o"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    fallback_models: Annotated[list[str], NoDecode] = ["groq", "gemini", "openrouter", "openai"]
    embedding_model: str = "text-embedding-3-small"

    # --- Live search ---
    # SerpAPI (serpapi.com) proxies real Google Search results - unlike the
    # free DuckDuckGo/Google-scraping web_search tool, it's a paid API with
    # no rate-limiting/CAPTCHA issues, and its answer_box/knowledge_graph
    # fields surface fast-changing data (scores, prices, breaking news)
    # directly instead of just links.
    serpapi_api_key: str | None = None

    @field_validator("fallback_models", mode="before")
    @classmethod
    def parse_fallback_models(cls, value: Any) -> Any:
        """Parse fallback models from comma-separated string or list."""
        if isinstance(value, str):
            return [model.strip() for model in value.split(",") if model.strip()]
        return value

    # --- Auth ---
    jwt_secret_key: str = Field(default_factory=lambda: secrets.token_urlsafe(64))
    jwt_algorithm: str = "HS256"
    jwt_secret_file: str = "./data/jwt_secret.key"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    oauth_google_client_id: str | None = None
    oauth_google_client_secret: str | None = None
    oauth_github_client_id: str | None = None
    oauth_github_client_secret: str | None = None

    # --- Rate Limiting ---
    rate_limit_per_minute: int = 60
    rate_limit_stream_per_minute: int = 30

    # --- Observability ---
    langchain_tracing_v2: bool = True
    langchain_api_key: str | None = None
    langchain_project: str = "ai-chatbot"
    otel_exporter_otlp_endpoint: str = "http://localhost:4317"

    # --- Uploads ---
    max_upload_size_mb: int = 50
    upload_dir: str = "./uploads"
    allowed_extensions: Annotated[list[str], NoDecode] = [
        "pdf", "docx", "pptx", "txt", "md", "csv", "xlsx", "xls",
        "json", "xml", "html", "htm", "zip",
        "jpg", "jpeg", "png", "webp", "gif", "svg", "mp3", "wav", "mp4",
    ]

    @field_validator("allowed_extensions", mode="before")
    @classmethod
    def parse_extensions(cls, value: Any) -> Any:
        """Parse allowed extensions from a comma-separated string or list."""
        if isinstance(value, str):
            return [ext.strip() for ext in value.split(",") if ext.strip()]
        return value

    # --- Model settings ---
    max_tokens: int = 4096
    temperature: float = 0.4
    stream_timeout_seconds: int = 60

    @model_validator(mode="after")
    def validate_provider_keys(self) -> "Settings":
        """Ensure at least one provider API key is configured in production."""
        if self.app_env == "production":
            providers = [
                self.openai_api_key,
                self.gemini_api_key,
                self.groq_api_key,
                self.openrouter_api_key,
            ]
            if not any(providers):
                raise ValueError("At least one LLM provider API key must be configured in production.")
        return self

    @property
    def is_production(self) -> bool:
        """Check if running in production."""
        return self.app_env == "production"

    @property
    def upload_path(self) -> Path:
        """Return the upload directory path."""
        path = Path(self.upload_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path


@lru_cache
def get_settings() -> Settings:
    """Return cached settings instance."""
    return Settings()


settings = get_settings()

