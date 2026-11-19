"""Deleting a provider's data of a root over the API (step 5.18, ADR-0023): what a delete removes,
with how many saved runs read the data, and the delete itself, through the SDK
(`fefat.market.stored_deletion`). A delete is refused while a job is queued or running, since a
job could read or write the data it removes, and while an import from a terminal writes or a file
is held open; asking again once they are done finishes it."""

from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from pydantic import BaseModel, ConfigDict

from fefat.backtest.saved_runs import runs_that_read
from fefat.market.calendar import counted
from fefat.market.store import Store
from fefat.market.stored_deletion import (
    DeleteRefusedError,
    NoStoredDataError,
    StoredDataDeletion,
    delete_stored_data,
    planned_deletion,
)
from fefat_app.services.jobs import Jobs


class DeletionPreview(BaseModel):
    """What a delete of a provider's data of a root removes, as its dataset's page says it before
    it asks: how many of FEAT's copies of the files it was imported from go, so that those files
    import again as new; the names of the files kept, since each also holds another root still
    stored; whether its quality report goes; and how many saved runs read the data, which keep
    their records and results but can no longer be explained or checked again."""

    model_config = ConfigDict(frozen=True)

    provider: str
    root: str
    imported_files: int
    kept_files: tuple[str, ...]
    quality_report: bool
    saved_runs: int


class NoSuchStoredDataError(ValueError):
    """A provider and root of which the store holds no data, in the words of the SDK's refusal
    (`NoStoredDataError`)."""


class DeletionRefusedError(ValueError):
    """A delete refused for now: a job queued or running, an import writing, or a file another
    program holds open; a delete asked again once it is free finishes."""


@dataclass(frozen=True)
class StoredDataDeletions:
    """Deletes of what `store` holds (module docstring), with its quality reports in
    `reports_folder`, its engine cache in `cache_folder`, the saved runs in `runs_folder`, and the
    jobs under way read from `jobs`."""

    store: Store
    reports_folder: Path
    cache_folder: Path
    runs_folder: Path
    jobs: Jobs

    def preview(self, provider: str, root: str) -> DeletionPreview:
        """What a delete of `provider`'s data of `root` removes, nothing written;
        `NoSuchStoredDataError` where the store holds none."""
        try:
            planned = planned_deletion(
                self.store, self.reports_folder, self.cache_folder, provider, root
            )
        except NoStoredDataError as refused:
            raise NoSuchStoredDataError(str(refused)) from refused
        return _preview(planned, len(runs_that_read(self.runs_folder, provider, root)))

    def delete(self, provider: str, root: str) -> None:
        """Delete `provider`'s data of `root`; `DeletionRefusedError` while a job is queued or
        running, an import writes, or a file is held open, and `NoSuchStoredDataError` where the
        store holds none."""
        under_way = self.jobs.under_way()
        if under_way:
            raise DeletionRefusedError(
                f"Expected no job queued or running, got {counted(len(under_way), 'job')}: delete "
                "once they end, or cancel them under Jobs, so that none reads or writes the data "
                "a delete removes."
            )
        try:
            delete_stored_data(self.store, self.reports_folder, self.cache_folder, provider, root)
        except NoStoredDataError as refused:
            raise NoSuchStoredDataError(str(refused)) from refused
        except DeleteRefusedError as refused:
            raise DeletionRefusedError(str(refused)) from refused


def _preview(planned: StoredDataDeletion, saved_runs: int) -> DeletionPreview:
    return DeletionPreview(
        provider=planned.provider,
        root=planned.root,
        imported_files=len(planned.raw_files),
        kept_files=tuple(PurePosixPath(path).name for path in planned.kept_files),
        quality_report=planned.quality_report,
        saved_runs=saved_runs,
    )
