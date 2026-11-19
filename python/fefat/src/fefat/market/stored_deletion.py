"""Deleting a provider's data of one root from the store (step 5.18, ADR-0023), as `fefat data
delete` and the dataset's page do: every dataset of the pair, of every schema; FEFAT's copies
under `raw` of the files they were imported from, with their entries in the raw manifest, so that
those files import again as new; the pair's quality report; and its engine cache. A raw file that
also feeds another root still stored from the provider is kept, and goes with the last of its
roots; a batch's side files, which feed no root, go once no file of the provider in their folder
feeds one. Saved runs, the instrument's saved specification, and other providers' data stay.

`planned_deletion` says what a delete removes and writes nothing; `delete_stored_data` holds the
store as an import holds it while it writes, plans again, and removes, in an order that keeps the
pair listed while a record remains, so that a delete held up, by a crash or by a file another
program holds open, is finished by asking again:

    deletion = planned_deletion(store, paths.reports_dir, paths.cache_dir, "ninjatrader", "ES")
    print(deletion.summary())
    delete_stored_data(store, paths.reports_dir, paths.cache_dir, "ninjatrader", "ES")
"""

import shutil
from collections.abc import Callable
from contextlib import ExitStack
from datetime import timedelta
from pathlib import Path, PurePosixPath

from fefat.market.calendar import counted
from fefat.market.coverage import SESSION_KINDS
from fefat.market.engine_cache_index import ENGINE_CACHE_FOLDER_NAME
from fefat.market.importers.databento_batch import CONDITIONS_FILE_NAME
from fefat.market.layout import DATASET_METADATA_FILE_NAME, RAW_FOLDER_NAME, Dataset
from fefat.market.quality_report import REPORT_LOCK_SUFFIX
from fefat.market.raw_files import RawFiles
from fefat.market.raw_manifest import RAW_MANIFEST_FILE_NAME, RawManifest
from fefat.market.schema import FrozenModel
from fefat.market.store import IMPORT_LOCK_FILE_NAME, Store
from fefat.market.store_files import held_alone

DELETE_WAIT = timedelta(seconds=5)
"""How long a delete waits for an import's writes, or a quality report's writer, before it is
refused: the trader asks again once they are done."""


class NoStoredDataError(ValueError):
    """A provider and root of which the store lists no dataset."""

    def __init__(self, provider: str, root: str) -> None:
        super().__init__(
            f"Expected stored data of {root} from {provider}, got none: `fefat data catalog` "
            "lists each provider's data of each root the store holds."
        )


class DeleteRefusedError(ValueError):
    """A delete that cannot go on now: the store held by an import's writes, or a file that
    another program holds open; asking again once it is free finishes the delete."""


class StoredDataDeletion(FrozenModel):
    """What a delete of `provider`'s data of `root` removes (module docstring): its datasets and
    how many partitions they hold; FEFAT's copies of the files they were imported from, and the
    side files of their batches, by their paths under `raw`; whether a quality report and an
    engine cache are written; and the raw files kept, since they also feed another root still
    stored."""

    provider: str
    root: str
    datasets: tuple[Dataset, ...]
    partitions: int
    raw_files: tuple[str, ...]
    side_files: tuple[str, ...]
    kept_files: tuple[str, ...]
    quality_report: bool
    engine_cache: bool

    def summary(self) -> str:
        """What the delete removes, in lines for a person: counts, schemas, and raw paths."""
        schemas = ", ".join(str(dataset.schema_name) for dataset in self.datasets)
        lines = [
            f"{self.root} from {self.provider}: {counted(self.partitions, 'partition')} of "
            f"{schemas}.",
            self._raw_files_line(),
        ]
        if self.kept_files:
            kept = ", ".join(self.kept_files)
            lines.append(
                f"Raw copies kept, since each also feeds another root still stored: {kept}."
            )
        if self.quality_report:
            lines.append("Its quality report goes.")
        if self.engine_cache:
            lines.append("Its engine cache goes.")
        return "\n".join(lines)

    def _raw_files_line(self) -> str:
        if not self.raw_files:
            return "No raw copy goes."
        going = counted(len(self.raw_files), "imported file")
        if self.side_files:
            going += f", and {counted(len(self.side_files), 'side file')} of their batches"
        return (
            "Raw copies that go, with their entries in the raw manifest, so that their files "
            f"import again as new: {going}."
        )


def planned_deletion(
    store: Store, reports_folder: Path, cache_folder: Path, provider: str, root: str
) -> StoredDataDeletion:
    """What a delete of `provider`'s data of `root` removes, writing nothing; `NoStoredDataError`
    where the store lists no dataset of the pair. The datasets are those the store lists, so that
    no path is built from the text that names the pair."""
    stored = store.list_datasets()
    datasets = _datasets_of(stored, provider, root)
    pair = datasets[0]
    others = {each.root for each in stored if each.provider == pair.provider} - {pair.root}
    manifest = store.raw.manifest()
    fed = [
        file
        for file in manifest.files
        if file.provider == pair.provider and pair.root in file.roots
    ]
    raw_files = tuple(file.path for file in fed if not others.intersection(file.roots))
    return StoredDataDeletion(
        provider=pair.provider,
        root=pair.root,
        datasets=datasets,
        partitions=sum(len(store.list_partitions(dataset)) for dataset in datasets),
        raw_files=raw_files,
        side_files=_side_files(manifest, pair.provider, raw_files),
        kept_files=tuple(file.path for file in fed if others.intersection(file.roots)),
        quality_report=_report_folder(reports_folder, pair).is_dir(),
        engine_cache=_cache_folder(cache_folder, pair).is_dir(),
    )


def delete_stored_data(
    store: Store, reports_folder: Path, cache_folder: Path, provider: str, root: str
) -> StoredDataDeletion:
    """Delete what `planned_deletion` says, and give it: a pair the store does not list refused
    before anything is held or written, then the store held as an import holds it while it
    writes, refused with `DeleteRefusedError` past `DELETE_WAIT`, and planned once held (ADR-0023).
    The quality report goes first, so that no report vouches for data half deleted; the raw
    copies and their entries before any record, so that no entry says a file is imported once its
    records are gone; the records of other kinds before trades, TBBO, and bars, which the Data
    page lists the pair by, and every record before each `dataset.json`, so that the pair stays
    listed while a record remains. A file that another program holds open refuses the delete
    with `DeleteRefusedError`, and asking again finishes it."""
    _datasets_of(store.list_datasets(), provider, root)
    with ExitStack() as held:
        _hold(held, store.folder / IMPORT_LOCK_FILE_NAME, "an import writing to the store")
        deletion = planned_deletion(store, reports_folder, cache_folder, provider, root)
        pair = deletion.datasets[0]
        if deletion.quality_report:
            _removed_report(reports_folder, pair)
        _removed_tree(_cache_folder(cache_folder, pair))
        _removed_empty_folders(
            cache_folder / ENGINE_CACHE_FOLDER_NAME, PurePosixPath(pair.provider)
        )
        _removed_raw_files(store, deletion)
        for dataset in sorted(deletion.datasets, key=_listed_by_the_data_page):
            _removed_records(store.folder / dataset.relative_folder())
        for dataset in deletion.datasets:
            _removed_file(store.folder / dataset.metadata_path())
            _removed_empty_folders(store.folder, dataset.relative_folder())
    return deletion


def _datasets_of(stored: tuple[Dataset, ...], provider: str, root: str) -> tuple[Dataset, ...]:
    """The datasets of `provider`'s data of `root` among those the store lists;
    `NoStoredDataError` where there are none."""
    datasets = tuple(each for each in stored if (each.provider, each.root) == (provider, root))
    if not datasets:
        raise NoStoredDataError(provider, root)
    return datasets


def _listed_by_the_data_page(dataset: Dataset) -> bool:
    """Whether the Data page lists a pair by `dataset`, one of trades, TBBO, or bars."""
    return dataset.schema_name.kind in SESSION_KINDS


def _side_files(manifest: RawManifest, provider: str, removed: tuple[str, ...]) -> tuple[str, ...]:
    """The provider's entries that feed no root, a batch's side files, in the folders that
    `removed` leaves without an entry of the provider that feeds one."""
    gone = set(removed)
    feeding = {
        PurePosixPath(file.path).parent
        for file in manifest.files
        if file.provider == provider and file.roots and file.path not in gone
    }
    emptied = {PurePosixPath(path).parent for path in removed} - feeding
    return tuple(
        file.path
        for file in manifest.files
        if file.provider == provider
        and not file.roots
        and PurePosixPath(file.path).parent in emptied
    )


def _removed_report(reports_folder: Path, pair: Dataset) -> None:
    """The pair's quality report, removed under its writers' lock, whose file stays, since a
    writer waiting for the lock holds it open."""
    folder = _report_folder(reports_folder, pair)
    with ExitStack() as held:
        lock = folder.with_name(f"{pair.root}{REPORT_LOCK_SUFFIX}")
        _hold(held, lock, "its quality report being written")
        _removed_tree(folder)


def _removed_raw_files(store: Store, deletion: StoredDataDeletion) -> None:
    """The raw copies that feed the root, then the side files, then their entries in one write
    of the manifest, then the folders left empty: every entry stays until its file is gone, so
    that a delete stopped part way finds them again when it is asked again. The vendor's
    conditions, which the quality reports read through the manifest, go last, so that a file
    held open never leaves their entry without its file."""
    raw, raw_folder = store.raw, store.folder / RAW_FOLDER_NAME
    side_files = sorted(
        deletion.side_files, key=lambda path: PurePosixPath(path).name == CONDITIONS_FILE_NAME
    )
    for path in (*deletion.raw_files, *side_files):
        _removed_raw_file(raw, raw_folder, path)
    try:
        raw.forget({*deletion.raw_files, *deletion.side_files})
    except OSError as error:
        raise _held_open(raw_folder / RAW_MANIFEST_FILE_NAME, error) from error
    for path in (*deletion.raw_files, *deletion.side_files):
        _removed_empty_folders(raw_folder, PurePosixPath(path).parent)


def _removed_raw_file(raw: RawFiles, raw_folder: Path, path: str) -> None:
    try:
        raw.remove(path)
    except OSError as error:
        raise _held_open(raw_folder / path, error) from error


def _removed_records(folder: Path) -> None:
    """Everything in a dataset's folder but its `dataset.json`: its contracts' partitions, their
    digests, and what an interrupted write left."""
    if not folder.is_dir():
        return
    for entry in sorted(folder.iterdir()):
        if entry.name == DATASET_METADATA_FILE_NAME:
            continue
        if entry.is_dir():
            _removed_tree(entry)
        else:
            _removed_file(entry)


def _removed_tree(folder: Path) -> None:
    """`folder` and all it holds removed, passing over a file gone before its turn, as another
    program's rename of a temporary file leaves it, and the folder itself where it is gone;
    any other refusal stops the delete (`DeleteRefusedError`)."""
    try:
        shutil.rmtree(folder, onexc=_passing_over_what_is_gone)
    except OSError as error:
        raise _held_open(folder, error) from error


def _passing_over_what_is_gone(
    removing: Callable[..., object], path: str, error: BaseException
) -> None:
    if not isinstance(error, FileNotFoundError):
        raise error


def _removed_file(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError as error:
        raise _held_open(path, error) from error


def _removed_empty_folders(top: Path, relative: PurePosixPath) -> None:
    """`relative`'s folder under `top`, and each folder above it below `top`, removed while it
    is empty, the deepest first."""
    for folder in (relative, *relative.parents[:-1]):
        if folder == PurePosixPath("."):
            return
        try:
            (top / folder).rmdir()
        except FileNotFoundError:
            continue
        except OSError:
            return


def _hold(held: ExitStack, lock_file: Path, holder: str) -> None:
    """`lock_file` held alone until `held` closes, refused with `DeleteRefusedError` past
    `DELETE_WAIT`; a refusal from inside the block passes as it is."""
    try:
        held.enter_context(held_alone(lock_file, DELETE_WAIT))
    except ValueError as busy:
        seconds = DELETE_WAIT.total_seconds()
        raise DeleteRefusedError(
            f"Expected to delete with nothing else writing, got {holder} for {seconds:g} "
            "seconds: delete again once it is done."
        ) from busy


def _held_open(path: Path, error: OSError) -> DeleteRefusedError:
    """The refusal of `path`, in the system's words without the path its text repeats, or the
    error's whole text where it carries no words of the system."""
    words = str(error) if error.strerror is None else error.strerror
    return DeleteRefusedError(
        f'Expected to remove {path}, got "{words}": close the programs that read it, such as a '
        "chart or a notebook, then delete again, which finishes the delete."
    )


def _report_folder(reports_folder: Path, pair: Dataset) -> Path:
    return reports_folder / pair.provider / pair.root


def _cache_folder(cache_folder: Path, pair: Dataset) -> Path:
    return cache_folder / ENGINE_CACHE_FOLDER_NAME / pair.provider / pair.root
