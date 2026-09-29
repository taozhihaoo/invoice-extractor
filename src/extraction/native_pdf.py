"""Native (text-layer) PDF extraction via PyMuPDF.

PyMuPDF is distributed under the AGPL-3.0 license; this project is an
independent portfolio project and uses it under those terms.
"""

from __future__ import annotations

from pathlib import Path

import pymupdf

from ..errors import InvalidPdfError


class NativePdfExtractor:
    def extract_pages(self, path: Path) -> tuple[int, list[str]]:
        """Return ``(page_count, [text per page])`` for a readable text PDF."""
        try:
            doc = pymupdf.open(path)
        except Exception as exc:  # pymupdf raises several low-level types
            raise InvalidPdfError("file could not be parsed as a PDF document") from exc
        try:
            if not doc.is_pdf:
                raise InvalidPdfError("file is not a PDF document")
            if doc.needs_pass:
                raise InvalidPdfError("password-protected PDFs are not supported")
            pages = [page.get_text("text") for page in doc]
            return len(pages), pages
        finally:
            doc.close()
