"""REST API tests: /health, POST/GET /documents, download, safe errors."""


from tests.conftest import (
    CORRUPTED_PDF_BYTES,
    SAMPLE_INVOICE_TEXT,
    make_image_only_pdf,
    make_pdf,
    make_settings,
    upload_pdf,
)


class TestHealth:
    def test_health_reports_provider_and_ocr(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["llm_provider"] == "mock"
        assert isinstance(body["ocr_available"], bool)
        assert body["version"]


class TestUploadDocument:
    def test_upload_processes_invoice(self, client):
        response = upload_pdf(client, make_pdf(SAMPLE_INVOICE_TEXT), "invoice.pdf")
        assert response.status_code == 201
        body = response.json()
        assert body["status"] == "processed"
        assert body["document_type"] == "invoice"
        assert body["extraction"]["invoice"]["invoice_number"] == "INV-9001"
        assert body["extraction"]["validation"]["passed"] is True
        assert body["extraction"]["needs_review"] is False
        assert body["extraction"]["llm_provider"] == "mock"
        assert body["classification"]["method"] == "rules"

    def test_duplicate_upload_returns_existing_document(self, client):
        data = make_pdf(SAMPLE_INVOICE_TEXT)
        first = upload_pdf(client, data, "a.pdf").json()
        second = upload_pdf(client, data, "b.pdf")
        assert second.status_code == 200
        body = second.json()
        assert body["duplicate"] is True
        assert body["document_id"] == first["document_id"]

    def test_txt_extension_rejected_415(self, client):
        response = upload_pdf(
            client, make_pdf(SAMPLE_INVOICE_TEXT), "notes.txt", "application/pdf"
        )
        assert response.status_code == 415
        assert response.json()["error"]["code"] == "unsupported_file_type"

    def test_wrong_mime_rejected_415(self, client):
        response = upload_pdf(
            client, make_pdf(SAMPLE_INVOICE_TEXT), "invoice.pdf", "text/html"
        )
        assert response.status_code == 415
        assert response.json()["error"]["code"] == "unsupported_media_type"

    def test_empty_file_rejected_422(self, client):
        response = upload_pdf(client, b"", "empty.pdf")
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "empty_file"

    def test_oversized_file_rejected_413(self, tmp_path):
        settings = make_settings(tmp_path, max_upload_size_mb=1)
        from fastapi.testclient import TestClient

        from src.api.app import create_app

        with TestClient(create_app(settings)) as http:
            response = upload_pdf(http, b"%PDF-" + b"x" * (1024 * 1024 + 1), "big.pdf")
        assert response.status_code == 413
        assert response.json()["error"]["code"] == "file_too_large"

    def test_corrupted_pdf_recorded_as_failed(self, client):
        response = upload_pdf(client, CORRUPTED_PDF_BYTES, "corrupt.pdf")
        assert response.status_code == 201  # upload fine; processing failed
        body = response.json()
        assert body["status"] == "failed"
        assert "invalid_pdf" in body["error_message"]

    def test_path_traversal_filename_sanitised(self, client):
        response = upload_pdf(
            client, make_pdf(SAMPLE_INVOICE_TEXT), "../../etc/passwd.pdf"
        )
        assert response.status_code == 201
        body = response.json()
        assert body["original_filename"] == "passwd.pdf"
        # Storage name is generated, never the original filename.
        assert body["document_id"] != "passwd"

    def test_image_only_pdf_reports_ocr_honestly(self, client):
        response = upload_pdf(
            client, make_image_only_pdf(SAMPLE_INVOICE_TEXT), "scanned.pdf"
        )
        body = response.json()
        assert body["status"] == "needs_review"
        assert body["extraction_method"] == "none"
        assert any("OCR" in reason for reason in body["review_reasons"])


class TestGetDocuments:
    def test_get_document_by_id(self, client):
        created = upload_pdf(client, make_pdf(SAMPLE_INVOICE_TEXT)).json()
        response = client.get(f"/documents/{created['document_id']}")
        assert response.status_code == 200
        assert response.json()["sha256"] == created["sha256"]

    def test_get_unknown_document_is_404_with_safe_body(self, client):
        response = client.get("/documents/does-not-exist")
        assert response.status_code == 404
        error = response.json()["error"]
        assert error["code"] == "http_404"
        assert "document not found" in error["message"]

    def test_list_documents(self, client):
        upload_pdf(client, make_pdf(SAMPLE_INVOICE_TEXT), "a.pdf")
        response = client.get("/documents")
        assert response.status_code == 200
        body = response.json()
        assert body["total"] >= 1
        assert len(body["items"]) == body["total"]

    def test_download_round_trips_exact_bytes(self, client):
        data = make_pdf(SAMPLE_INVOICE_TEXT)
        created = upload_pdf(client, data, "original.pdf").json()
        response = client.get(f"/documents/{created['document_id']}/download")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/pdf")
        assert response.content == data


class TestSafeErrors:
    def test_internal_error_returns_sanitised_500(self, client, monkeypatch):
        components = client.app.state.components

        def boom(*args, **kwargs):
            raise RuntimeError("secret internal path C:\\Users\\x\\secret.db leaked")

        monkeypatch.setattr(components.batch, "process_one", boom)
        response = upload_pdf(client, make_pdf(SAMPLE_INVOICE_TEXT))
        assert response.status_code == 500
        text = response.text
        assert response.json()["error"]["code"] == "internal_error"
        assert "Traceback" not in text
        assert "RuntimeError" not in text
        assert "secret" not in text

    def test_request_validation_is_sanitised(self, client):
        response = client.post("/documents")  # missing file part
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_error"
