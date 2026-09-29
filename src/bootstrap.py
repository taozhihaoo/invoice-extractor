"""Composition root: the single place where settings meet implementations."""

from __future__ import annotations

from dataclasses import dataclass

from .classification.classifier import DocumentClassifier
from .config import Settings
from .database import Database
from .extraction.ocr import OcrExtractor
from .extraction.pipeline import ExtractionPipeline
from .file_store import FileStore
from .llm.base import LLMClient
from .llm.mock import MockLLMClient
from .llm.openai_client import OpenAIClient
from .processing.batch import BatchProcessor
from .processing.service import DocumentProcessor


@dataclass(frozen=True)
class Components:
    settings: Settings
    db: Database
    file_store: FileStore
    processor: DocumentProcessor
    batch: BatchProcessor
    llm: LLMClient
    llm_provider: str
    ocr_available: bool


def build(settings: Settings) -> Components:
    settings.ensure_dirs()
    provider = settings.effective_provider()

    llm: LLMClient
    if provider == "openai":
        llm = OpenAIClient(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            timeout_seconds=settings.openai_timeout_seconds,
            max_retries=settings.openai_max_retries,
            base_url=settings.openai_base_url,
            max_chars=settings.max_llm_chars,
        )
    else:
        llm = MockLLMClient()

    db = Database(settings.database_path)
    store = FileStore(settings.upload_dir)
    ocr = OcrExtractor()
    pipeline = ExtractionPipeline(
        max_pages=settings.max_pdf_pages,
        min_text_chars=settings.min_native_text_chars,
        ocr=ocr,
    )
    classifier = DocumentClassifier(llm_fallback=llm if provider == "openai" else None)
    processor = DocumentProcessor(
        settings=settings,
        db=db,
        file_store=store,
        pipeline=pipeline,
        classifier=classifier,
        llm=llm,
        ocr_available=ocr.is_available(),
    )
    batch = BatchProcessor(processor=processor, db=db, max_files=settings.max_batch_files)
    return Components(
        settings=settings,
        db=db,
        file_store=store,
        processor=processor,
        batch=batch,
        llm=llm,
        llm_provider=provider,
        ocr_available=ocr.is_available(),
    )
