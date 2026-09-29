"""Export formatting tests."""

from src.database import Database
from src.exporters import CSV_COLUMNS, build_csv, build_json, csv_row


def sample_record(**overrides):
    record = {
        "document_id": "doc1",
        "original_filename": "invoice.pdf",
        "status": "processed",
        "document_type": "invoice",
        "supplier": "Supplier Ltd",
        "invoice_number": "INV-1",
        "invoice_date": "2026-09-01",
        "due_date": "2026-10-01",
        "subtotal": "920.00",
        "tax": "92.00",
        "total": "1012.00",
        "currency": "USD",
        "validation_status": "passed",
        "validation_warnings": [],
        "needs_review": False,
        "review_reasons": [],
        "llm_provider": "mock",
        "llm_model": "mock-rules-v1",
        "prompt_tokens": 0,
        "completion_tokens": 0,
    }
    record.update(overrides)
    return record


class TestCsv:
    def test_header_matches_specified_columns(self):
        lines = build_csv([]).strip().splitlines()
        assert lines[0].split(",") == CSV_COLUMNS

    def test_row_values_and_formats(self):
        csv_text = build_csv([sample_record()])
        lines = csv_text.strip().splitlines()
        assert len(lines) == 2
        assert "Supplier Ltd" in lines[1]
        assert "1012.00" in lines[1]
        assert "invoice,processed,false" in lines[1]

    def test_needs_review_flag_rendered(self):
        row = csv_row(sample_record(needs_review=True, status="needs_review"))
        assert row["needs_review"] == "true"

    def test_missing_amounts_render_empty(self):
        row = csv_row(sample_record(subtotal=None, tax=None, total=None))
        assert row["total"] == ""


class TestJson:
    def test_full_structure(self):
        payload = build_json([sample_record()], run_id="run-1", generated_at="t")
        data = __import__("json").loads(payload)
        assert data["count"] == 1
        assert data["run_id"] == "run-1"
        doc = data["documents"][0]
        assert doc["invoice"]["total"] == 1012.0
        assert doc["invoice"]["currency"] == "USD"
        assert doc["validation"]["status"] == "passed"
        assert doc["needs_review"] is False
        assert doc["llm"]["provider"] == "mock"

    def test_empty_export(self):
        data = __import__("json").loads(build_json([], run_id=None, generated_at="t"))
        assert data["count"] == 0
        assert data["documents"] == []


class TestDatabaseIntegration:
    def test_export_rows_feed_exporters(self, tmp_path):
        db = Database(tmp_path / "db.sqlite3")
        db.insert_document(
            {
                "id": "d1", "original_filename": "a.pdf", "file_size": 10,
                "sha256": "x", "status": "processed", "document_type": "invoice",
                "created_at": "2026-09-30T00:00:00+00:00",
                "updated_at": "2026-09-30T00:00:00+00:00",
            }
        )
        db.insert_extraction(
            {
                "document_id": "d1", "invoice_number": "INV-9", "total": "50.00",
                "needs_review": 1, "review_reasons": '["fields could not be extracted: due_date"]',
                "created_at": "2026-09-30T00:00:00+00:00",
            }
        )
        rows = db.export_rows()
        data = __import__("json").loads(build_json(rows, run_id=None, generated_at="t"))
        doc = data["documents"][0]
        assert doc["invoice"]["invoice_number"] == "INV-9"
        assert doc["needs_review"] is True
        assert "due_date" in doc["review_reasons"][0]
