"""SQLite persistence.

- Three tables: ``documents``, ``extractions``, ``processing_runs``.
- Every statement is parameterised (no string interpolation of values).
- The schema is created idempotently on first use.
- Money is stored as TEXT (exact decimal strings) to avoid float drift.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id                TEXT PRIMARY KEY,
    original_filename TEXT NOT NULL,
    content_type      TEXT,
    file_size         INTEGER NOT NULL,
    sha256            TEXT NOT NULL,
    status            TEXT NOT NULL,
    document_type     TEXT,
    classification_method     TEXT,
    classification_confidence REAL,
    page_count        INTEGER,
    extraction_method TEXT,
    text_length       INTEGER,
    storage_path      TEXT,
    run_id            TEXT,
    error_message     TEXT,
    review_reasons    TEXT,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_documents_sha256 ON documents (sha256);
CREATE INDEX IF NOT EXISTS idx_documents_run_id ON documents (run_id);

CREATE TABLE IF NOT EXISTS extractions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id         TEXT NOT NULL UNIQUE REFERENCES documents (id),
    supplier            TEXT,
    invoice_number      TEXT,
    invoice_date        TEXT,
    due_date            TEXT,
    subtotal            TEXT,
    tax                 TEXT,
    total               TEXT,
    currency            TEXT,
    validation_status   TEXT,
    validation_warnings TEXT,
    needs_review        INTEGER NOT NULL DEFAULT 0,
    review_reasons      TEXT,
    llm_provider        TEXT,
    llm_model           TEXT,
    prompt_tokens       INTEGER NOT NULL DEFAULT 0,
    completion_tokens   INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS processing_runs (
    run_id       TEXT PRIMARY KEY,
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    total        INTEGER NOT NULL DEFAULT 0,
    success      INTEGER NOT NULL DEFAULT 0,
    failed       INTEGER NOT NULL DEFAULT 0,
    needs_review INTEGER NOT NULL DEFAULT 0,
    uploads_json TEXT
);
"""

_DOCUMENT_COLUMNS = (
    "id", "original_filename", "content_type", "file_size", "sha256", "status",
    "document_type", "classification_method", "classification_confidence",
    "page_count", "extraction_method", "text_length", "storage_path", "run_id",
    "error_message", "review_reasons", "created_at", "updated_at",
)

_EXTRACTION_COLUMNS = (
    "document_id", "supplier", "invoice_number", "invoice_date", "due_date",
    "subtotal", "tax", "total", "currency", "validation_status",
    "validation_warnings", "needs_review", "review_reasons",
    "llm_provider", "llm_model", "prompt_tokens", "completion_tokens", "created_at",
)

_EXTRACTION_DEFAULTS = {
    "needs_review": 0,
    "prompt_tokens": 0,
    "completion_tokens": 0,
}

_UPDATABLE_DOCUMENT_COLUMNS = frozenset(_DOCUMENT_COLUMNS) - {"id", "created_at"}


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _dumps(value: list[str] | None) -> str | None:
    return json.dumps(value) if value is not None else None


def _loads(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


class Database:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            # WAL keeps reads from blocking the writer while a batch is running.
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA)
            # Databases created before uploads_json existed keep working.
            columns = {row[1] for row in conn.execute("PRAGMA table_info(processing_runs)")}
            if "uploads_json" not in columns:
                conn.execute("ALTER TABLE processing_runs ADD COLUMN uploads_json TEXT")

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        # Concurrent uploads share one file; wait instead of raising at once.
        conn.execute("PRAGMA busy_timeout=30000")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    # documents ------------------------------------------------------------

    def insert_document(self, record: dict[str, Any]) -> None:
        placeholders = ", ".join("?" for _ in _DOCUMENT_COLUMNS)
        columns = ", ".join(_DOCUMENT_COLUMNS)
        values = [record.get(column) for column in _DOCUMENT_COLUMNS]
        with self._conn() as conn:
            conn.execute(
                f"INSERT INTO documents ({columns}) VALUES ({placeholders})", values
            )

    def update_document(self, document_id: str, **fields: Any) -> None:
        unknown = set(fields) - _UPDATABLE_DOCUMENT_COLUMNS
        if unknown:
            raise ValueError(f"unknown document columns: {sorted(unknown)}")
        assignments = ", ".join(f"{column} = ?" for column in fields)
        values = list(fields.values()) + [document_id]
        with self._conn() as conn:
            conn.execute(
                f"UPDATE documents SET {assignments} WHERE id = ?", values
            )

    def get_document(self, document_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM documents WHERE id = ?", (document_id,)
            ).fetchone()
        return dict(row) if row else None

    def find_document_by_sha256(self, sha256: str) -> dict[str, Any] | None:
        """Return the most recent *usable* document holding these exact bytes.

        Documents that failed (or never finished) are deliberately excluded:
        re-uploading the same file after a transient failure must actually try
        again instead of handing back the failed record forever.
        """
        with self._conn() as conn:
            row = conn.execute(
                """SELECT * FROM documents
                   WHERE sha256 = ? AND status IN ('processed', 'needs_review')
                   ORDER BY created_at DESC, rowid DESC LIMIT 1""",
                (sha256,),
            ).fetchone()
        return dict(row) if row else None

    def list_documents(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        with self._conn() as conn:
            # rowid keeps the order stable inside one batch, where several rows
            # share the same second-precision created_at.
            rows = conn.execute(
                """SELECT * FROM documents
                   ORDER BY created_at DESC, rowid DESC LIMIT ? OFFSET ?""",
                (limit, offset),
            ).fetchall()
        return [dict(row) for row in rows]

    def count_documents(self) -> int:
        with self._conn() as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM documents").fetchone()
        return int(row["n"])

    def count_documents_by_status(self) -> dict[str, int]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS n FROM documents GROUP BY status"
            ).fetchall()
        return {row["status"]: int(row["n"]) for row in rows}

    # extractions ----------------------------------------------------------

    def insert_extraction(self, record: dict[str, Any]) -> None:
        placeholders = ", ".join("?" for _ in _EXTRACTION_COLUMNS)
        columns = ", ".join(_EXTRACTION_COLUMNS)
        values = [
            record.get(column) if record.get(column) is not None
            else _EXTRACTION_DEFAULTS.get(column)
            for column in _EXTRACTION_COLUMNS
        ]
        with self._conn() as conn:
            conn.execute(
                f"INSERT INTO extractions ({columns}) VALUES ({placeholders})", values
            )

    def get_extraction(self, document_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM extractions WHERE document_id = ?", (document_id,)
            ).fetchone()
        return dict(row) if row else None

    # processing runs ------------------------------------------------------

    def create_run(self, run_id: str, started_at: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO processing_runs (run_id, started_at) VALUES (?, ?)",
                (run_id, started_at),
            )

    def finish_run(
        self,
        run_id: str,
        *,
        total: int,
        success: int,
        failed: int,
        needs_review: int,
        finished_at: str,
        uploads: list[dict[str, Any]] | None = None,
    ) -> None:
        uploads_json = json.dumps(uploads) if uploads is not None else None
        with self._conn() as conn:
            conn.execute(
                """UPDATE processing_runs
                   SET total = ?, success = ?, failed = ?, needs_review = ?, finished_at = ?,
                       uploads_json = ?
                   WHERE run_id = ?""",
                (total, success, failed, needs_review, finished_at, uploads_json, run_id),
            )

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM processing_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        return dict(row) if row else None

    def list_runs(self, limit: int = 10) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM processing_runs ORDER BY started_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_run_documents(self, run_id: str) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM documents WHERE run_id = ? ORDER BY rowid",
                (run_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    # export ---------------------------------------------------------------

    def export_rows(self, run_id: str | None = None) -> list[dict[str, Any]]:
        query = """
            SELECT d.id AS document_id, d.original_filename, d.status, d.document_type,
                   d.classification_method, d.classification_confidence,
                   d.page_count, d.extraction_method, d.text_length, d.file_size,
                   d.sha256, d.run_id, d.error_message, d.review_reasons AS doc_review_reasons,
                   e.supplier, e.invoice_number, e.invoice_date, e.due_date,
                   e.subtotal, e.tax, e.total, e.currency,
                   e.validation_status, e.validation_warnings,
                   e.needs_review, e.review_reasons,
                   e.llm_provider, e.llm_model, e.prompt_tokens, e.completion_tokens
            FROM documents d
            LEFT JOIN extractions e ON e.document_id = d.id
        """
        params: tuple[Any, ...] = ()
        if run_id is not None:
            query += " WHERE d.run_id = ?"
            params = (run_id,)
        query += " ORDER BY d.rowid"
        with self._conn() as conn:
            rows = conn.execute(query, params).fetchall()
        result = []
        for row in rows:
            record = dict(row)
            record["validation_warnings"] = _loads(record.get("validation_warnings"))
            review_reasons = record.get("review_reasons") or record.get("doc_review_reasons")
            record["review_reasons"] = _loads(review_reasons)
            # Non-invoice documents carry needs_review in documents.status only.
            record["needs_review"] = bool(record.get("needs_review")) or (
                record.get("status") == "needs_review"
            )
            result.append(record)
        return result
