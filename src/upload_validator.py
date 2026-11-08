"""Upload validation: every check happens before a byte reaches storage.

The original filename is never used for storage paths (a generated UUID name
is used instead), so path traversal is structurally impossible; it is still
sanitised because it is echoed back in API responses and download headers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .errors import (
    EmptyFileError,
    FileTooLargeError,
    InvalidPdfError,
    UnsupportedFileTypeError,
    UnsupportedMediaTypeError,
)

# Clients that do not set a MIME type ("" / "application/octet-stream") are
# accepted here; the magic-byte check below provides the real guarantee.
ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "application/x-pdf",
    "application/octet-stream",
    "",
}

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


@dataclass(frozen=True)
class SanitisedUpload:
    original_filename: str
    content_type: str
    size: int


def sanitise_filename(name: str | None) -> str:
    """Reduce an untrusted filename to a safe display value."""
    if not name:
        return "upload.pdf"
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    name = _CONTROL_CHARS.sub("", name).strip().strip(".")
    return name or "upload.pdf"


def size_limit_message(max_size_bytes: int) -> str:
    return (
        "file exceeds the maximum allowed size of "
        f"{max_size_bytes // (1024 * 1024)} MB"
    )


def validate_upload(
    *,
    filename: str | None,
    content_type: str | None,
    data: bytes,
    max_size_bytes: int,
) -> SanitisedUpload:
    original = sanitise_filename(filename)

    if not data:
        raise EmptyFileError("uploaded file is empty")
    if len(data) > max_size_bytes:
        raise FileTooLargeError(size_limit_message(max_size_bytes))
    if not original.lower().endswith(".pdf"):
        raise UnsupportedFileTypeError("only .pdf files are supported")

    media_type = (content_type or "").split(";", 1)[0].strip().lower()
    if media_type not in ALLOWED_CONTENT_TYPES:
        raise UnsupportedMediaTypeError(
            f"content type {media_type!r} is not accepted; expected application/pdf"
        )
    if b"%PDF-" not in data[:1024]:
        raise InvalidPdfError("file content does not look like a PDF document")

    return SanitisedUpload(
        original_filename=original,
        content_type=media_type or "application/pdf",
        size=len(data),
    )
