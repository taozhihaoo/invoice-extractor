"""API-specific response models."""

from __future__ import annotations

from pydantic import BaseModel

from ..models import DocumentResult


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str
    llm_provider: str
    ocr_available: bool


class DocumentListResponse(BaseModel):
    total: int
    items: list[DocumentResult]
