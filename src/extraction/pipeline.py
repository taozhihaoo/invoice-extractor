"""Extraction pipeline.

Strategy: never assume a PDF needs OCR. Native text is extracted first and
OCR is attempted only when the text yield is below ``min_text_chars`` and an
OCR engine is actually available. When no text can be obtained at all the
document is returned with ``method="none"`` so it can be flagged for review.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..errors import InvalidPdfError, TooManyPagesError
from ..models.enums import ExtractionMethod
from .base import ExtractedDocument
from .native_pdf import NativePdfExtractor
from .ocr import OcrExtractor


def normalise_text(raw: str) -> str:
    """Collapse per-line whitespace and drop empty lines, preserving order."""
    lines = (re.sub(r"[ \t]+", " ", line).strip()
             for line in raw.replace("\r\n", "\n").replace("\r", "\n").split("\n"))
    return "\n".join(line for line in lines if line)


class ExtractionPipeline:
    def __init__(
        self,
        *,
        max_pages: int,
        min_text_chars: int,
        ocr: OcrExtractor | None = None,
    ) -> None:
        self._native = NativePdfExtractor()
        self._max_pages = max_pages
        self._min_text_chars = min_text_chars
        self._ocr = ocr

    def extract(self, path: Path) -> ExtractedDocument:
        page_count, pages = self._native.extract_pages(path)
        if page_count == 0:
            raise InvalidPdfError("PDF document contains no pages")
        if page_count > self._max_pages:
            raise TooManyPagesError(
                f"PDF has {page_count} pages; the maximum allowed is {self._max_pages}"
            )

        text = normalise_text("\n".join(pages))
        method = ExtractionMethod.NATIVE_TEXT

        if len(text) < self._min_text_chars and self._ocr is not None and self._ocr.is_available():
            ocr_text = normalise_text(
                "\n".join(self._ocr.extract_pages(path, range(page_count)))
            )
            if len(ocr_text) > len(text):
                text = ocr_text
                method = ExtractionMethod.OCR

        if not text:
            method = ExtractionMethod.NONE

        return ExtractedDocument(text=text, page_count=page_count, method=method)
