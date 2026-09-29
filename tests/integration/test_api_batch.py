"""REST API tests: batch upload, run queries, export endpoints, web UI."""

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from tests.conftest import (
    CORRUPTED_PDF_BYTES,
    SAMPLE_INVOICE_MISMATCH,
    SAMPLE_INVOICE_MISSING_DUE_DATE,
    SAMPLE_INVOICE_TEXT,
    make_pdf,
    make_settings,
    upload_pdf,
)


@pytest.fixture
def batch_client(tmp_path):
    settings = make_settings(tmp_path, max_batch_files=3)
    with TestClient(create_app(settings)) as http:
        yield http


def post_batch(http, *tuples):
    files = [
        ("files", (name, data, "application/pdf")) for name, data in tuples
    ]
    return http.post("/documents/batch", files=files)


class TestBatchEndpoint:
    def test_batch_processes_each_file_independently(self, batch_client):
        response = post_batch(
            batch_client,
            ("ok.pdf", make_pdf(SAMPLE_INVOICE_TEXT)),
            ("mismatch.pdf", make_pdf(SAMPLE_INVOICE_MISMATCH)),
            ("corrupt.pdf", CORRUPTED_PDF_BYTES),
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 3
        assert body["succeeded"] == 1
        assert body["needs_review"] == 1
        assert body["failed"] == 1
        assert len(body["results"]) == 3
        statuses = {r["status"] for r in body["results"]}
        assert statuses == {"processed", "needs_review", "failed"}

    def test_batch_size_limit_is_enforced(self, batch_client):
        response = post_batch(
            batch_client,
            ("a.pdf", make_pdf(SAMPLE_INVOICE_TEXT)),
            ("b.pdf", make_pdf(SAMPLE_INVOICE_TEXT)),
            ("c.pdf", make_pdf(SAMPLE_INVOICE_TEXT)),
            ("d.pdf", make_pdf(SAMPLE_INVOICE_TEXT)),
        )
        assert response.status_code == 413
        assert response.json()["error"]["code"] == "too_many_files"


class TestRuns:
    def test_get_run_matches_batch_summary(self, batch_client):
        batch = post_batch(
            batch_client,
            ("ok.pdf", make_pdf(SAMPLE_INVOICE_TEXT)),
            ("corrupt.pdf", CORRUPTED_PDF_BYTES),
        ).json()
        response = batch_client.get(f"/runs/{batch['batch_id']}")
        assert response.status_code == 200
        run = response.json()
        assert run["total"] == 2
        assert run["succeeded"] == 1
        assert run["failed"] == 1
        assert len(run["documents"]) == 2
        assert run["finished_at"] is not None

    def test_unknown_run_is_404(self, batch_client):
        response = batch_client.get("/runs/nope")
        assert response.status_code == 404


class TestExport:
    def test_csv_export_contains_invoice_rows(self, client):
        upload_pdf(client, make_pdf(SAMPLE_INVOICE_TEXT), "invoice.pdf")
        response = client.get("/export/csv")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/csv")
        lines = response.text.strip().splitlines()
        assert len(lines) == 2
        header = lines[0].split(",")
        assert header[0] == "filename"
        assert "INV-9001" in lines[1]

    def test_json_export_full_structure(self, client):
        upload_pdf(client, make_pdf(SAMPLE_INVOICE_TEXT), "invoice.pdf")
        response = client.get("/export/json")
        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 1
        doc = body["documents"][0]
        assert doc["invoice"]["invoice_number"] == "INV-9001"
        assert doc["filename"] == "invoice.pdf"

    def test_export_filtered_by_run(self, client):
        batch = post_batch(
            client, ("a.pdf", make_pdf(SAMPLE_INVOICE_TEXT))
        ).json()
        response = client.get("/export/csv", params={"run_id": batch["batch_id"]})
        assert len(response.text.strip().splitlines()) == 2  # header + 1 row

    def test_export_with_no_data_is_empty_not_error(self, client):
        response = client.get("/export/csv")
        assert response.status_code == 200
        assert response.text.count("\n") == 1  # header only


class TestWebUI:
    def test_dashboard_renders(self, client):
        upload_pdf(client, make_pdf(SAMPLE_INVOICE_TEXT), "invoice.pdf")
        response = client.get("/")
        assert response.status_code == 200
        assert "Dashboard" in response.text
        assert "invoice.pdf" in response.text

    def test_upload_form_renders(self, client):
        response = client.get("/upload")
        assert response.status_code == 200
        assert 'enctype="multipart/form-data"' in response.text

    def test_upload_form_processes_and_redirects(self, client):
        response = client.post(
            "/upload",
            files=[
                ("files", ("a.pdf", make_pdf(SAMPLE_INVOICE_TEXT), "application/pdf")),
                ("files", ("b.pdf", make_pdf(SAMPLE_INVOICE_MISMATCH), "application/pdf")),
            ],
            follow_redirects=False,
        )
        assert response.status_code == 303
        run_url = response.headers["location"]
        assert run_url.startswith("/runs/")
        page = client.get(run_url)
        assert page.status_code == 200
        assert "a.pdf" in page.text
        assert "needs_review" in page.text

    def test_document_detail_page(self, client):
        created = upload_pdf(client, make_pdf(SAMPLE_INVOICE_TEXT)).json()
        response = client.get(f"/documents/{created['document_id']}/view")
        assert response.status_code == 200
        assert "Test Supplier GmbH" in response.text
        assert "INV-9001" in response.text

    def test_document_page_for_missing_document_is_404(self, client):
        response = client.get("/documents/nope/view")
        assert response.status_code == 404

    def test_run_page_unknown_is_404(self, client):
        response = client.get("/runs/nope/view")
        assert response.status_code == 404


class TestRunPageDuplicateDisplay:
    """Regression: run result page must show every upload, including duplicates.

    Duplicates intentionally have no document row (dedup design); the batch
    manifest recorded on the run lets the UI display them anyway.
    """

    def test_mixed_batch_shows_duplicates_and_failures_in_table(self, client):
        comps = client.app.state.components
        data = make_pdf(SAMPLE_INVOICE_TEXT)
        upload_pdf(client, data, "original.pdf")
        documents_before = comps.db.count_documents()

        batch = post_batch(
            client,
            ("invoice.pdf", data),                                       # duplicate
            ("missing.pdf", make_pdf(SAMPLE_INVOICE_MISSING_DUE_DATE)),  # needs_review
            ("corrupt.pdf", CORRUPTED_PDF_BYTES),                        # failed
        ).json()
        assert batch["total"] == 3
        assert batch["duplicates"] == 1
        assert batch["needs_review"] == 1
        assert batch["failed"] == 1

        page = client.get(f"/runs/{batch['batch_id']}/view")
        assert page.status_code == 200
        assert "invoice.pdf" in page.text       # duplicate upload is listed
        assert "missing.pdf" in page.text
        assert "corrupt.pdf" in page.text
        assert "duplicate" in page.text
        # Summary and table are consistent: one row per upload, but the
        # duplicate created no additional document row.
        assert comps.db.count_documents() == documents_before + 2

    def test_all_duplicate_batch_table_is_not_empty(self, client):
        comps = client.app.state.components
        data = make_pdf(SAMPLE_INVOICE_TEXT)
        upload_pdf(client, data, "first.pdf")
        documents_before = comps.db.count_documents()

        batch = post_batch(client, ("a.pdf", data), ("b.pdf", data)).json()
        assert batch["total"] == 2
        assert batch["duplicates"] == 2

        page = client.get(f"/runs/{batch['batch_id']}/view")
        assert page.status_code == 200
        assert "a.pdf" in page.text
        assert "b.pdf" in page.text
        assert page.text.count("duplicate") >= 2
        # Dedup design unchanged: duplicates never create document rows.
        assert comps.db.count_documents() == documents_before
        # API contract unchanged: summary correct, and this run has no document
        # rows of its own because both uploads were duplicates.
        run = client.get(f"/runs/{batch['batch_id']}").json()
        assert (run["total"], run["succeeded"], run["needs_review"], run["failed"]) == (2, 2, 0, 0)
        assert run["documents"] == []


class TestTemplatePlaceholders:
    """Regression: null-field placeholders must render as an em dash, not the
    literal text ``&mdash;`` (Jinja autoescape escapes HTML entities that are
    interpolated through {{ }})."""

    def test_pages_render_em_dash_not_escaped_entity(self, client):
        created = upload_pdf(client, CORRUPTED_PDF_BYTES, "corrupt.pdf").json()
        assert created["document_type"] is None  # failed doc: placeholders kick in

        dashboard = client.get("/").text
        assert "&amp;mdash;" not in dashboard  # would render as literal &mdash;
        assert "—" in dashboard

        detail = client.get(f"/documents/{created['document_id']}/view").text
        assert "&amp;mdash;" not in detail
        assert "—" in detail

        # A run page without a manifest (finished_at is set) also renders fine.
        run_page_html = client.get(f"/runs/{created['run_id']}/view").text
        assert "&amp;mdash;" not in run_page_html

    def test_duplicate_within_one_batch_is_listed(self, client):
        """A file duplicated against a document created in the same batch must
        also appear in the run table (by_id skip must not swallow it)."""
        comps = client.app.state.components
        data = make_pdf(SAMPLE_INVOICE_TEXT)
        documents_before = comps.db.count_documents()

        batch = post_batch(client, ("new.pdf", data), ("again.pdf", data)).json()
        assert batch["total"] == 2
        assert batch["duplicates"] == 1

        page = client.get(f"/runs/{batch['batch_id']}/view")
        assert page.status_code == 200
        assert "new.pdf" in page.text
        assert "again.pdf" in page.text
        assert page.text.count("duplicate") >= 1
        assert comps.db.count_documents() == documents_before + 1
