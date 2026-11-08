"""Chunked multipart upload reading with a hard size cap.

``UploadFile.read()`` without a size would pull an arbitrary upload into memory
before validation could reject it. Reading in chunks and aborting as soon as the
cap is exceeded keeps memory bounded no matter what the client sends.
"""

from __future__ import annotations

from fastapi import UploadFile

from ..errors import FileTooLargeError
from ..upload_validator import size_limit_message

CHUNK_SIZE = 64 * 1024


async def read_upload_limited(upload: UploadFile, *, max_size_bytes: int) -> bytes:
    buffer = bytearray()
    while True:
        chunk = await upload.read(CHUNK_SIZE)
        if not chunk:
            break
        buffer.extend(chunk)
        if len(buffer) > max_size_bytes:
            raise FileTooLargeError(size_limit_message(max_size_bytes))
    return bytes(buffer)
