"""Storage of uploaded files.

Files are persisted under generated names (``<uuid-hex>.pdf``); the original
filename is kept as metadata only, so untrusted input never becomes a path.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from pathlib import Path


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class StoredFile:
    path: Path
    size: int
    sha256: str


class FileStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, data: bytes) -> StoredFile:
        path = self.root / f"{uuid.uuid4().hex}.pdf"
        path.write_bytes(data)
        return StoredFile(path=path, size=len(data), sha256=sha256_hex(data))

    def exists(self, path: Path) -> bool:
        return Path(path).is_file()

    def delete(self, path: Path) -> None:
        Path(path).unlink(missing_ok=True)
