"""Domain errors.

Every error in this hierarchy carries a stable machine-readable ``code`` and a
message that is safe to show to API clients: no stack traces, no internal
paths, no provider details.
"""

from __future__ import annotations


class DocumentProcessorError(Exception):
    """Base class for expected, user-safe errors."""

    code = "processing_error"
    message = "processing failed"
    status_code = 400

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.message)
        if message:
            self.message = message


class ConfigurationError(DocumentProcessorError):
    code = "configuration_error"
    status_code = 500


class UploadError(DocumentProcessorError):
    """An uploaded file was rejected before/while processing."""

    status_code = 422
    code = "upload_error"


class UnsupportedFileTypeError(UploadError):
    status_code = 415
    code = "unsupported_file_type"


class UnsupportedMediaTypeError(UploadError):
    status_code = 415
    code = "unsupported_media_type"


class FileTooLargeError(UploadError):
    status_code = 413
    code = "file_too_large"


class EmptyFileError(UploadError):
    status_code = 422
    code = "empty_file"


class InvalidPdfError(UploadError):
    """Not a readable PDF (bad magic bytes, truncated, encrypted, no pages)."""

    status_code = 422
    code = "invalid_pdf"


class TooManyPagesError(UploadError):
    status_code = 422
    code = "too_many_pages"


class BatchTooLargeError(UploadError):
    status_code = 413
    code = "too_many_files"
