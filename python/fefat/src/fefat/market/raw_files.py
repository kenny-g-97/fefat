"""The vendors' original files under the store's `raw` folder, which never change, and their
manifest (ADR-0019, `fefat.market.raw_manifest`): a file is copied in once its copy has the
SHA-256 stated, recorded with its size, SHA-256, and vendor details, and read back only while its
bytes are the ones recorded. A store's are `Store.raw`:

    store.raw.write(path, source, sha256)
    store.raw.record(path, provider=..., vendor_version=..., downloaded_on=..., batch_job=...,
                     imported_on=..., roots=...)
    store.raw.read(path)
"""

import hashlib
import shutil
from collections.abc import Callable
from datetime import date
from pathlib import Path, PurePosixPath

from fefat.market.layout import RAW_FOLDER_NAME
from fefat.market.raw_manifest import (
    RAW_MANIFEST_FILE_NAME,
    BatchJob,
    RawFile,
    RawManifest,
    checked_raw_path,
)
from fefat.market.store_files import hashed, json_writer, parsed_json, write_atomically


class RawFiles:
    """The vendors' files of one store folder, under its `raw` folder."""

    def __init__(self, store_folder: Path) -> None:
        self._folder = store_folder / RAW_FOLDER_NAME

    def manifest(self) -> RawManifest:
        """The raw manifest; empty until the first raw file is recorded."""
        path = self._manifest_path()
        if not path.is_file():
            return RawManifest()
        return parsed_json(RawManifest, path.read_bytes(), str(path))

    def write(self, path: PurePosixPath, source: Path, sha256: str) -> None:
        """Copy a vendor's file to `raw/<path>` in one step, once the copy's SHA-256 is the
        one stated, replacing a copy an interrupted import left behind. A path the raw manifest
        records is refused, since raw files never change; record the copy with `record` once it
        is imported."""
        relative = checked_raw_path(path.as_posix())
        if self.manifest().file_at(relative) is not None:
            raise ValueError(
                f"Expected a raw file the manifest {self._manifest_path()} does not record, "
                f"got {relative}, which it records: raw files never change."
            )
        write_atomically(self._folder / relative, _verified_copy(source, sha256))

    def read(self, path: PurePosixPath) -> bytes:
        """The bytes of a raw file the manifest records, refused when they no longer match its
        recorded SHA-256."""
        relative = checked_raw_path(path.as_posix())
        recorded = self.manifest().file_at(relative)
        if recorded is None:
            raise FileNotFoundError(
                f"Expected {relative} in the raw manifest {self._manifest_path()}, got no "
                "such entry."
            )
        content = self._vendor_file(relative).read_bytes()
        actual = hashlib.sha256(content).hexdigest()
        if actual != recorded.sha256:
            raise ValueError(
                f"Expected the raw file {relative} with its recorded SHA-256 {recorded.sha256}, "
                f"got {actual}: raw files never change."
            )
        return content

    def record(
        self,
        path: PurePosixPath,
        provider: str,
        vendor_version: str,
        downloaded_on: date,
        batch_job: BatchJob | None,
        imported_on: date,
        roots: tuple[str, ...],
    ) -> RawFile:
        """Record a vendor's file under `raw` in the raw manifest, with its size and SHA-256,
        the day it was imported, and the roots its records fed.

        Recording the same file again changes nothing. Raw files are immutable, so a recorded
        file whose bytes or details changed is refused: a vendor's re-normalised history
        arrives as a new file."""
        relative = checked_raw_path(path.as_posix())
        digest = hashed(self._vendor_file(relative))
        raw_file = RawFile(
            path=relative,
            size_bytes=digest.size_bytes,
            sha256=digest.sha256,
            provider=provider,
            vendor_version=vendor_version,
            downloaded_on=downloaded_on,
            batch_job=batch_job,
            imported_on=imported_on,
            roots=roots,
        )
        manifest = self.manifest()
        recorded = manifest.file_at(relative)
        if recorded is None:
            write_atomically(self._manifest_path(), json_writer(manifest.with_file(raw_file)))
            return raw_file
        if recorded != raw_file:
            raise ValueError(
                f"Expected the raw file {relative} as {self._manifest_path()} records it, "
                f"since raw files are immutable: recorded {recorded.model_dump_json()}, got "
                f"{raw_file.model_dump_json()}."
            )
        return recorded

    def _vendor_file(self, relative: str) -> Path:
        """The vendor's file under `raw`, refused when it is missing or when it is the manifest
        under another name, such as a hard link or a short 8.3 name."""
        file = self._folder / relative
        if not file.is_file():
            raise FileNotFoundError(f"Expected the raw file {file}, got no such file.")
        manifest = self._manifest_path()
        if manifest.is_file() and file.samefile(manifest):
            raise ValueError(
                f"Expected a vendor's file inside the raw folder, got {relative!r}, another name "
                "of the raw manifest."
            )
        return file

    def _manifest_path(self) -> Path:
        return self._folder / RAW_MANIFEST_FILE_NAME


def _verified_copy(source: Path, sha256: str) -> Callable[[Path], object]:
    def copy(temporary: Path) -> None:
        shutil.copyfile(source, temporary)
        copied = hashed(temporary).sha256
        if copied != sha256:
            raise ValueError(
                f"Expected the copy of {source} to have the SHA-256 {sha256}, got {copied}."
            )

    return copy
