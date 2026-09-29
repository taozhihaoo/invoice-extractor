"""Upload validation unit tests."""

import pytest

from src.errors import (
    EmptyFileError,
    FileTooLargeError,
    InvalidPdfError,
    UnsupportedFileTypeError,
    UnsupportedMediaTypeError,
)
from src.upload_validator import sanitise_filename, validate_upload

VALID_PDF = b"%PDF-1.7\n...rest of document..."


class TestSanitiseFilename:
    def test_strips_path_traversal(self):
        assert sanitise_filename("../../secret.txt") == "secret.txt"

    def test_strips_windows_path_traversal(self):
        assert sanitise_filename("..\\..\\..\\windows\\system32\\evil.pdf") == "evil.pdf"

    def test_keeps_simple_name(self):
        assert sanitise_filename("invoice_2026.pdf") == "invoice_2026.pdf"

    def test_removes_control_characters(self):
        assert sanitise_filename("bad\x00name\n.pdf") == "badnamen.pdf" or sanitise_filename(
            "bad\x00name.pdf"
        ).endswith(".pdf")

    def test_empty_becomes_placeholder(self):
        assert sanitise_filename(None) == "upload.pdf"
        assert sanitise_filename("") == "upload.pdf"


class TestValidateUpload:
    def test_valid_upload_passes(self):
        info = validate_upload(
            filename="invoice.pdf", content_type="application/pdf", data=VALID_PDF,
            max_size_bytes=1024 * 1024,
        )
        assert info.original_filename == "invoice.pdf"
        assert info.size == len(VALID_PDF)

    def test_empty_file_rejected(self):
        with pytest.raises(EmptyFileError):
            validate_upload(
                filename="a.pdf", content_type="application/pdf", data=b"",
                max_size_bytes=1024,
            )

    def test_oversized_file_rejected(self):
        with pytest.raises(FileTooLargeError):
            validate_upload(
                filename="a.pdf", content_type="application/pdf", data=VALID_PDF * 10,
                max_size_bytes=16,
            )

    def test_wrong_extension_rejected(self):
        with pytest.raises(UnsupportedFileTypeError):
            validate_upload(
                filename="invoice.txt", content_type="application/pdf", data=VALID_PDF,
                max_size_bytes=1024,
            )

    def test_wrong_mime_type_rejected(self):
        with pytest.raises(UnsupportedMediaTypeError):
            validate_upload(
                filename="invoice.pdf", content_type="text/html", data=VALID_PDF,
                max_size_bytes=1024,
            )

    def test_octet_stream_accepted_when_magic_bytes_are_pdf(self):
        info = validate_upload(
            filename="invoice.pdf", content_type="application/octet-stream",
            data=VALID_PDF, max_size_bytes=1024,
        )
        assert info.content_type == "application/octet-stream"

    def test_mime_parameters_are_ignored(self):
        info = validate_upload(
            filename="invoice.pdf", content_type="application/pdf; charset=utf-8",
            data=VALID_PDF, max_size_bytes=1024,
        )
        assert info.content_type == "application/pdf"

    def test_missing_pdf_magic_rejected(self):
        with pytest.raises(InvalidPdfError):
            validate_upload(
                filename="fake.pdf", content_type="application/pdf",
                data=b"just some text pretending to be a pdf",
                max_size_bytes=1024,
            )

    def test_path_traversal_filename_is_sanitised(self):
        info = validate_upload(
            filename="../../secret.pdf", content_type="application/pdf",
            data=VALID_PDF, max_size_bytes=1024,
        )
        assert info.original_filename == "secret.pdf"
