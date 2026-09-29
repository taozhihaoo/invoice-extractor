"""Result models shared by the processing pipeline, the REST API and the UI."""

from __future__ import annotations

from pydantic import BaseModel, Field

from .enums import DocumentStatus, DocumentType, ExtractionMethod
from .invoice import InvoiceData


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0


class Classification(BaseModel):
    document_type: DocumentType
    confidence: float = Field(ge=0.0, le=1.0)
    method: str  # "rules" (deterministic) or "llm" (model fallback)


class ValidationResult(BaseModel):
    passed: bool
    warnings: list[str] = Field(default_factory=list)


class InvoiceExtraction(BaseModel):
    """Invoice fields plus the outcome of deterministic validation."""

    invoice: InvoiceData
    validation: ValidationResult
    needs_review: bool
    review_reasons: list[str] = Field(default_factory=list)
    llm_provider: str = "mock"
    llm_model: str | None = None
    usage: Usage = Field(default_factory=Usage)


class DocumentResult(BaseModel):
    document_id: str
    original_filename: str
    status: DocumentStatus
    document_type: DocumentType | None = None
    page_count: int | None = None
    extraction_method: ExtractionMethod | None = None
    text_length: int | None = None
    file_size: int
    sha256: str
    content_type: str | None = None
    error_message: str | None = None
    duplicate: bool = False
    duplicate_of: str | None = None
    run_id: str | None = None
    classification: Classification | None = None
    review_reasons: list[str] = Field(default_factory=list)
    created_at: str | None = None
    updated_at: str | None = None
    extraction: InvoiceExtraction | None = None


class BatchResult(BaseModel):
    batch_id: str
    total: int
    succeeded: int
    failed: int
    needs_review: int
    duplicates: int = 0
    results: list[DocumentResult] = Field(default_factory=list)


class RunSummary(BaseModel):
    run_id: str
    started_at: str
    finished_at: str | None = None
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    needs_review: int = 0


class RunDetail(RunSummary):
    documents: list[DocumentResult] = Field(default_factory=list)
