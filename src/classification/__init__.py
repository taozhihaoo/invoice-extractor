"""Document classification: rules first, LLM fallback for ambiguous text."""

from .classifier import DocumentClassifier

__all__ = ["DocumentClassifier"]
