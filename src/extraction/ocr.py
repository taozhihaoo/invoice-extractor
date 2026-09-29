"""Optional OCR adapter backed by Tesseract (pytesseract + Pillow).

The adapter is honest about its prerequisites: when the Tesseract binary is
not installed, ``is_available()`` returns False and the pipeline flags the
document for review instead of pretending OCR happened. Real OCR therefore
requires installing Tesseract separately (see README).
"""

from __future__ import annotations

import shutil
from collections.abc import Iterable
from pathlib import Path


class OcrUnavailableError(Exception):
    """Raised when OCR is requested but the Tesseract engine is missing."""


class OcrExtractor:
    def __init__(self, dpi: int = 200, language: str = "eng") -> None:
        self.dpi = dpi
        self.language = language

    def is_available(self) -> bool:
        return shutil.which("tesseract") is not None

    def extract_pages(self, pdf_path: Path, page_indices: Iterable[int]) -> list[str]:
        if not self.is_available():
            raise OcrUnavailableError(
                "Tesseract OCR engine is not installed; see README for setup"
            )
        # Imported lazily so the rest of the app works without Pillow/pytesseract.
        import pymupdf
        import pytesseract
        from PIL import Image

        doc = pymupdf.open(pdf_path)
        try:
            texts = []
            for index in page_indices:
                pix = doc[index].get_pixmap(dpi=self.dpi)
                image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                texts.append(pytesseract.image_to_string(image, lang=self.language))
            return texts
        finally:
            doc.close()
