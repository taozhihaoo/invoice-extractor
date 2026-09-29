"""FastAPI application factory.

Error responses always use the shape
``{"error": {"code": ..., "message": ...}}``; stack traces, internal paths and
provider details never reach the client (unexpected errors are logged, not
returned).
"""

from __future__ import annotations

import logging
from functools import partial
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

from .. import __version__
from ..bootstrap import build
from ..config import Settings, get_settings
from ..database import utc_now
from ..errors import BatchTooLargeError, DocumentProcessorError, UploadError
from ..exporters import build_csv, build_json
from ..models import BatchResult, DocumentResult, RunDetail
from ..processing import UploadInput
from ..processing.service import document_result_from_rows
from ..upload_validator import validate_upload
from .schemas import DocumentListResponse, HealthResponse
from .ui import router as ui_router

logger = logging.getLogger("document_processor")


def _error_body(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    components = build(settings)

    app = FastAPI(
        title="AI Document Processor",
        version=__version__,
        description=(
            "Upload PDFs, extract text (native + optional OCR), classify documents, "
            "extract invoice fields via LLM structured outputs, validate deterministically, "
            "persist to SQLite and export CSV/JSON."
        ),
    )
    app.state.components = components

    # -- error handling -----------------------------------------------------

    @app.exception_handler(UploadError)
    async def handle_upload_error(_: Request, exc: UploadError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(exc.code, exc.message),
        )

    @app.exception_handler(DocumentProcessorError)
    async def handle_domain_error(
        _: Request, exc: DocumentProcessorError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(exc.code, exc.message),
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(
        _: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(f"http_{exc.status_code}", str(exc.detail)),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation(
        _: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=_error_body("validation_error", "request failed validation"),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error while serving request")
        return JSONResponse(
            status_code=500,
            content=_error_body("internal_error", "An unexpected error occurred."),
        )

    # -- system -------------------------------------------------------------

    @app.get("/health", response_model=HealthResponse, tags=["system"])
    def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            version=__version__,
            llm_provider=components.llm_provider,
            ocr_available=components.ocr_available,
        )

    # -- documents ----------------------------------------------------------

    @app.post("/documents", response_model=DocumentResult, tags=["documents"])
    async def upload_document(
        response: Response, file: UploadFile = File(...)
    ) -> DocumentResult:
        data = await file.read()
        # HTTP-level validation first: invalid single uploads are rejected with
        # 4xx and never create a document record (batch runs record everything).
        validate_upload(
            filename=file.filename,
            content_type=file.content_type,
            data=data,
            max_size_bytes=components.settings.max_upload_size_bytes,
        )
        result = await run_in_threadpool(
            partial(
                components.batch.process_one,
                UploadInput(
                    filename=file.filename,
                    content_type=file.content_type,
                    data=data,
                ),
            )
        )
        response.status_code = 200 if result.duplicate else 201
        return result

    @app.post("/documents/batch", response_model=BatchResult, tags=["documents"])
    async def upload_documents_batch(
        files: list[UploadFile] = File(...)
    ) -> BatchResult:
        if len(files) > components.settings.max_batch_files:
            raise BatchTooLargeError(
                f"batch of {len(files)} files exceeds the maximum of "
                f"{components.settings.max_batch_files}"
            )
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
        return await run_in_threadpool(components.batch.process_files, inputs)

    @app.get("/documents", response_model=DocumentListResponse, tags=["documents"])
    def list_documents(
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ) -> DocumentListResponse:
        rows = components.db.list_documents(limit=limit, offset=offset)
        items = [
            document_result_from_rows(row, components.db.get_extraction(row["id"]))
            for row in rows
        ]
        return DocumentListResponse(total=components.db.count_documents(), items=items)

    @app.get("/documents/{document_id}", response_model=DocumentResult, tags=["documents"])
    def get_document(document_id: str) -> DocumentResult:
        row = components.db.get_document(document_id)
        if row is None:
            raise HTTPException(status_code=404, detail="document not found")
        return document_result_from_rows(
            row, components.db.get_extraction(document_id)
        )

    @app.get("/documents/{document_id}/download", tags=["documents"])
    def download_document(document_id: str) -> FileResponse:
        row = components.db.get_document(document_id)
        path = Path(row["storage_path"]) if row and row.get("storage_path") else None
        if path is None or not path.is_file():
            raise HTTPException(status_code=404, detail="document file not available")
        return FileResponse(
            path, media_type="application/pdf", filename=row["original_filename"]
        )

    # -- runs ---------------------------------------------------------------

    @app.get("/runs/{run_id}", response_model=RunDetail, tags=["runs"])
    def get_run(run_id: str) -> RunDetail:
        run = components.db.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        rows = components.db.list_run_documents(run_id)
        documents = [
            document_result_from_rows(row, components.db.get_extraction(row["id"]))
            for row in rows
        ]
        return RunDetail(
            run_id=run["run_id"],
            started_at=run["started_at"],
            finished_at=run.get("finished_at"),
            total=run["total"],
            succeeded=run["success"],
            failed=run["failed"],
            needs_review=run["needs_review"],
            documents=documents,
        )

    # -- export ---------------------------------------------------------------

    @app.get("/export/csv", tags=["export"])
    def export_csv(run_id: str | None = Query(default=None)) -> Response:
        records = components.db.export_rows(run_id)
        return Response(
            content=build_csv(records),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="invoice_report.csv"'},
        )

    @app.get("/export/json", tags=["export"])
    def export_json(run_id: str | None = Query(default=None)) -> Response:
        records = components.db.export_rows(run_id)
        return Response(
            content=build_json(records, run_id=run_id, generated_at=utc_now()),
            media_type="application/json",
            headers={"Content-Disposition": 'attachment; filename="invoice_report.json"'},
        )

    app.include_router(ui_router)
    return app
