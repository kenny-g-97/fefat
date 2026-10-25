"""How the store writes and checks its files (ADR-0019): in one step, as JSON models, and with
each partition's digest kept once beside it (step 2.5).

A partition's digest, `part.digest.json` beside `part.parquet`, holds the file's size, its
modification time in nanoseconds, and its SHA-256, all read through the one open handle that
hashed it. While the file's size and time are the digest's, a snapshot pins the digest without
reading the file; otherwise the file is hashed again. A read through a snapshot still hashes the
bytes it parses, so a file rewritten in place without a new size or time is refused, never read
as the one the snapshot pinned.
"""

import hashlib
import os
import tempfile
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from fefat.market.schema import FrozenModel
from fefat.market.snapshot import Sha256

DIGEST_SUFFIX = ".digest.json"
"""The suffix of a file's digest beside it: `part.parquet` has `part.digest.json`."""


class FileDigestRecord(FrozenModel):
    """A file's size, modification time, and SHA-256, read through one open handle."""

    size_bytes: int = Field(ge=0)
    modified_ns: int
    sha256: Sha256


def hashed(path: Path) -> FileDigestRecord:
    """The file's digest: its size and time from the handle that hashes it, so that all three
    describe one file."""
    with path.open("rb") as file:
        status = os.fstat(file.fileno())
        sha256 = hashlib.file_digest(file, "sha256").hexdigest()
    return FileDigestRecord(
        size_bytes=status.st_size, modified_ns=status.st_mtime_ns, sha256=sha256
    )


def current_digest(path: Path) -> FileDigestRecord:
    """The digest beside the file while it still describes the file, else the file's hash;
    writes nothing."""
    recorded = _recorded_digest(path)
    if recorded is None:
        return hashed(path)
    return recorded


def recorded_or_new_digest(path: Path) -> FileDigestRecord:
    """The digest beside the file while it still describes the file, else the file's hash,
    recorded beside it."""
    recorded = _recorded_digest(path)
    if recorded is None:
        return record_digest(path)
    return recorded


def record_digest(path: Path) -> FileDigestRecord:
    """Hash the file and record its digest beside it, replacing an earlier one in one step."""
    digest = hashed(path)
    write_atomically(path.with_suffix(DIGEST_SUFFIX), json_writer(digest))
    return digest


def _recorded_digest(path: Path) -> FileDigestRecord | None:
    """The digest beside the file, or None while there is none or it describes another size or
    time; a digest file that does not parse is refused."""
    digest_path = path.with_suffix(DIGEST_SUFFIX)
    if not digest_path.is_file():
        return None
    recorded = parsed_json(FileDigestRecord, digest_path.read_bytes(), str(digest_path))
    status = path.stat()
    if (recorded.size_bytes, recorded.modified_ns) != (status.st_size, status.st_mtime_ns):
        return None
    return recorded


def write_atomically(path: Path, write: Callable[[Path], object]) -> None:
    """Write through a temporary file beside the target, flush it to disk, then replace the
    target in one step (atomic on one NTFS or POSIX volume): a reader, or a power cut, sees
    the old file or the new one, never half of one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f"{path.stem}.", suffix=".tmp"
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        write(temporary)
        with temporary.open("rb+") as written:
            os.fsync(written.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def json_writer(model: BaseModel) -> Callable[[Path], object]:
    """A writer, for `write_atomically`, of the model as indented JSON ending in a newline."""
    content = model.model_dump_json(indent=2).encode() + b"\n"
    return lambda temporary: temporary.write_bytes(content)


def parsed_json[Model: BaseModel](model: type[Model], content: bytes, source: str) -> Model:
    """The model `content` holds, or a refusal that names `source`."""
    try:
        return model.model_validate_json(content)
    except ValidationError as error:
        raise ValueError(f"Expected {source} to hold a {model.__name__}, got: {error}") from error
