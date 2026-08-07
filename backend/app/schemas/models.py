"""Pydantic schemas for models, memory, files, and settings."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import DocumentStatus, MemoryType


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class ModelInfo(BaseModel):
    """Available model info."""

    name: str
    provider: str
    display_name: str
    description: str
    is_available: bool
    capabilities: list[str] = Field(default_factory=list)
    context_window: int | None = None


class ModelList(BaseModel):
    """List of available models."""

    default: str
    fallback_chain: list[str]
    models: list[ModelInfo]


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------
class MemoryCreate(BaseModel):
    """Memory creation schema."""

    content: str
    memory_type: MemoryType = MemoryType.LONG_TERM
    key: str | None = None
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    metadata_: dict[str, Any] = Field(default_factory=dict)


class MemoryUpdate(BaseModel):
    """Memory update schema - all fields optional, only provided ones change."""

    content: str | None = None
    importance: float | None = Field(default=None, ge=0.0, le=1.0)
    metadata_: dict[str, Any] | None = None


class MemoryRead(BaseModel):
    """Memory response schema."""

    id: str
    memory_type: MemoryType
    content: str
    key: str | None = None
    importance: float
    metadata_: dict[str, Any]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MemoryList(BaseModel):
    """Paginated memory list."""

    items: list[MemoryRead]
    total: int


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------
class FileUploadResponse(BaseModel):
    """File upload response schema."""

    file_id: str
    filename: str
    content_type: str
    size: int
    url: str
    category: str


class DocumentRead(BaseModel):
    """Document response schema."""

    id: str
    thread_id: str | None = None
    filename: str
    file_type: str
    file_size: int
    status: DocumentStatus
    chunk_count: int
    # Carries `metadata_["error"]` when status is FAILED, so a processing
    # failure (corrupt file, no extractable text, ...) surfaces as a clear,
    # specific message in the UI instead of a silent/generic failure the
    # user has no way to diagnose.
    metadata_: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DocumentList(BaseModel):
    """List of documents."""

    items: list[DocumentRead]
    total: int


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
class SettingsUpdate(BaseModel):
    """User settings update."""

    theme: str | None = None  # light | dark | system
    default_model: str | None = None
    default_provider: str | None = None
    voice_input_enabled: bool | None = None
    voice_output_enabled: bool | None = None
    streaming_enabled: bool | None = None
    system_prompt: str | None = Field(default=None, max_length=4000)
    preferences: dict[str, Any] | None = None
