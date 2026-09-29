"""Extraction result shared by native and OCR paths."""

from __future__ import annotations

from dataclasses import dataclass

from ..models.enums import ExtractionMethod


@dataclass(frozen=True)
class ExtractedDocument:
    text: str
    page_count: int
    method: ExtractionMethod

    @property
    def text_length(self) -> int:
        return len(self.text)
