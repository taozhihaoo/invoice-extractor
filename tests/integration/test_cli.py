"""CLI and demo mode integration tests (fully offline)."""

import json

import pytest

from src.config import Settings
from src.database import Database
from src.demo.samples import generate_demo_documents
from src.main import main
from tests.conftest import make_settings


def _run_demo(settings: Settings) -> int:
    from src.demo.runner import run_demo

    return run_demo(settings)


class TestHelpAndVersion:
    def test_help_exits_zero_and_lists_modes(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            main(["--help"])
        assert exc_info.value.code == 0
        output = capsys.readouterr().out
        assert "--demo" in output
        assert "--serve" in output
        assert "--process" in output

    def test_version_flag(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            main(["--version"])
        assert exc_info.value.code == 0
        assert capsys.readouterr().out.strip()


class TestDemo:
    def test_demo_runs_end_to_end_offline(self, tmp_path, capsys):
        settings = make_settings(tmp_path)
        exit_code = _run_demo(settings)
        assert exit_code == 0
        output = capsys.readouterr().out
        assert "mock" in output

        db = Database(settings.database_path)
        # 6 sample files + 1 duplicate upload = 7 items but 6 document rows.
        assert db.count_documents() == 6
        runs = db.list_runs()
        assert runs and runs[0]["total"] == 7

        # Expected outcome mix regardless of whether Tesseract is installed:
        run = runs[0]
        assert run["failed"] == 1  # corrupted sample
        assert run["success"] + run["needs_review"] + run["failed"] == run["total"]

        # Exports written and consistent with the database.
        csv_text = (settings.export_dir / "invoice_report.csv").read_text(encoding="utf-8")
        assert csv_text.splitlines()[0].startswith("filename,supplier,invoice_number")
        assert "INV-1001" in csv_text
        payload = json.loads(
            (settings.export_dir / "invoice_report.json").read_text(encoding="utf-8")
        )
        assert payload["count"] == db.count_documents()

    def test_demo_detects_the_duplicate(self, tmp_path):
        settings = make_settings(tmp_path)
        _run_demo(settings)
        db = Database(settings.database_path)
        rows = db.list_documents(limit=100)
        sha_values = [row["sha256"] for row in rows]
        assert len(sha_values) == len(set(sha_values))  # one row per unique file

    def test_demo_never_requires_an_api_key(self, tmp_path, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        settings = make_settings(tmp_path, llm_provider="auto", openai_api_key=None)
        assert _run_demo(settings) == 0  # would raise if OpenAI were required


class TestProcessCommand:
    @staticmethod
    def _isolate_to(tmp_path, monkeypatch):
        """Point the CLI's default Settings at a temp workspace."""
        monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "cli.db"))
        monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
        monkeypatch.setenv("EXPORT_DIR", str(tmp_path / "out"))

    def test_process_directory(self, tmp_path, capsys, monkeypatch):
        inbox = tmp_path / "input"
        generate_demo_documents(inbox)
        self._isolate_to(tmp_path, monkeypatch)
        exit_code = main(["--process", str(inbox)])
        assert exit_code == 0
        assert "total 6" in capsys.readouterr().out

    def test_process_twice_makes_duplicates_not_rework(self, tmp_path, capsys, monkeypatch):
        inbox = tmp_path / "input"
        generate_demo_documents(inbox)
        self._isolate_to(tmp_path, monkeypatch)
        assert main(["--process", str(inbox)]) == 0
        first_output = capsys.readouterr().out
        assert "duplicates 0" in first_output

        assert main(["--process", str(inbox)]) == 0
        second_output = capsys.readouterr().out
        # Every file from the first run - including the corrupt one - is now
        # a duplicate, so no extraction work is repeated.
        assert "duplicates 6" in second_output

    def test_process_missing_path_fails_cleanly(self, tmp_path, capsys):
        exit_code = main(["--process", str(tmp_path / "nope")])
        assert exit_code == 2


class TestGenSamples:
    def test_gen_samples_writes_pdfs(self, tmp_path, capsys):
        target = tmp_path / "samples"
        exit_code = main(["--gen-samples", str(target)])
        assert exit_code == 0
        pdfs = sorted(target.glob("*.pdf"))
        assert len(pdfs) == 6
        assert all(path.read_bytes().startswith(b"%PDF") for path in pdfs)
