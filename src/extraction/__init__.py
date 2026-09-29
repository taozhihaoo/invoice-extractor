"""Text extraction: native PDF text first, OCR fallback only when needed."""

from .base import ExtractedDocument
from .native_pdf import NativePdfExtractor
from .ocr import OcrExtractor, OcrUnavailableError
from .pipeline import ExtractionPipeline, normalise_text

__all__ = [
    "ExtractedDocument",
    "ExtractionPipeline",
    "NativePdfExtractor",
    "OcrExtractor",
    "OcrUnavailableError",
    "normalise_text",
]
