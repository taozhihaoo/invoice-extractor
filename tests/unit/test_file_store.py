"""File storage unit tests."""

from src.file_store import FileStore, sha256_hex


class TestFileStore:
    def test_save_stores_exact_bytes(self, tmp_path):
        store = FileStore(tmp_path / "uploads")
        data = b"%PDF-1.7 pretend content"
        stored = store.save(data)
        assert stored.path.read_bytes() == data
        assert stored.size == len(data)

    def test_generated_names_are_uuid_pdfs(self, tmp_path):
        store = FileStore(tmp_path / "uploads")
        stored = store.save(b"%PDF-1.7 a")
        assert stored.path.parent == tmp_path / "uploads"
        assert stored.path.name.endswith(".pdf")
        assert len(stored.path.stem) == 32  # uuid4().hex

    def test_two_saves_get_distinct_names(self, tmp_path):
        store = FileStore(tmp_path / "uploads")
        first = store.save(b"%PDF-1.7 a")
        second = store.save(b"%PDF-1.7 a")
        assert first.path != second.path

    def test_sha256_matches_expected_digest(self):
        import hashlib

        data = b"hello"
        assert sha256_hex(data) == hashlib.sha256(data).hexdigest()

    def test_delete_removes_file(self, tmp_path):
        store = FileStore(tmp_path / "uploads")
        stored = store.save(b"%PDF-1.7 a")
        store.delete(stored.path)
        assert not stored.path.exists()

    def test_original_filename_never_used_for_storage(self, tmp_path):
        # Even if a caller tried, FileStore has no API that takes a filename.
        store = FileStore(tmp_path / "uploads")
        stored = store.save(b"%PDF-1.7")
        assert "../../evil" not in str(stored.path)
