"""Snapshots: the files a request read, pinned by their content (ADR-0009, ADR-0019).

A snapshot names a dataset's `dataset.json` and the partitions a request selected, each
with its SHA-256, and one hash over all of them: the SHA-256 of their `sha256sum` listing,
one line `<sha256>  <path>` per file, sorted by path, each ending in a newline, which any
language can reproduce. The hash names the files; the rows read from them also depend on
the request's dates, so whatever keys on a snapshot (a run, a cache) keys on its request
too. `Store.snapshot` takes one, and `Store.read` reads exactly what it pinned.
"""

import hashlib
from collections.abc import Iterable
from pathlib import PurePosixPath
from typing import Annotated, Self

from pydantic import Field, StringConstraints, model_validator

from fefat.market.layout import Partition, PartitionRequest
from fefat.market.schema import FrozenModel

Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
"""A SHA-256 digest as 64 lowercase hex digits, without a prefix such as `sha256:`."""


class FileDigest(FrozenModel):
    """A file a snapshot pins: its path relative to the store folder, written with `/` on every
    system, its size, and its SHA-256."""

    path: str
    size_bytes: int = Field(ge=0)
    sha256: Sha256


def _listing_sha256(files: Iterable[FileDigest]) -> str:
    ordered = sorted(files, key=lambda file: file.path)
    listing = "".join(f"{file.sha256}  {file.path}\n" for file in ordered)
    return hashlib.sha256(listing.encode()).hexdigest()


class Snapshot(FrozenModel):
    """What a request read, pinned by content, so that a run names exactly its data. A snapshot
    read back from a run's record is checked: its files are its dataset's metadata and the
    partitions its request selects, and its hash covers them."""

    request: PartitionRequest
    metadata: FileDigest
    partitions: tuple[FileDigest, ...] = Field(min_length=1)
    sha256: Sha256

    @classmethod
    def of(
        cls, request: PartitionRequest, metadata: FileDigest, partitions: tuple[FileDigest, ...]
    ) -> Self:
        """The snapshot of the files, with its hash computed."""
        sha256 = _listing_sha256((metadata, *partitions))
        return cls(request=request, metadata=metadata, partitions=partitions, sha256=sha256)

    @model_validator(mode="after")
    def _pins_what_its_request_selects(self) -> Self:
        metadata_path = self.request.dataset.metadata_path().as_posix()
        if self.metadata.path != metadata_path:
            raise ValueError(f"Expected the metadata {metadata_path}, got {self.metadata.path}.")
        paths = [file.path for file in self.partitions]
        if paths != sorted(set(paths)):
            raise ValueError(f"Expected the partitions sorted by path, each once, got {paths}.")
        unselected = [
            path
            for path in paths
            if not self.request.selects(Partition.from_relative_path(PurePosixPath(path)))
        ]
        if unselected:
            raise ValueError(f"Expected only partitions its request selects, got {unselected}.")
        expected = _listing_sha256((self.metadata, *self.partitions))
        if self.sha256 != expected:
            raise ValueError(
                f"Expected the snapshot hash {expected} of its files, got {self.sha256}."
            )
        return self
