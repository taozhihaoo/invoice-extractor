"""Demo mode: an end-to-end offline run.

Demo always uses the deterministic MockLLMClient - it never requires an
OpenAI API key and never makes a network call. It generates synthetic
invoice samples, processes them as one batch (including a duplicate and a
corrupted file), stores everything in SQLite and writes CSV/JSON exports.
"""

from __future__ import annotations

from ..bootstrap import build
from ..config import Settings
from ..database import utc_now
from ..exporters import build_csv, build_json
from ..models import DocumentStatus
from ..processing import UploadInput
from .samples import generate_demo_documents


def run_demo(settings: Settings) -> int:
    # Demo mode is honest by construction: mock provider, no network.
    settings = settings.model_copy(update={"llm_provider": "mock"})
    settings.ensure_dirs()
    components = build(settings)

    samples_dir = settings.database_path.parent / "demo_samples"
    paths = generate_demo_documents(samples_dir)
    uploads = [
        UploadInput(filename=path.name, content_type="application/pdf", data=path.read_bytes())
        for path in paths
    ]
    # Re-add the first file: demonstrates SHA-256 duplicate detection.
    uploads.append(
        UploadInput(
            filename=paths[0].name,
            content_type="application/pdf",
            data=paths[0].read_bytes(),
        )
    )

    result = components.batch.process_files(uploads)

    records = components.db.export_rows(run_id=result.batch_id)
    csv_path = settings.export_dir / "invoice_report.csv"
    json_path = settings.export_dir / "invoice_report.json"
    csv_path.write_text(build_csv(records), encoding="utf-8")
    json_path.write_text(
        build_json(records, run_id=result.batch_id, generated_at=utc_now()),
        encoding="utf-8",
    )

    print("Invoice Extractor - demo mode (LLM provider: mock, no external calls)")
    _print_batch_summary(settings, result)
    return 0


def _print_batch_summary(settings: Settings, result) -> None:
    print(f"Sample documents: data/demo_samples/ · batch {result.batch_id}")
    print(
        f"  total {result.total} | succeeded {result.succeeded} | "
        f"needs_review {result.needs_review} | failed {result.failed} | "
        f"duplicates {result.duplicates}"
    )
    print()
    print(f"  {'file':38s} {'status':13s} {'type':9s} detail")
    for item in result.results:
        if item.status is DocumentStatus.FAILED:
            detail = item.error_message or ""
        elif item.duplicate:
            detail = f"duplicate of {item.duplicate_of[:12]}"
        elif item.extraction is not None:
            invoice = item.extraction.invoice
            parts = [invoice.invoice_number or "-"]
            if invoice.total is not None:
                parts.append(f"total {invoice.total:.2f} {invoice.currency or ''}")
            detail = " ".join(part for part in parts if part)
        else:
            detail = (item.review_reasons or [""])[0]
        print(f"  {item.original_filename:38s} {item.status.value:13s} "
              f"{(item.document_type.value if item.document_type else '-'):9s} {detail[:52]}")
    print()
    print(f"SQLite database : {settings.database_path}")
    print(f"CSV export      : {settings.export_dir / 'invoice_report.csv'}")
    print(f"JSON export     : {settings.export_dir / 'invoice_report.json'}")
    print("Web UI          : python -m src.main --serve")
