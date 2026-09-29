"""SQLite storage tests."""

import sqlite3

import pytest

from src.database import Database


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "test.db")


def make_document(**overrides):
    record = {
        "id": "doc-1",
        "original_filename": "O'Neil & Co invoice.pdf",
        "content_type": "application/pdf",
        "file_size": 1234,
        "sha256": "abc123",
        "status": "processing",
        "created_at": "2026-09-30T10:00:00+00:00",
        "updated_at": "2026-09-30T10:00:00+00:00",
    }
    record.update(overrides)
    return record


class TestSchema:
    def test_creates_database_file(self, tmp_path):
        db = Database(tmp_path / "nested" / "test.db")
        assert db.path.exists()

    def test_init_is_idempotent(self, tmp_path):
        path = tmp_path / "test.db"
        Database(path)
        Database(path)  # must not raise
        with sqlite3.connect(path) as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        assert {"documents", "extractions", "processing_runs"} <= tables


class TestDocuments:
    def test_insert_and_get_round_trip(self, db):
        db.insert_document(make_document())
        row = db.get_document("doc-1")
        assert row["original_filename"] == "O'Neil & Co invoice.pdf"
        assert row["status"] == "processing"

    def test_get_unknown_returns_none(self, db):
        assert db.get_document("nope") is None

    def test_find_by_sha256(self, db):
        db.insert_document(make_document(sha256="deadbeef"))
        assert db.find_document_by_sha256("deadbeef")["id"] == "doc-1"
        assert db.find_document_by_sha256("missing") is None

    def test_parameterised_values_with_quotes(self, db):
        db.insert_document(make_document())
        row = db.get_document("doc-1")
        assert "'" in row["original_filename"]  # stored intact, no escaping bugs

    def test_update_document_whitelist(self, db):
        db.insert_document(make_document())
        db.update_document(
            "doc-1",
            status="processed",
            document_type="invoice",
            page_count=2,
            text_length=4321,
        )
        row = db.get_document("doc-1")
        assert row["status"] == "processed"
        assert row["document_type"] == "invoice"
        assert row["page_count"] == 2

    def test_update_rejects_unknown_column(self, db):
        db.insert_document(make_document())
        with pytest.raises(ValueError):
            db.update_document("doc-1", evil_column="x")

    def test_list_documents_order_and_pagination(self, db):
        for index in range(5):
            db.insert_document(
                make_document(id=f"doc-{index}", created_at=f"2026-09-3{index}T00:00:00+00:00")
            )
        page = db.list_documents(limit=2, offset=1)
        assert len(page) == 2
        assert db.count_documents() == 5

    def test_counts_by_status(self, db):
        db.insert_document(make_document(id="a", status="processed"))
        db.insert_document(make_document(id="b", status="processed"))
        db.insert_document(make_document(id="c", status="failed"))
        counts = db.count_documents_by_status()
        assert counts == {"processed": 2, "failed": 1}


class TestExtractions:
    def test_insert_and_get(self, db):
        db.insert_document(make_document())
        db.insert_extraction(
            {
                "document_id": "doc-1",
                "supplier": "Test Supplier",
                "invoice_number": "INV-1",
                "subtotal": "100.00",
                "total": "120.00",
                "validation_status": "passed",
                "validation_warnings": '["w1"]',
                "needs_review": 0,
                "review_reasons": None,
                "created_at": "2026-09-30T10:00:00+00:00",
            }
        )
        extraction = db.get_extraction("doc-1")
        assert extraction["supplier"] == "Test Supplier"
        assert extraction["subtotal"] == "100.00"
        assert db.get_extraction("missing") is None


class TestRuns:
    def test_create_and_finish_run(self, db):
        db.create_run("run-1", "2026-09-30T10:00:00+00:00")
        assert db.get_run("run-1")["total"] == 0
        db.finish_run(
            "run-1", total=3, success=2, failed=1, needs_review=0,
            finished_at="2026-09-30T10:05:00+00:00",
        )
        run = db.get_run("run-1")
        assert (run["total"], run["success"], run["failed"]) == (3, 2, 1)
        assert run["finished_at"] is not None

    def test_get_unknown_run_returns_none(self, db):
        assert db.get_run("nope") is None

    def test_list_runs_most_recent_first(self, db):
        db.create_run("run-old", "2026-01-01T00:00:00+00:00")
        db.create_run("run-new", "2026-06-01T00:00:00+00:00")
        runs = db.list_runs()
        assert runs[0]["run_id"] == "run-new"


class TestExportRows:
    def test_left_join_includes_documents_without_extraction(self, db):
        db.insert_document(make_document(id="inv", status="processed"))
        db.insert_document(make_document(id="mem", status="needs_review",
                                         review_reasons='["unknown"]'))
        db.insert_extraction(
            {"document_id": "inv", "invoice_number": "INV-1", "total": "10.00",
             "needs_review": 0, "created_at": "2026-09-30T10:00:00+00:00"}
        )
        rows = db.export_rows()
        assert len(rows) == 2
        by_id = {row["document_id"]: row for row in rows}
        assert by_id["inv"]["invoice_number"] == "INV-1"
        assert by_id["mem"]["invoice_number"] is None
        assert by_id["mem"]["needs_review"] is True  # derived from status

    def test_filter_by_run(self, db):
        db.insert_document(make_document(id="a", run_id="run-1"))
        db.insert_document(make_document(id="b", run_id="run-2"))
        assert [r["document_id"] for r in db.export_rows(run_id="run-1")] == ["a"]
