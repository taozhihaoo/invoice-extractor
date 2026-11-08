"""Server-rendered HTML UI (Jinja2).

Dashboard, upload form, batch results and per-document detail pages. No
JavaScript framework: the API does the work, the templates make it usable for
non-technical users. Every visible string comes from :mod:`src.api.i18n`, so
the same page renders in English or Simplified Chinese depending on the
``lang`` query parameter / cookie / ``Accept-Language`` header.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

from .. import __version__
from ..errors import DocumentProcessorError
from ..models import DocumentResult, DocumentStatus
from ..processing import UploadInput
from ..processing.service import document_result_from_rows
from .i18n import language_switcher, translator_for
from .uploads import read_upload_limited

router = APIRouter(tags=["ui"], include_in_schema=False)
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _money(value: object) -> str:
    if value in (None, ""):
        return ""
    return f"{float(value):,.2f}"


def _stamp(value: Any) -> str:
    """Render an ISO-8601 UTC timestamp as ``YYYY-MM-DD HH:MM``."""
    if not value:
        return "—"
    text = str(value)
    try:
        return datetime.fromisoformat(text).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return text[:16]


def _filesize(value: Any) -> str:
    if value in (None, ""):
        return "—"
    size = float(value)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


templates.env.filters["money"] = _money
templates.env.filters["stamp"] = _stamp
templates.env.filters["filesize"] = _filesize


def _render(
    request: Request,
    template: str,
    context: dict[str, Any] | None = None,
    *,
    active: str = "",
    status_code: int = 200,
):
    translator = translator_for(request)
    return templates.TemplateResponse(
        request,
        template,
        {
            "t": translator,
            "lang": translator.lang,
            "languages": language_switcher(translator.lang),
            "version": __version__,
            "active": active,
            **(context or {}),
        },
        status_code=status_code,
    )


def _error_page(
    request: Request, code: str, message: str, *, status_code: int = 400, active: str = ""
):
    return _render(
        request,
        "error.html",
        {"code": code, "message": message},
        active=active,
        status_code=status_code,
    )


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    comps = request.app.state.components
    db = comps.db
    rows = db.list_documents(limit=10)
    documents = [
        document_result_from_rows(row, db.get_extraction(row["id"])) for row in rows
    ]
    return _render(
        request,
        "dashboard.html",
        {
            "total_documents": db.count_documents(),
            "counts": db.count_documents_by_status(),
            "documents": documents,
            "runs": db.list_runs(limit=5),
            "ocr_available": comps.ocr_available,
            "llm_provider": comps.llm_provider,
        },
        active="dashboard",
    )


@router.get("/upload", response_class=HTMLResponse)
def upload_page(request: Request):
    comps = request.app.state.components
    return _render(
        request,
        "upload.html",
        {
            "max_upload_size_mb": comps.settings.max_upload_size_mb,
            "max_batch_files": comps.settings.max_batch_files,
        },
        active="upload",
    )


@router.post("/upload")
async def upload_submit(request: Request, files: list[UploadFile] = File(default=[])):
    comps = request.app.state.components
    t = translator_for(request)

    if not files:
        return _error_page(
            request, "empty_file", t("upload.error.nofiles"), status_code=422, active="upload"
        )
    if len(files) > comps.settings.max_batch_files:
        return _error_page(
            request,
            "too_many_files",
            t("upload.error.toomany", count=comps.settings.max_batch_files),
            status_code=413,
            active="upload",
        )

    try:
        inputs: list[UploadInput] = []
        for upload_file in files:
            inputs.append(
                UploadInput(
                    filename=upload_file.filename,
                    content_type=upload_file.content_type,
                    data=await read_upload_limited(
                        upload_file, max_size_bytes=comps.settings.max_upload_size_bytes
                    ),
                )
            )
        result = await run_in_threadpool(comps.batch.process_files, inputs)
    except DocumentProcessorError as exc:
        return _error_page(
            request, exc.code, exc.message, status_code=exc.status_code, active="upload"
        )
    return RedirectResponse(url=f"/runs/{result.batch_id}/view", status_code=303)


@router.get("/documents/{document_id}/view", response_class=HTMLResponse)
def document_page(request: Request, document_id: str):
    comps = request.app.state.components
    row = comps.db.get_document(document_id)
    if row is None:
        return _error_page(
            request,
            "not_found",
            translator_for(request)("error.not_found"),
            status_code=404,
            active="dashboard",
        )
    document = document_result_from_rows(row, comps.db.get_extraction(document_id))
    return _render(
        request, "document.html", {"document": document}, active="dashboard"
    )


@router.get("/runs/{run_id}/view", response_class=HTMLResponse)
def run_page(request: Request, run_id: str):
    comps = request.app.state.components
    run = comps.db.get_run(run_id)
    if run is None:
        return _error_page(
            request,
            "not_found",
            translator_for(request)("error.not_found"),
            status_code=404,
            active="dashboard",
        )
    rows = comps.db.list_run_documents(run_id)
    by_id = {
        row["id"]: document_result_from_rows(row, comps.db.get_extraction(row["id"]))
        for row in rows
    }
    documents: list[DocumentResult] = list(by_id.values())

    # Duplicates have no document row of their own (by design). The batch
    # manifest recorded on the run lets the table show every upload anyway.
    for entry in json.loads(run.get("uploads_json") or "[]"):
        listed = by_id.get(entry["document_id"])
        if listed is not None and not entry.get("duplicate"):
            continue  # this upload produced its own document row, already listed
        if listed is not None:
            # Duplicate of a document created earlier in this same batch.
            documents.append(
                listed.model_copy(
                    update={
                        "duplicate": True,
                        "original_filename": entry.get("original_filename")
                        or listed.original_filename,
                    }
                )
            )
            continue
        original = comps.db.get_document(entry["document_id"])
        if original is not None:
            result = document_result_from_rows(
                original,
                comps.db.get_extraction(entry["document_id"]),
                duplicate=True,
            )
            # Show the name this run uploaded, not the original document's name.
            result.original_filename = (
                entry.get("original_filename") or result.original_filename
            )
            documents.append(result)
        else:
            documents.append(
                DocumentResult(
                    document_id=entry["document_id"],
                    original_filename=entry.get("original_filename") or "upload.pdf",
                    status=DocumentStatus.FAILED,
                    file_size=0,
                    sha256="",
                    duplicate=True,
                    run_id=run_id,
                    error_message="original document record is no longer available",
                )
            )

    return _render(
        request,
        "run.html",
        {
            "run_id": run_id,
            "started_at": run["started_at"],
            "finished_at": run.get("finished_at"),
            "total": run["total"],
            "succeeded": run["success"],
            "failed": run["failed"],
            "needs_review": run["needs_review"],
            "documents": documents,
        },
        active="dashboard",
    )
