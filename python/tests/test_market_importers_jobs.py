"""Imports as jobs run them (step 5.12): one import writes into a store at a time, under the
store's import lock, which an import takes once its file is read and checked against the store
and its copy under `raw` verified, so that a refused file takes no lock and leaves no file; once
it holds the lock, an import looks its file up again as imported and checks it again where
another import wrote meanwhile, before it writes a partition; and each importer tells the stages
it reaches, its file read and its partitions written, which an import job reports as its progress
(from `BACKLOG.md`, the store's lock over an import's check and its writes, D-99)."""

import hashlib
import threading
import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import timedelta
from pathlib import Path, PurePosixPath

import pytest

from export_samples import (
    IMPORTED_ON,
    SAMPLES,
    sample_lines,
    sample_request,
    store_files,
    with_a_lot_more_in_the_last_bar,
    written_export,
)
from fefat.market import store as stores
from fefat.market.importers.databento import import_databento
from fefat.market.importers.file_import import import_file
from fefat.market.importers.file_report import AlreadyImported
from fefat.market.importers.report import DatabentoImport, ImportStage
from fefat.market.instruments import STATIC_TABLE
from fefat.market.raw_files import RawFiles
from fefat.market.raw_manifest import RAW_MANIFEST_FILE_NAME, RawManifest
from fefat.market.store import IMPORT_LOCK_FILE_NAME, Store
from fefat.market.store_files import held_alone

BATCH = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "synthetic"
    / "databento-batch"
    / "GLBX-20260310-SYNTHETIC0"
)
IMPORTERS = ("file", "databento")


def imported_through(
    importer: str, store: Store, cache: Path, told: list[ImportStage] | None = None
) -> object:
    """The fixtures' NinjaTrader sample or Databento batch imported into `store`, each stage
    the importer tells kept in `told`."""
    stages = [] if told is None else told
    if importer == "file":
        return import_file(
            sample_request("ninjatrader"),
            store,
            cache,
            imported_on=IMPORTED_ON,
            instruments=STATIC_TABLE,
            progress=stages.append,
        )
    return import_databento(BATCH, store, cache, imported_on=IMPORTED_ON, progress=stages.append)


BEFORE_THE_COPY, WHILE_IT_WAITS = "before its copy under raw", "while it waits for the lock"


def another_import_first(
    monkeypatch: pytest.MonkeyPatch, moment: str, another: Callable[[], object]
) -> None:
    """Have the next import run `another` first, at `moment`: just before its original's copy
    under `raw`, or as it takes the store's lock, as an import that ran meanwhile, or held the
    lock while the next one waited for it, would have."""
    if moment == BEFORE_THE_COPY:
        write = RawFiles.write

        def copied_after_another(
            raw: RawFiles, path: PurePosixPath, source: Path, sha256: str
        ) -> None:
            monkeypatch.setattr(RawFiles, "write", write)
            another()
            write(raw, path, source, sha256)

        monkeypatch.setattr(RawFiles, "write", copied_after_another)
        return
    held = Store.held_for_an_import

    def held_after_another(store: Store) -> AbstractContextManager[None]:
        monkeypatch.setattr(Store, "held_for_an_import", held)
        another()
        return held(store)

    monkeypatch.setattr(Store, "held_for_an_import", held_after_another)


def without_the_lock(files: dict[str, tuple[int, int]]) -> dict[str, tuple[int, int]]:
    return {path: file for path, file in files.items() if IMPORT_LOCK_FILE_NAME not in path}


@pytest.mark.parametrize("importer", IMPORTERS)
def test_an_import_whose_store_another_import_holds_writes_no_record_and_is_refused_after_its_wait(
    importer: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The original's copy under `raw` comes before the lock, the last of what can refuse an
    # import before then, so it is all that stays, unrecorded, and the next import of the file
    # writes it again; the import never told its file read, after which it writes, so that its
    # wait for another import can still be stopped.
    store = Store(tmp_path / "data")
    monkeypatch.setattr(stores, "IMPORT_LOCK_WAIT", timedelta(seconds=0.2))
    told: list[ImportStage] = []

    held = held_alone(store.folder / IMPORT_LOCK_FILE_NAME, timedelta(seconds=1))
    with held, pytest.raises(ValueError, match="alone within"):
        imported_through(importer, store, tmp_path / "cache", told)

    assert told == []
    assert store.list_datasets() == ()
    assert store.list_partitions() == ()
    assert store.raw.manifest() == RawManifest()
    assert not (store.folder / "instruments").exists()


def test_a_file_the_store_refuses_takes_no_lock(tmp_path: Path) -> None:
    # A file read in the wrong time zone is refused before anything is written, the lock
    # included (step 5.14's guards hold its other refusals to the same).
    store = Store(tmp_path / "data")

    with pytest.raises(ValueError, match="run 6 hours late"):
        import_file(
            sample_request("ninjatrader", time_zone="America/Chicago"),
            store,
            tmp_path / "cache",
            imported_on=IMPORTED_ON,
            instruments=STATIC_TABLE,
        )

    assert not store.folder.exists()


def test_an_import_waits_for_the_import_that_holds_its_store_and_then_writes(
    tmp_path: Path,
) -> None:
    store = Store(tmp_path / "data")
    holding = threading.Event()
    released: list[float] = []
    told: list[tuple[ImportStage, float]] = []

    def another_import() -> None:
        with held_alone(store.folder / IMPORT_LOCK_FILE_NAME, timedelta(seconds=5)):
            holding.set()
            time.sleep(0.5)
            released.append(time.perf_counter())

    other = threading.Thread(target=another_import)
    other.start()
    holding.wait(timeout=30)
    import_file(
        sample_request("ninjatrader"),
        store,
        tmp_path / "cache",
        imported_on=IMPORTED_ON,
        instruments=STATIC_TABLE,
        progress=lambda stage: told.append((stage, time.perf_counter())),
    )
    other.join()

    assert [stage for stage, _ in told] == [ImportStage.FILE_READ, ImportStage.PARTITIONS_WRITTEN]
    assert told[0][1] > released[0]
    assert len(store.raw.manifest().files) == 1


def test_an_import_whose_dataset_another_import_wrote_while_it_waited_is_refused_with_nothing_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # An export of the same bars, its last bar one lot more, imports while the NinjaTrader
    # sample waits for the lock: held, the sample is checked again and refused for that bar,
    # though its check before the lock found nothing to refuse, and nothing of it is written but
    # its copy under `raw`, unrecorded, where its partitions were written up to the first that
    # differed (from the reviews).
    store = Store(tmp_path / "data")
    later = written_export(
        tmp_path / "later",
        "ES 03-26.Last.txt",
        with_a_lot_more_in_the_last_bar(sample_lines("ninjatrader")),
    )
    after_the_other: dict[str, tuple[int, int]] = {}

    def the_later_export() -> None:
        import_file(
            sample_request("ninjatrader", path=later),
            store,
            tmp_path / "cache",
            imported_on=IMPORTED_ON,
            instruments=STATIC_TABLE,
        )
        after_the_other.update(without_the_lock(store_files(store.folder)))

    another_import_first(monkeypatch, WHILE_IT_WAITS, the_later_export)
    told: list[ImportStage] = []

    with pytest.raises(ValueError, match="nothing was written"):
        imported_through("file", store, tmp_path / "cache", told)

    assert told == []
    assert after_the_other
    assert without_the_lock(store_files(store.folder)) == after_the_other
    (recorded,) = store.raw.manifest().files
    sample = SAMPLES["ninjatrader"][0]
    copy = f"user/{hashlib.sha256(sample.read_bytes()).hexdigest()}/{sample.name}"
    assert sorted(
        path.relative_to(store.folder / "raw").as_posix()
        for path in (store.folder / "raw").rglob("*")
        if path.is_file()
    ) == sorted([RAW_MANIFEST_FILE_NAME, str(recorded.path), copy])


@pytest.mark.parametrize("moment", [BEFORE_THE_COPY, WHILE_IT_WAITS])
@pytest.mark.parametrize("importer", IMPORTERS)
def test_a_file_another_import_imported_meanwhile_reads_as_imported_before(
    importer: str, moment: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The same file imported at once from two places, as the app and the command line could:
    # its copy under `raw`, which the other import recorded, is left as it is, where it was
    # refused as a file that raw files never change, and held, the second import finds the
    # file in the raw manifest and changes nothing (from the reviews).
    store = Store(tmp_path / "data")
    after_the_other: dict[str, tuple[int, int]] = {}

    def the_same_file() -> None:
        imported_through(importer, store, tmp_path / "cache")
        after_the_other.update(without_the_lock(store_files(store.folder)))

    another_import_first(monkeypatch, moment, the_same_file)
    told: list[ImportStage] = []

    result = imported_through(importer, store, tmp_path / "cache", told)

    assert told == []
    if importer == "file":
        assert isinstance(result, AlreadyImported)
    else:
        assert isinstance(result, DatabentoImport)
        assert result.already_imported
    assert after_the_other
    assert without_the_lock(store_files(store.folder)) == after_the_other


@pytest.mark.parametrize("importer", IMPORTERS)
def test_an_import_tells_its_stages_in_order_and_one_imported_already_tells_none(
    importer: str, tmp_path: Path
) -> None:
    store = Store(tmp_path / "data")
    first: list[ImportStage] = []
    again: list[ImportStage] = []

    imported_through(importer, store, tmp_path / "cache", first)
    imported_through(importer, store, tmp_path / "cache", again)

    assert first == [ImportStage.FILE_READ, ImportStage.PARTITIONS_WRITTEN]
    assert again == []
