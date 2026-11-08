"""Minimal template internationalisation (English + Simplified Chinese).

The UI is server-rendered, so translation is a plain lookup table plus a
request-scoped translator injected into every template. The chosen language is
taken from ``?lang=`` first, then a cookie, then ``Accept-Language``.

Only user-visible UI strings live here - API payloads and stored data stay in
English so that exports remain machine-stable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

DEFAULT_LANGUAGE = "en"
SUPPORTED_LANGUAGES = ("en", "zh")
LANGUAGE_COOKIE = "lang"
COOKIE_MAX_AGE = 60 * 60 * 24 * 365

# key -> {"en": ..., "zh": ...}
STRINGS: dict[str, dict[str, str]] = {
    # shell ---------------------------------------------------------------
    "brand": {"en": "AI Document Processor", "zh": "AI 文档处理器"},
    "brand.tag": {"en": "Invoice intake", "zh": "发票处理"},
    "nav.dashboard": {"en": "Dashboard", "zh": "总览"},
    "nav.upload": {"en": "Upload", "zh": "上传"},
    "nav.api": {"en": "API", "zh": "API"},
    "footer.note": {
        "en": "Runs locally on SQLite · no document data leaves this machine",
        "zh": "本地运行，数据存于 SQLite · 文档不会离开本机",
    },
    # shared --------------------------------------------------------------
    "status.processed": {"en": "Processed", "zh": "已处理"},
    "status.needs_review": {"en": "Needs review", "zh": "待复核"},
    "status.failed": {"en": "Failed", "zh": "失败"},
    "status.processing": {"en": "Processing", "zh": "处理中"},
    "status.duplicate": {"en": "Duplicate", "zh": "重复文件"},
    "type.invoice": {"en": "Invoice", "zh": "发票"},
    "type.receipt": {"en": "Receipt", "zh": "收据"},
    "type.unknown": {"en": "Unknown", "zh": "未知"},
    "method.native_text": {"en": "native text", "zh": "原生文本层"},
    "method.ocr": {"en": "OCR", "zh": "OCR"},
    "method.none": {"en": "no text extracted", "zh": "未提取到文本"},
    "common.none": {"en": "—", "zh": "—"},
    "common.files": {"en": "files", "zh": "个文件"},
    "common.documents": {"en": "documents", "zh": "份文档"},
    "common.back": {"en": "Back to dashboard", "zh": "返回总览"},
    # dashboard -----------------------------------------------------------
    "dash.title": {"en": "Dashboard", "zh": "总览"},
    "dash.subtitle": {
        "en": "Every upload, its processing status and the result of the deterministic checks.",
        "zh": "每次上传的处理状态，以及确定性校验的结果。",
    },
    "dash.action.upload": {"en": "Upload documents", "zh": "上传文档"},
    "dash.stat.documents": {"en": "Documents", "zh": "文档总数"},
    "dash.stat.processed": {"en": "Processed", "zh": "已处理"},
    "dash.stat.review": {"en": "Needs review", "zh": "待复核"},
    "dash.stat.failed": {"en": "Failed", "zh": "失败"},
    "dash.stat.documents.hint": {"en": "in this workspace", "zh": "当前工作区"},
    "dash.stat.processed.hint": {"en": "validated, no review needed", "zh": "已校验，无需复核"},
    "dash.stat.review.hint": {"en": "flagged for a human", "zh": "已标记待人工确认"},
    "dash.stat.failed.hint": {"en": "rejected or unreadable", "zh": "被拒绝或无法读取"},
    "dash.recent_docs": {"en": "Recent documents", "zh": "最近文档"},
    "dash.recent_runs": {"en": "Recent batches", "zh": "最近批次"},
    "dash.empty.docs": {"en": "No documents yet", "zh": "还没有文档"},
    "dash.empty.docs.hint": {
        "en": "Upload a few PDFs and their status will show up here.",
        "zh": "上传几个 PDF，处理状态就会显示在这里。",
    },
    "dash.empty.runs": {"en": "No batches yet", "zh": "还没有批次"},
    "dash.empty.runs.hint": {
        "en": "Each upload session is recorded as one batch.",
        "zh": "每次上传会话都会记录为一个批次。",
    },
    "dash.engine": {"en": "Engine", "zh": "运行配置"},
    "dash.engine.llm": {"en": "LLM provider", "zh": "模型提供方"},
    "dash.engine.ocr": {"en": "OCR engine", "zh": "OCR 引擎"},
    "dash.engine.ocr.available": {"en": "available", "zh": "可用"},
    "dash.engine.ocr.missing": {"en": "not installed", "zh": "未安装"},
    # tables --------------------------------------------------------------
    "table.file": {"en": "File", "zh": "文件"},
    "table.type": {"en": "Type", "zh": "类型"},
    "table.amount": {"en": "Total", "zh": "金额"},
    "table.status": {"en": "Status", "zh": "状态"},
    "table.uploaded": {"en": "Uploaded (UTC)", "zh": "上传时间 (UTC)"},
    "table.run": {"en": "Batch", "zh": "批次"},
    "table.started": {"en": "Started (UTC)", "zh": "开始时间 (UTC)"},
    "table.files": {"en": "Files", "zh": "文件数"},
    "table.succeeded": {"en": "Succeeded", "zh": "成功"},
    "table.review": {"en": "Review", "zh": "待复核"},
    "table.failed": {"en": "Failed", "zh": "失败"},
    "table.detail": {"en": "Detail", "zh": "详情"},
    "table.view": {"en": "View", "zh": "查看"},
    # upload --------------------------------------------------------------
    "upload.title": {"en": "Upload documents", "zh": "上传文档"},
    "upload.subtitle": {
        "en": "PDF invoices and receipts. Every file is processed on its own, "
              "so one bad file never stops the rest.",
        "zh": "支持 PDF 发票与收据。每个文件独立处理，单个文件出错不会影响其他文件。",
    },
    "upload.drop": {"en": "Drop PDF files here", "zh": "将 PDF 拖放到这里"},
    "upload.or": {"en": "or", "zh": "或"},
    "upload.browse": {"en": "Browse files", "zh": "选择文件"},
    "upload.selected": {"en": "Selected", "zh": "已选择"},
    "upload.empty": {"en": "No files selected yet", "zh": "尚未选择文件"},
    "upload.submit": {"en": "Process files", "zh": "开始处理"},
    "upload.limits": {
        "en": "PDF only · max {size} MB per file · max {count} files per batch",
        "zh": "仅支持 PDF · 单文件最大 {size} MB · 每批最多 {count} 个文件",
    },
    "upload.dedup": {
        "en": "Identical files are detected by SHA-256 and never processed twice.",
        "zh": "相同文件通过 SHA-256 去重，不会被重复处理。",
    },
    "upload.privacy": {
        "en": "Files stay on this machine - stored under a generated name, "
              "original filename kept as metadata only.",
        "zh": "文件保存在本机，使用随机生成的文件名存储，原始文件名仅作为元数据保留。",
    },
    "upload.error.nofiles": {
        "en": "Select at least one PDF file.",
        "zh": "请至少选择一个 PDF 文件。",
    },
    "upload.error.toomany": {
        "en": "Too many files: the limit is {count} per batch.",
        "zh": "文件过多：每批最多 {count} 个。",
    },
    # run ------------------------------------------------------------------
    "run.title": {"en": "Batch result", "zh": "批次结果"},
    "run.subtitle": {
        "en": "One row per uploaded file, duplicates included.",
        "zh": "每个上传文件一行，包含重复文件。",
    },
    "run.started": {"en": "Started", "zh": "开始"},
    "run.finished": {"en": "Finished", "zh": "结束"},
    "run.export": {"en": "Export", "zh": "导出"},
    "run.export.csv": {"en": "CSV", "zh": "CSV"},
    "run.export.json": {"en": "JSON", "zh": "JSON"},
    "run.stat.total": {"en": "Files", "zh": "文件总数"},
    "run.stat.succeeded": {"en": "Succeeded", "zh": "成功"},
    "run.stat.review": {"en": "Needs review", "zh": "待复核"},
    "run.stat.failed": {"en": "Failed", "zh": "失败"},
    "run.empty": {"en": "This batch recorded no files.", "zh": "该批次没有记录任何文件。"},
    # document -------------------------------------------------------------
    "doc.fields": {"en": "Extracted invoice fields", "zh": "提取的发票字段"},
    "doc.supplier": {"en": "Supplier", "zh": "供应商"},
    "doc.invoice_number": {"en": "Invoice number", "zh": "发票号"},
    "doc.invoice_date": {"en": "Invoice date", "zh": "开票日期"},
    "doc.due_date": {"en": "Due date", "zh": "到期日"},
    "doc.subtotal": {"en": "Subtotal", "zh": "小计"},
    "doc.tax": {"en": "Tax", "zh": "税额"},
    "doc.total": {"en": "Total", "zh": "合计"},
    "doc.currency": {"en": "Currency", "zh": "币种"},
    "doc.no_fields": {
        "en": "No invoice fields were extracted for this document.",
        "zh": "该文档未提取到发票字段。",
    },
    "doc.validation": {"en": "Deterministic validation", "zh": "确定性校验"},
    "doc.validation.passed": {
        "en": "Passed: subtotal + tax matches the total and the dates are in order.",
        "zh": "通过：小计 + 税额等于合计，日期顺序正确。",
    },
    "doc.validation.warn": {"en": "Warning", "zh": "警告"},
    "doc.validation.scope": {
        "en": "These checks verify internal consistency of the extracted numbers "
              "only - they cannot prove an invoice is genuine.",
        "zh": "以上校验只针对提取数值的内部一致性，无法证明发票本身真实有效。",
    },
    "doc.review": {"en": "Review reasons", "zh": "复核原因"},
    "doc.provenance": {"en": "Extraction provenance", "zh": "提取来源"},
    "doc.provider": {"en": "Provider", "zh": "提供方"},
    "doc.model": {"en": "Model", "zh": "模型"},
    "doc.tokens": {"en": "Tokens", "zh": "Token 用量"},
    "doc.tokens.value": {
        "en": "{prompt} prompt + {completion} completion",
        "zh": "{prompt} 输入 + {completion} 输出",
    },
    "doc.meta": {"en": "Document", "zh": "文档信息"},
    "doc.type": {"en": "Document type", "zh": "文档类型"},
    "doc.classification": {
        "en": "{method} · confidence {confidence}",
        "zh": "{method} · 置信度 {confidence}",
    },
    "doc.pages": {"en": "Pages", "zh": "页数"},
    "doc.pages.one": {"en": " page", "zh": " 页"},
    "doc.pages.many": {"en": " pages", "zh": " 页"},
    "doc.method": {"en": "Extraction method", "zh": "提取方式"},
    "doc.text_length": {"en": "Text length", "zh": "文本长度"},
    "doc.text_length.value": {"en": "{count} characters", "zh": "{count} 字符"},
    "doc.file_size": {"en": "File size", "zh": "文件大小"},
    "doc.file_size.value": {"en": "{kb} KB", "zh": "{kb} KB"},
    "doc.sha": {"en": "SHA-256", "zh": "SHA-256"},
    "doc.uploaded": {"en": "Uploaded", "zh": "上传时间"},
    "doc.download": {"en": "Download original PDF", "zh": "下载原始 PDF"},
    "doc.duplicate_of": {"en": "Duplicate of {id}", "zh": "{id} 的重复文件"},
    "doc.rejected": {
        "en": "This upload was rejected before processing.",
        "zh": "该上传在处理前已被拒绝。",
    },
    # error ---------------------------------------------------------------
    "error.title": {"en": "Request rejected", "zh": "请求被拒绝"},
    "error.subtitle": {
        "en": "The request could not be completed. Nothing was stored.",
        "zh": "请求未能完成，未保存任何数据。",
    },
    "error.code": {"en": "Error code", "zh": "错误码"},
    "error.back": {"en": "Back to upload", "zh": "返回上传"},
    "error.retry": {"en": "Try again", "zh": "重试"},
    "error.not_found": {
        "en": "This document or batch does not exist (any more).",
        "zh": "该文档或批次不存在（或已被删除）。",
    },
}


def normalise_language(value: str | None) -> str | None:
    if not value:
        return None
    tag = value.strip().split(";", 1)[0].strip().lower().replace("_", "-")
    if tag.startswith("zh"):
        return "zh"
    if tag.startswith("en"):
        return "en"
    return None


@dataclass(frozen=True)
class Translator:
    """Callable used from templates: ``{{ t("nav.upload") }}``."""

    lang: str

    def __call__(self, key: str, **values: Any) -> str:
        entry = STRINGS.get(key)
        if entry is None:
            return key
        text = entry.get(self.lang) or entry[DEFAULT_LANGUAGE]
        if not values:
            return text
        try:
            return text.format(**values)
        except (KeyError, IndexError):
            return text

    def __getitem__(self, key: str) -> str:
        return self(key)


def resolve_language(request: Any) -> str:
    """Query parameter wins, then cookie, then Accept-Language, then default."""
    from_query = normalise_language(request.query_params.get(LANGUAGE_COOKIE))
    if from_query:
        return from_query
    from_cookie = normalise_language(request.cookies.get(LANGUAGE_COOKIE))
    if from_cookie:
        return from_cookie
    header = request.headers.get("accept-language")
    if header:
        for part in header.split(","):
            from_header = normalise_language(part)
            if from_header:
                return from_header
    return DEFAULT_LANGUAGE


def translator_for(request: Any) -> Translator:
    lang = getattr(request.state, "lang", None) or resolve_language(request)
    return Translator(lang=lang)


def language_switcher(lang: str) -> list[dict[str, str]]:
    labels = {"en": "EN", "zh": "中文"}
    return [
        {"code": code, "label": labels[code], "active": code == lang}
        for code in SUPPORTED_LANGUAGES
    ]
