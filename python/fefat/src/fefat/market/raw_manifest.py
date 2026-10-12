"""The raw manifest: the vendors' original files under `raw`, which never change (ADR-0019).

`raw/MANIFEST.json` lists each file with its path, size, and SHA-256, its provider, the
vendor's version, the download date, and, for a vendor's batch download, the job id and the
SHA-256 the vendor published. `Store.record_raw_file` keeps it.
"""

from datetime import date
from pathlib import PurePosixPath
from typing import Annotated, Self

from pydantic import AfterValidator, Field, model_validator

from fefat.market.layout import ProviderName
from fefat.market.schema import FrozenModel
from fefat.market.snapshot import Sha256

RAW_MANIFEST_FILE_NAME = "MANIFEST.json"


def checked_raw_path(path: str) -> str:
    """A vendor file's path relative to the `raw` folder, written with `/`; a path that could
    leave the folder or name the manifest itself is refused, as is a name ending in a dot or a
    space, which Windows drops."""
    parts = PurePosixPath(path).parts
    outside = not parts or path.startswith("/") or PurePosixPath(path).as_posix() != path
    unsafe = any(
        part == ".." or ":" in part or "\\" in part or part.endswith((".", " ")) for part in parts
    )
    if outside or unsafe or path.lower() == RAW_MANIFEST_FILE_NAME.lower():
        raise ValueError(
            "Expected a vendor's file inside the raw folder, such as vendor/job/file.dbn, "
            f"got {path!r}."
        )
    return path


RawPath = Annotated[str, AfterValidator(checked_raw_path)]


class BatchJob(FrozenModel):
    """The vendor's batch job a raw file came from, with the SHA-256 the vendor published for it
    (comparing it with the file's own is the importer's check)."""

    job_id: str = Field(min_length=1)
    published_sha256: Sha256


class RawFile(FrozenModel):
    """A vendor's original file under `raw`, as the raw manifest records it."""

    path: RawPath
    size_bytes: int = Field(ge=0)
    sha256: Sha256
    provider: ProviderName
    vendor_version: str = Field(min_length=1)
    downloaded_on: date
    batch_job: BatchJob | None


class RawManifest(FrozenModel):
    """Every raw file the store has recorded, sorted by path."""

    files: tuple[RawFile, ...] = ()

    @model_validator(mode="after")
    def _records_each_path_once(self) -> Self:
        paths = [file.path for file in self.files]
        if len(paths) != len(set(paths)):
            raise ValueError(f"Expected each raw file recorded once, got the paths {paths}.")
        return self

    def file_at(self, path: str) -> RawFile | None:
        """The record of the file at the path, if the manifest has one."""
        return next((file for file in self.files if file.path == path), None)

    def with_file(self, raw_file: RawFile) -> Self:
        """The manifest with one more file recorded."""
        files = sorted((*self.files, raw_file), key=lambda file: file.path)
        return type(self)(files=tuple(files))
