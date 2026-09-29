"""CSV / JSON export of processing results.

The CSV layout is the flat ``invoice_report`` format; JSON carries the full
structured result per document. Non-invoice documents appear with empty
invoice fields so failed and unclassifiable files stay visible in exports.
"""

from __future__ import annotations

import csv
import io
import json
from decimal import Decimal
from typing import Any

CSV_COLUMNS = [
    "filename",
    "supplier",
    "invoice_number",
    "invoice_date",
    "due_date",
    "subtotal",
    "tax",
    "total",
    "currency",
    "document_type",
    "status",
    "needs_review",
]


def _format_amount(value: Any) -> str:
    if value in (None, ""):
        return ""
    try:
        return f"{Decimal(str(value)):.2f}"
    except Exception:
        return ""


def csv_row(record: dict[str, Any]) -> dict[str, str]:
    return {
        "filename": record.get("original_filename") or "",
        "supplier": record.get("supplier") or "",
        "invoice_number": record.get("invoice_number") or "",
        "invoice_date": record.get("invoice_date") or "",
        "due_date": record.get("due_date") or "",
        "subtotal": _format_amount(record.get("subtotal")),
        "tax": _format_amount(record.get("tax")),
        "total": _format_amount(record.get("total")),
        "currency": record.get("currency") or "",
        "document_type": record.get("document_type") or "",
        "status": record.get("status") or "",
        "needs_review": "true" if record.get("needs_review") else "false",
    }


def build_csv(records: list[dict[str, Any]]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS)
    writer.writeheader()
    for record in records:
        writer.writerow(csv_row(record))
    return buffer.getvalue()


def _json_amount(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(Decimal(str(value)))


def build_json(records: list[dict[str, Any]], *, run_id: str | None, generated_at: str) -> str:
    documents = []
    for record in records:
        documents.append(
            {
                "document_id": record.get("document_id"),
                "filename": record.get("original_filename"),
                "status": record.get("status"),
                "document_type": record.get("document_type"),
                "page_count": record.get("page_count"),
                "extraction_method": record.get("extraction_method"),
                "text_length": record.get("text_length"),
                "file_size": record.get("file_size"),
                "sha256": record.get("sha256"),
                "run_id": record.get("run_id"),
                "error_message": record.get("error_message"),
                "invoice": {
                    "supplier": record.get("supplier"),
                    "invoice_number": record.get("invoice_number"),
                    "invoice_date": record.get("invoice_date"),
                    "due_date": record.get("due_date"),
                    "subtotal": _json_amount(record.get("subtotal")),
                    "tax": _json_amount(record.get("tax")),
                    "total": _json_amount(record.get("total")),
                    "currency": record.get("currency"),
                },
                "validation": {
                    "status": record.get("validation_status"),
                    "warnings": record.get("validation_warnings", []),
                },
                "needs_review": bool(record.get("needs_review")),
                "review_reasons": record.get("review_reasons", []),
                "llm": {
                    "provider": record.get("llm_provider"),
                    "model": record.get("llm_model"),
                    "prompt_tokens": record.get("prompt_tokens", 0),
                    "completion_tokens": record.get("completion_tokens", 0),
                },
            }
        )
    payload = {
        "generated_at": generated_at,
        "run_id": run_id,
        "count": len(documents),
        "documents": documents,
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)
