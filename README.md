# AI Document Processor

A small, runnable document-processing service: upload PDFs → validate → extract
text → classify → extract invoice fields with an LLM → validate deterministically
→ store in SQLite → export CSV/JSON.

> **Independent portfolio project.** This is a personal, self-contained project
> built to demonstrate real, working software — not a client deliverable and not
> a production system.

## Overview

The system ingests invoice/receipt PDFs, pulls the text out of them (native text
layer first, optional OCR fallback), classifies each document, and for invoices
extracts a fixed set of fields (`supplier`, `invoice_number`, `invoice_date`,
`due_date`, `subtotal`, `tax`, `total`, `currency`) using LLM structured
outputs. A deterministic validation layer then checks the extracted data for
internal consistency, and anything incomplete or inconsistent is flagged for
human review instead of being silently accepted.

Everything can run fully offline: the demo and the whole test-suite use a
deterministic `MockLLMClient`, so **no OpenAI API key is required** to run,
test or evaluate this project.

## Use Case

The v1 scenario is **invoice / receipt processing**: a folder of PDF invoices
comes in, and you get back a structured, validated, exportable dataset — with
each file individually tracked as `processed`, `needs_review` or `failed`.

## Features

- **PDF upload validation** — extension, MIME type, size, empty file, PDF
  magic bytes, page-count limit, filename sanitisation
- **Text extraction** — native text via PyMuPDF; OCR fallback (Tesseract) only
  when the text yield is too low and an OCR engine is actually installed
- **Document classification** — `invoice` / `receipt` / `unknown`, deterministic
  keyword rules first, LLM only for ambiguous documents, real computed confidence
- **LLM structured extraction** — OpenAI structured outputs with a strict JSON
  schema; fields not present in the document are returned as `null`, never guessed
- **Deterministic validation** — `subtotal + tax ≈ total`, `invoice_date <= due_date`,
  computed in plain Python (Decimal), never via the LLM
- **Human review** — `needs_review` status plus explicit `review_reasons`
- **Batch processing** — per-file isolation: one broken file never stops the run;
  every batch gets a `batch_id` with `total / succeeded / failed / needs_review`
- **Duplicate detection** — SHA-256 based; an identical file re-uploaded never
  triggers a second LLM call
- **SQLite persistence** — `documents`, `extractions`, `processing_runs`;
  parameterised SQL only; schema created automatically
- **REST API + minimal HTML UI** — upload, batch, status, results, download, export
- **CSV / JSON export** — flat `invoice_report.csv` and full-structure JSON
- **Demo mode** — end-to-end offline run on synthetic sample documents
- **Tests & CI** — 173 offline tests; GitHub Actions on Python 3.11 and 3.13

## Quickstart

Requires Python 3.11+. `OPENAI_API_KEY` is optional — without it, everything
runs offline in mock mode.

```bash
# 1. create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate

# 2. install dependencies (runtime + test tooling)
pip install -r requirements-dev.txt

# 3. verify: offline tests and lint
pytest
ruff check .

# 4. run the end-to-end demo (mock LLM, no API key, no network)
python -m src.main --demo

# 5. start the API + web UI on http://127.0.0.1:8000
python -m src.main --serve
```

## Architecture

```
                 ┌──────────────────────────────────────────────────┐
 upload ────────►│ validate (ext/MIME/size/empty/magic/pages/names) │
                 └───────────────────────┬──────────────────────────┘
                                         │ safe generated name
                                         ▼
                 ┌──────────────────────────────────────────────────┐
                 │ extraction pipeline                              │
                 │  native PDF text (PyMuPDF)                       │
                 │  └─ if text < threshold: OCR fallback (optional) │
                 └───────────────────────┬──────────────────────────┘
                                         ▼
                 ┌──────────────────────────────────────────────────┐
                 │ classification: rules first, LLM fallback        │
                 └───────────────────────┬──────────────────────────┘
                                         │ if invoice
                                         ▼
                 ┌──────────────────────────────────────────────────┐
                 │ LLMClient (OpenAI │ Mock) → InvoiceData (strict) │
                 └───────────────────────┬──────────────────────────┘
                                         ▼
                 ┌──────────────────────────────────────────────────┐
                 │ deterministic validation + review reasons        │
                 └──────────────┬─────────────────────┬─────────────┘
                                ▼                     ▼
                          SQLite storage        CSV / JSON export
```

Key abstraction: business logic depends only on interfaces —
`ExtractionPipeline` (native/OCR), `LLMClient` (OpenAI/Mock) — with concrete
implementations injected in one composition root (`src/bootstrap.py`).

## Supported Documents

- **PDF only** in v1 (native text-layer PDFs are the primary target).
- Image-only ("scanned") PDFs are handled honestly: with Tesseract installed
  they go through OCR; without it they are flagged `needs_review` with the
  reason `no extractable text (OCR engine not installed)` — the system never
  pretends OCR happened.
- DOCX/XLSX/EMAIL/ZIP are out of scope for v1.

## Invoice Extraction

Extracted fields: `supplier`, `invoice_number`, `invoice_date`, `due_date`,
`subtotal`, `tax`, `total`, `currency` — via a Pydantic `InvoiceData` model:

- dates are normalised to ISO 8601 (`YYYY-MM-DD`; day-first assumed for
  `DD/MM/YYYY` — documented assumption)
- amounts are exact `Decimal` values, non-negative
- currency is an uppercase 3-letter code
- every field is nullable; **missing information is `null`, never invented**
  (enforced by schema + prompt + the deterministic mock alike)

## Validation

The deterministic validation layer (`src/validation_rules.py`, pure Python,
no LLM) checks:

- `subtotal + tax ≈ total` within a rounding tolerance (2 cents + 0.1% of total)
- `due_date` is not before `invoice_date` (when both exist)

These checks verify **internal consistency of the extracted data only**. They
do not and cannot verify that an invoice is genuine.

## Human Review

A document is marked `needs_review` with explicit `review_reasons`, e.g.:

```json
{
  "needs_review": true,
  "review_reasons": [
    "fields could not be extracted: due_date",
    "subtotal + tax (110.00) does not match total (999.00)"
  ]
}
```

Review triggers: incomplete extraction, failed consistency checks, unknown
document type, or no extractable text. The system never claims an LLM
"confirmed" the data — extraction provenance (provider, model, token usage)
is stored and shown.

## REST API

Interactive docs: `http://127.0.0.1:8000/docs` (Swagger UI).

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | status, version, active LLM provider, OCR availability |
| POST | `/documents` | upload + process one PDF (201; 200 + `duplicate: true` for repeats) |
| POST | `/documents/batch` | upload + process multiple PDFs as one run |
| GET | `/documents` | list documents (paginated) |
| GET | `/documents/{id}` | full result: fields, validation, review reasons, LLM usage |
| GET | `/documents/{id}/download` | original stored PDF |
| GET | `/runs/{run_id}` | batch summary + per-file results |
| GET | `/export/csv` | `invoice_report.csv` (optional `?run_id=`) |
| GET | `/export/json` | full structured JSON (optional `?run_id=`) |

Errors always use `{"error": {"code": ..., "message": ...}}` — 4xx for rejected
uploads, sanitised 500 for unexpected failures. Stack traces, internal paths and
provider details are never returned.

Amount fields in API JSON responses are serialised as **strings** (e.g.
`"total": "999.00"`): extracted amounts are `Decimal` values kept at full
precision instead of being rounded through floats. The JSON export
(`/export/json`) writes amounts as JSON numbers — see `src/exporters.py`.

## Web UI

Plain server-rendered pages (FastAPI + Jinja2, no JS framework):

- **Dashboard** `/` — document/run overview, provider + OCR status
- **Upload** `/upload` — multi-file PDF form → redirects to the run result page
- **Run view** `/runs/{id}/view` — per-file status table, links to exports
- **Document view** `/documents/{id}/view` — extracted fields, validation
  warnings, review reasons, download link

## CLI

```bash
python -m src.main --help          # usage
python -m src.main --demo          # offline end-to-end demo (no API key)
python -m src.main --serve         # start API + web UI
python -m src.main --process DIR   # process every PDF in a folder
python -m src.main --process FILE  # process a single PDF
python -m src.main --gen-samples D # write synthetic sample PDFs to D
```

After `pip install -e .` the same CLI is available as `document-processor`.

## Configuration

Environment variables (or a `.env` file — see `.env.example`; never committed):

| Variable | Default | Purpose |
|---|---|---|
| `LLM_PROVIDER` | `auto` | `mock` / `openai` / `auto` (auto = OpenAI only if a key exists) |
| `OPENAI_API_KEY` | — | never required for demo/tests |
| `OPENAI_MODEL` | `gpt-4o-mini` | model id for structured extraction |
| `DATABASE_PATH` | `data/processor.db` | SQLite location |
| `UPLOAD_DIR` | `data/uploads` | stored uploads |
| `EXPORT_DIR` | `output` | CSV/JSON exports |
| `MAX_UPLOAD_SIZE_MB` | `15` | per-file upload limit |
| `MAX_PDF_PAGES` | `50` | page-count limit |
| `MAX_BATCH_FILES` | `20` | files per batch |
| `MIN_NATIVE_TEXT_CHARS` | `100` | below this, OCR is attempted if available |

## Demo Mode

```bash
python -m src.main --demo
```

Requires **no API key and no network**. It generates six synthetic documents
(invented companies: *Demo Supplier Ltd.*, *Acme Paper Goods Co.*, …), processes
them as one batch — including a **duplicate** file and a **corrupted** PDF —
stores everything in SQLite, and writes `invoice_report.csv` / `.json` to
`output/`. Expected outcome: `total 7 · succeeded 3 · needs_review 3 · failed 1 ·
duplicates 1` (without Tesseract). All sample data is synthetic; no real
companies, addresses or personal data exist anywhere in this repository.

## OpenAI Integration

Implemented in `src/llm/openai_client.py`: strict JSON-schema structured
outputs, timeout, explicit retries (rate limits honour `Retry-After`, timeouts
and 5xx use exponential backoff; auth errors fail fast), error classification
into an `LLMError` hierarchy, and token-usage tracking stored per extraction.

Honest status: the integration is covered by offline tests against a fake SDK
(**all automated tests run without network**), and works end-to-end in mock
mode, but it **was not executed against the real OpenAI API in the environment
where this README was written** (no API key configured). Set `OPENAI_API_KEY`
and `LLM_PROVIDER=openai` to run it for real.

## Storage

SQLite (file-based, zero-ops) with three tables:

- `documents` — filename (sanitised), content type, size, SHA-256, status,
  document type + classification confidence, page count, extraction method,
  text length, review reasons, timestamps
- `extractions` — the 8 invoice fields, validation status + warnings,
  needs_review + reasons, LLM provider/model/token usage
- `processing_runs` — run id, start/finish, `total / success / failed / needs_review`

All statements are parameterised; the schema is created idempotently on first
use. Uploaded files are stored under generated UUID names — an untrusted
filename never becomes a filesystem path.

## Export

- **CSV** (`/export/csv`, or `output/invoice_report.csv` after demo):
  `filename, supplier, invoice_number, invoice_date, due_date, subtotal, tax,
  total, currency, document_type, status, needs_review`
- **JSON** (`/export/json`): full structured result per document, including
  validation warnings and review reasons

## Testing

173 offline tests (plus 1 optional OCR integration test that auto-skips
without Tesseract):

- unit: upload validation, filename sanitisation, file store, extraction
  pipeline (incl. OCR-fallback abstraction with fakes), classification,
  `InvoiceData` schema, deterministic validation rules, mock LLM, OpenAI
  client (retry / rate limit / timeout / auth / bad-response, fake SDK),
  SQLite layer, exporters
- integration: processing service, duplicates, batch isolation, every REST
  endpoint, safe error responses, Web UI pages, CLI + demo end-to-end

Every automated test is deterministic, offline (`LLM_PROVIDER=mock`), and needs
neither OpenAI, Tesseract, Docker, nor network access.

```bash
pytest
```

## Docker

`Dockerfile` + `docker-compose.yml` are provided (non-root user, healthcheck,
volumes for SQLite/uploads/exports, secrets injected via environment, `.env`
never baked into the image):

```bash
docker compose up --build     # API on http://localhost:8000
```

> **Honest note:** Docker was not available in the environment where this
> project was developed, so the image was **not built/verified locally**.
> The Compose setup follows the pinned `requirements.txt` and should work, but
> treat it as *prepared but not locally verified*.

For real OCR in a container you would additionally need the Tesseract binary
(`apt-get install tesseract-ocr`) — intentionally not bundled to keep the
default image small; without it, scanned PDFs are flagged for review as
described above.

## CI

`.github/workflows/ci.yml` runs on Python 3.11 and 3.13: install → `ruff check .`
→ `pytest`. CI needs **no** `OPENAI_API_KEY`, no Tesseract, no Docker, and
performs no network calls during tests.

## Security

- upload limits: size, MIME, extension, empty file, PDF magic bytes, page count
- filename sanitisation + generated storage names → path traversal is
  structurally impossible (original names are metadata only)
- parameterised SQL everywhere (whitelisted column names for updates)
- sanitised error responses: no tracebacks, no internal paths, no API keys
- API keys only via environment/`.env`; `.env`, `data/`, `uploads/`, `output/`
  are git-ignored; no real invoice/personal data in the repository
- non-root Docker user + healthcheck

Not implemented (by design, v1): authentication, multi-tenancy, rate limiting
per client, virus scanning, encryption at rest.

## Limitations

Stated plainly:

- PDF only; single-node, single SQLite file; no auth, no multi-tenancy
- OCR requires a separate Tesseract install; accuracy on real scans is
  untested (all evaluation used synthetic documents)
- OpenAI integration is implemented and unit-tested against a fake SDK, but
  was **not executed against the live API** in the development environment
- no measured accuracy claims are made anywhere — no benchmark, no "98%"
- not tested at production scale (large volumes, concurrency, huge PDFs)
- Chinese/Japanese/RTL document layouts are untested; date parsing assumes
  day-first for ambiguous numeric formats
- the Docker image was not built locally (Docker unavailable)

## Project Structure

```
src/
  main.py                CLI entry point (--demo / --serve / --process)
  config.py              settings (env / .env), provider resolution
  bootstrap.py           composition root: settings → implementations
  errors.py              user-safe domain error hierarchy
  upload_validator.py    extension/MIME/size/empty/magic/filename checks
  file_store.py          generated-name storage + SHA-256
  validation_rules.py    deterministic consistency checks + review reasons
  database.py            SQLite schema + parameterised queries
  exporters.py           CSV / JSON export builders
  models/                enums, InvoiceData, result models
  extraction/            native PDF (PyMuPDF), OCR adapter, pipeline
  classification/        weighted-keyword rules (+ LLM fallback hook)
  llm/                   LLMClient protocol, strict schemas, OpenAI + Mock
  processing/            single-document orchestration, batch runner
  api/                   FastAPI app factory, routes, Jinja2 templates
  demo/                  synthetic samples + offline demo runner
tests/
  unit/                  8 modules, offline, deterministic
  integration/           API, batch, UI, CLI/demo, processing, optional OCR
```

## License

MIT — see [LICENSE](LICENSE). Note: PyMuPDF is AGPL-3.0 licensed.
