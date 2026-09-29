"""Command line entry point.

    python -m src.main --demo          offline demo (mock LLM, no API key)
    python -m src.main --serve         start the HTTP API + web UI
    python -m src.main --process PATH  process a PDF file or a directory of PDFs
    python -m src.main --gen-samples D write synthetic sample PDFs to D
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .config import Settings, get_settings
from .errors import ConfigurationError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="document-processor",
        description="AI Document Processor - PDF ingestion, text extraction, "
        "classification, LLM structured invoice extraction, validation and export.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--demo",
        action="store_true",
        help="run the offline demo end-to-end (mock LLM, no API key required)",
    )
    mode.add_argument(
        "--serve", action="store_true", help="start the HTTP API and web UI"
    )
    mode.add_argument(
        "--process",
        metavar="PATH",
        help="process a single PDF file or a directory of PDF files",
    )
    mode.add_argument(
        "--gen-samples",
        metavar="DIR",
        help="write synthetic sample invoice PDFs to DIR and exit",
    )
    parser.add_argument("--host", default=None, help="bind host for --serve")
    parser.add_argument("--port", type=int, default=None, help="bind port for --serve")
    parser.add_argument(
        "--provider",
        choices=["mock", "openai", "auto"],
        default=None,
        help="override LLM_PROVIDER (default: env/auto)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings: Settings = get_settings()
    if args.provider:
        settings = settings.model_copy(update={"llm_provider": args.provider})

    try:
        if args.demo:
            from .demo.runner import run_demo

            return run_demo(settings)

        if args.serve:
            import uvicorn

            from .api.app import create_app

            settings.ensure_dirs()
            uvicorn.run(
                create_app(settings),
                host=args.host or settings.app_host,
                port=args.port or settings.app_port,
                log_level="info",
            )
            return 0

        if args.process:
            return _process_path(Path(args.process), settings)

        if args.gen_samples is not None:
            from .demo.samples import generate_demo_documents

            paths = generate_demo_documents(Path(args.gen_samples))
            print(f"Wrote {len(paths)} synthetic sample documents to {paths[0].parent}")
            return 0

        build_parser().print_help()
        return 0
    except ConfigurationError as exc:
        print(f"error: {exc.message}", file=sys.stderr)
        return 2


def _process_path(path: Path, settings: Settings) -> int:
    if not path.exists():
        print(f"error: path does not exist: {path}", file=sys.stderr)
        return 2

    files = [path] if path.is_file() else sorted(path.glob("*.pdf"))
    if not files:
        print(f"error: no PDF files found in {path}", file=sys.stderr)
        return 2

    from .bootstrap import build
    from .demo.runner import _print_batch_summary  # shared formatter
    from .processing import UploadInput

    components = build(settings)
    uploads = [
        UploadInput(
            filename=pdf_path.name,
            content_type="application/pdf",
            data=pdf_path.read_bytes(),
        )
        for pdf_path in files
    ]
    result = components.batch.process_files(uploads)
    _print_batch_summary(settings, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
