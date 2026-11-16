"""The files the browser sends for an import (step 5.12, D-93), kept under the workspace's uploads
(`fefat_app.ports.UploadRecords`): a folder each, named by a random id, holding the file under its
own name and `upload.json`, its name, size, SHA-256, and arrival, written last, so that a file
whose chunks stopped short is never taken for whole. The disk's work runs in a thread, so that the
event loop serves the app's other requests while a file arrives. The import job removes the
folder once its import has written, since the copy under `raw/user/` is then the import's record,
and `fefat up` removes those older than a day but those of imports still queued
(`fefat_app.executor.runner_process.leftovers_removed`)."""

import asyncio
import hashlib
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import ValidationError

from fefat.market.store_files import write_atomically
from fefat_app.executor.runner_process import removed
from fefat_app.imports import (
    UPLOAD_RECORD_NAME,
    NoSuchUploadError,
    UploadedFile,
    UploadRefusedError,
)
from fefat_app.ports import Clock


@dataclass(frozen=True)
class UploadFolders:
    """`UploadRecords` in `folder`, the workspace's uploads, stamped by `clock`."""

    folder: Path
    clock: Clock

    async def keep(self, name: str, chunks: AsyncIterator[bytes]) -> UploadedFile:
        upload_id = uuid4()
        kept = self.folder / str(upload_id)
        await asyncio.to_thread(kept.mkdir, parents=True)
        try:
            size, sha256 = await _written(kept / name, chunks)
            if size == 0:
                raise UploadRefusedError(
                    f"Expected a file of at least one byte, got {name!r} empty: choose the file "
                    "the platform exported."
                )
            uploaded = UploadedFile(
                id=upload_id, name=name, size=size, sha256=sha256, uploaded_at=self.clock()
            )
            record = uploaded.model_dump_json().encode()
            await asyncio.to_thread(
                write_atomically,
                kept / UPLOAD_RECORD_NAME,
                lambda temporary: temporary.write_bytes(record),
            )
        except BaseException:
            await asyncio.to_thread(removed, kept)
            raise
        return uploaded

    def path_of(self, upload_id: UUID) -> Path:
        kept = self.folder / str(upload_id)
        try:
            uploaded = UploadedFile.model_validate_json((kept / UPLOAD_RECORD_NAME).read_bytes())
        except (OSError, ValidationError) as missing:
            raise NoSuchUploadError(upload_id) from missing
        file = kept / uploaded.name
        if uploaded.id != upload_id or file.parent != kept or not file.is_file():
            raise NoSuchUploadError(upload_id)
        return file

    def remove(self, upload_id: UUID) -> None:
        removed(self.folder / str(upload_id))


async def _written(path: Path, chunks: AsyncIterator[bytes]) -> tuple[int, str]:
    """Write `chunks` to the new file `path` in a thread, hashing them as they come; their size
    and SHA-256."""
    digest = hashlib.sha256()
    size = 0
    file = await asyncio.to_thread(path.open, "xb")
    try:
        async for chunk in chunks:
            await asyncio.to_thread(file.write, chunk)
            digest.update(chunk)
            size += len(chunk)
    finally:
        await asyncio.to_thread(file.close)
    return size, digest.hexdigest()
