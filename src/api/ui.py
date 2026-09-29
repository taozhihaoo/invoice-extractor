"""Server-rendered HTML UI (Jinja2).

Deliberately plain: dashboard, upload form, run results and per-document
detail pages. No JavaScript framework - the API does the work, the pages
just make it usable for non-technical users.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

from ..errors import UploadError
from ..models import DocumentResult, DocumentStatus
from ..processing import UploadInput
from ..processing.service import document_result_from_rows

router = APIRouter(tags=["ui"], include_in_schema=False)
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _money(value: object) -> str:
    if value in (None, ""):
        return ""
    return f"{float(value):,.2f}"


templates.env.filters["money"] = _money


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    comps = request.app.state.components
    db = comps.db
    rows = db.list_documents(limit=10)
    documents = [
        document_result_from_rows(row, db.get_extraction(row["id"])) for row in rows
    ]
    return templates.TemplateResponse(
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
    )


@router.get("/upload", response_class=HTMLResponse)
def upload_page(request: Request):
    comps = request.app.state.components
    return templates.TemplateResponse(
        request,
        "upload.html",
        {
            "max_upload_size_mb": comps.settings.max_upload_size_mb,
            "max_batch_files": comps.settings.max_batch_files,
        },
    )


@router.post("/upload")
async def upload_submit(
    request: Request, files: list[UploadFile] = File(...)
):
    comps = request.app.state.components
    inputs: list[UploadInput] = []
    for upload_file in files:
        data = await upload_file.read()
        inputs.append(
            UploadInput(
                filename=upload_file.filename,
                content_type=upload_file.content_type,
                data=data,
            )
        )
    try:
        result = await run_in_threadpool(comps.batch.process_files, inputs)
    except UploadError as exc:
        return templates.TemplateResponse(
            request,
            "error.html",
            {"code": exc.code, "message": exc.message},
            status_code=exc.status_code,
        )
    return RedirectResponse(url=f"/runs/{result.batch_id}/view", status_code=303)


@router.get("/documents/{document_id}/view", response_class=HTMLResponse)
def document_page(request: Request, document_id: str):
    comps = request.app.state.components
    row = comps.db.get_document(document_id)
    if row is None:
        raise HTTPException(status_code=404, detail="document not found")
    document = document_result_from_rows(row, comps.db.get_extraction(document_id))
    return templates.TemplateResponse(
        request, "document.html", {"document": document}
    )


@router.get("/runs/{run_id}/view", response_class=HTMLResponse)
def run_page(request: Request, run_id: str):
    comps = request.app.state.components
    run = comps.db.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
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

    return templates.TemplateResponse(
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
    )
