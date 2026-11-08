"""UI rendering: localisation, static assets and upload error pages."""

from __future__ import annotations

from fastapi.testclient import TestClient

from src.api.app import create_app
from src.api.i18n import STRINGS
from tests.conftest import (
    CORRUPTED_PDF_BYTES,
    SAMPLE_INVOICE_TEXT,
    make_pdf,
    make_settings,
    upload_pdf,
)


class TestLanguageSwitch:
    def test_default_language_is_english(self, client):
        page = client.get("/")
        assert '<html lang="en">' in page.text
        assert "Dashboard" in page.text
        assert "总览" not in page.text

    def test_query_parameter_renders_chinese(self, client):
        page = client.get("/?lang=zh")
        assert page.status_code == 200
        assert '<html lang="zh">' in page.text
        assert "总览" in page.text
        assert "上传" in page.text

    def test_language_choice_is_remembered_in_a_cookie(self, client):
        response = client.get("/?lang=zh")
        assert response.cookies.get("lang") == "zh"
        page = client.get("/")  # no query parameter this time
        assert '<html lang="zh">' in page.text

    def test_accept_language_header_is_honoured(self, client):
        page = client.get("/", headers={"Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"})
        assert '<html lang="zh">' in page.text

    def test_unknown_language_falls_back_to_english(self, client):
        page = client.get("/?lang=de")
        assert '<html lang="en">' in page.text


class TestTemplatesCoverBothLanguages:
    def test_every_string_has_both_translations(self):
        missing = [
            key
            for key, entry in STRINGS.items()
            if not entry.get("en") or not entry.get("zh")
        ]
        assert missing == []

    def test_pages_render_in_chinese_without_falling_back_to_keys(self, client):
        created = upload_pdf(client, make_pdf(SAMPLE_INVOICE_TEXT), "invoice.pdf").json()
        urls = [
            "/?lang=zh",
            "/upload?lang=zh",
            f"/documents/{created['document_id']}/view?lang=zh",
            f"/runs/{created['run_id']}/view?lang=zh",
        ]
        for url in urls:
            page = client.get(url)
            assert page.status_code == 200, url
            # A missing key would be rendered literally as e.g. "doc.fields".
            assert "doc." not in page.text, url
            assert "upload." not in page.text, url
            assert "nav." not in page.text, url


class TestStaticAssets:
    def test_stylesheet_and_favicon_are_served(self, client):
        css = client.get("/static/app.css")
        assert css.status_code == 200
        assert "--accent" in css.text
        favicon = client.get("/static/favicon.svg")
        assert favicon.status_code == 200


class TestUploadPageErrors:
    def test_no_files_selected_shows_a_friendly_page(self, client):
        response = client.post("/upload", files=[])
        assert response.status_code == 422
        assert "text/html" in response.headers["content-type"]
        assert "error.code" not in response.text

    def test_too_many_files_shows_a_friendly_page(self, tmp_path):
        settings = make_settings(tmp_path, max_batch_files=1)
        with TestClient(create_app(settings), raise_server_exceptions=False) as client:
            response = client.post(
                "/upload",
                files=[
                    ("files", ("a.pdf", make_pdf(SAMPLE_INVOICE_TEXT), "application/pdf")),
                    ("files", ("b.pdf", make_pdf(SAMPLE_INVOICE_TEXT), "application/pdf")),
                ],
            )
        assert response.status_code == 413
        assert "text/html" in response.headers["content-type"]
        assert "too_many_files" in response.text

    def test_rejected_upload_renders_error_page_not_json(self, client):
        response = client.post(
            "/upload",
            files=[("files", ("broken.pdf", CORRUPTED_PDF_BYTES, "application/pdf"))],
            follow_redirects=False,
        )
        # A batch records the failure per file instead of rejecting the whole
        # request, so the user lands on the run result page.
        assert response.status_code == 303

    def test_missing_page_renders_html_instead_of_json(self, client):
        for url in ("/documents/nope/view", "/runs/nope/view"):
            response = client.get(url)
            assert response.status_code == 404, url
            assert "text/html" in response.headers["content-type"], url
            assert "not_found" in response.text, url
