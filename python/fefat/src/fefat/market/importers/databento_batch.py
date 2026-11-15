"""A Databento batch download as its vendor's files describe it (`02-engine-and-data.md` §1.8,
step 1.6): the DBN data file beside `metadata.json`, the query it answers, `manifest.json`, which
lists every other file with the SHA-256 the vendor publishes for it, and `condition.json`, how
complete the vendor says each day is.

`batch_in` reads a download's folder, refusing one that is not a batch of one DBN file, and
`require_published` checks a file against its published hash before it is read. An `Original` is
a vendor's file to keep under `raw`, a batch's or a single DBN file's.
`fefat.market.importers.databento` imports what this module describes.
"""

import hashlib
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path, PurePosixPath

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from fefat.market.importers.report import BatchReport, ConditionDay, VendorCondition
from fefat.market.raw_manifest import BatchJob, checked_raw_path

PROVIDER = "databento"
"""The provider folder of Databento's datasets and raw files."""
CONDITIONS_FILE_NAME = "condition.json"
"""A batch's file of per-day conditions, which the quality report reads back from `raw`."""
DBN_SUFFIXES = (".dbn", ".dbn.zst")
"""How a DBN data file's name ends, plain or compressed with zstd."""

_VENDOR_MANIFEST = "manifest.json"
_QUERY = "metadata.json"
_JOB_ID = re.compile(r"[A-Z0-9.]+-([0-9]{4})([0-9]{2})([0-9]{2})-[A-Z0-9]+")


class VendorModel(BaseModel):
    """A value read from a vendor's file, which may carry fields the importer does not read."""

    model_config = ConfigDict(frozen=True, extra="ignore")


class BatchFile(VendorModel):
    """A file of a batch download as `manifest.json` lists it, with its published SHA-256."""

    filename: str = Field(min_length=1)
    hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    def published_sha256(self) -> str:
        return self.hash.removeprefix("sha256:")


class BatchManifest(VendorModel):
    """A batch download's `manifest.json`: its job and every other file in it."""

    job_id: str = Field(min_length=1)
    files: tuple[BatchFile, ...] = Field(min_length=1)


class BatchQuery(VendorModel):
    """A batch download's `metadata.json`, the query it answers; the importer reads its job."""

    job_id: str = Field(min_length=1)


class DayCondition(VendorModel):
    """A day of `condition.json`: how complete the vendor says its data is, and when the vendor
    last changed it."""

    day: date = Field(alias="date")
    condition: VendorCondition
    last_modified_date: date | None = None


CONDITION_DAYS = TypeAdapter(tuple[DayCondition, ...])


@dataclass(frozen=True)
class Original:
    """A vendor's file to keep under `raw`: where it is, where it goes, its SHA-256, and the
    batch job it came in."""

    source: Path
    raw_path: PurePosixPath
    sha256: str
    batch_job: BatchJob | None


@dataclass(frozen=True)
class Batch:
    """A batch download as its vendor's files describe it: one DBN file and its sidecars."""

    folder: Path
    job_id: str
    downloaded_on: date
    conditions: tuple[DayCondition, ...]
    sidecars: tuple[Original, ...]
    data_file: Original

    def revised(self) -> date | None:
        """The newest day the vendor changed any of the batch's days, if it gives one."""
        dates = [day.last_modified_date for day in self.conditions if day.last_modified_date]
        return max(dates, default=None)

    def revision(self) -> str:
        """The batch's revision as the raw manifest records it."""
        revised = self.revised()
        return "no revision date" if revised is None else f"revised {revised}"

    def report(self) -> BatchReport:
        unavailable = tuple(
            ConditionDay(day=day.day, condition=day.condition)
            for day in self.conditions
            if day.condition is not VendorCondition.AVAILABLE
        )
        return BatchReport(job_id=self.job_id, revised=self.revised(), unavailable_days=unavailable)


def batch_in(folder: Path) -> Batch:
    """The batch download in `folder`, as its sidecars describe it; its files are checked
    against the vendor's hashes only when they are about to be read."""
    manifest = _parsed(BatchManifest, folder / _VENDOR_MANIFEST)
    query = _parsed(BatchQuery, folder / _QUERY)
    if query.job_id != manifest.job_id:
        raise ValueError(
            f"Expected the job of {folder / _VENDOR_MANIFEST}, {manifest.job_id}, in "
            f"{folder / _QUERY}, got {query.job_id}."
        )
    listed = {file.filename: file for file in manifest.files}
    data_name = _data_file_name(folder, listed)
    job = manifest.job_id

    def original(name: str) -> Original:
        published = listed[name].published_sha256()
        batch_job = BatchJob(job_id=job, published_sha256=published)
        raw_path = PurePosixPath(PROVIDER, job, name)
        checked_raw_path(raw_path.as_posix())
        return Original(folder / name, raw_path, published, batch_job)

    vendor_manifest = folder / _VENDOR_MANIFEST
    return Batch(
        folder=folder,
        job_id=job,
        downloaded_on=_job_date(job),
        conditions=_condition_days(folder / CONDITIONS_FILE_NAME),
        sidecars=(
            original(_QUERY),
            original(CONDITIONS_FILE_NAME),
            Original(
                vendor_manifest,
                PurePosixPath(PROVIDER, job, _VENDOR_MANIFEST),
                sha256_of(vendor_manifest),
                None,
            ),
        ),
        data_file=original(data_name),
    )


def require_published(original: Original, folder: Path) -> None:
    """Refuse a batch's file that is missing, or whose SHA-256 is not the one the vendor's
    `manifest.json` publishes for it."""
    path = original.source
    if not path.is_file():
        raise FileNotFoundError(
            f"Expected {path}, which {folder / _VENDOR_MANIFEST} lists, got no such file."
        )
    actual = sha256_of(path)
    if actual != original.sha256:
        raise ValueError(
            f"Expected {path} to have the SHA-256 {original.sha256} that "
            f"{folder / _VENDOR_MANIFEST} publishes, got {actual}: the file differs from the "
            "vendor's; download it again."
        )


def sha256_of(path: Path) -> str:
    """The SHA-256 of the file's bytes, as 64 hex digits."""
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def _data_file_name(folder: Path, listed: dict[str, BatchFile]) -> str:
    """The batch's DBN file, once its manifest lists the query, the conditions, one DBN file,
    and nothing else."""
    data_names = sorted(name for name in listed if name.endswith(DBN_SUFFIXES))
    others = sorted(set(listed) - {_QUERY, CONDITIONS_FILE_NAME, *data_names})
    if not {_QUERY, CONDITIONS_FILE_NAME} <= set(listed) or not data_names or others:
        raise ValueError(
            f"Expected {folder / _VENDOR_MANIFEST} to list {_QUERY}, {CONDITIONS_FILE_NAME}, and "
            f"DBN files, got {', '.join(sorted(listed))}: a batch encoded in CSV or JSON arrives "
            "through `fefat data import file` (step 1.10)."
        )
    if len(data_names) > 1:
        raise ValueError(
            f"Expected one DBN file in the batch {folder}, got {len(data_names)}: "
            f"{', '.join(data_names)}. A batch split by day, month, or symbol can give two files "
            "rows of one partition, which the importer does not merge yet: order the batch "
            "with the split duration none."
        )
    return data_names[0]


def _job_date(job_id: str) -> date:
    """The day a batch job ran, which its id carries (`GLBX-20260923-KF6FGGLH79`)."""
    found = _JOB_ID.fullmatch(job_id)
    if found is None:
        raise ValueError(
            f"Expected a Databento job id <dataset>-<YYYYMMDD>-<code>, got {job_id!r}."
        )
    return date(int(found[1]), int(found[2]), int(found[3]))


def _condition_days(path: Path) -> tuple[DayCondition, ...]:
    if not path.is_file():
        raise FileNotFoundError(f"Expected the batch's {path}, got no such file.")
    try:
        return CONDITION_DAYS.validate_json(path.read_bytes())
    except ValidationError as error:
        raise ValueError(f"Expected {path} to hold Databento's conditions, got: {error}") from error


def _parsed[Model: VendorModel](model: type[Model], path: Path) -> Model:
    if not path.is_file():
        raise FileNotFoundError(f"Expected the batch's {path}, got no such file.")
    try:
        return model.model_validate_json(path.read_bytes())
    except ValidationError as error:
        raise ValueError(f"Expected {path} to hold a {model.__name__}, got: {error}") from error
