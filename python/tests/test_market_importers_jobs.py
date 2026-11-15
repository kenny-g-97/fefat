"""Imports as jobs run them (step 5.12): one import writes into a store at a time, under the
store's import lock, which an import takes once its file is read and checked against the store,
so that a refused file takes no lock and leaves no file; and each importer tells the stages it
reaches, its file read and its partitions written, which an import job reports as its progress
(from `BACKLOG.md`, the store's lock over an import's check and its writes, D-99)."""

import threading
import time
from datetime import timedelta
from pathlib import Path

import pytest

from export_samples import IMPORTED_ON, sample_request
from fefat.market import store as stores
from fefat.market.importers.databento import import_databento
from fefat.market.importers.file_import import import_file
from fefat.market.importers.report import ImportStage
from fefat.market.instruments import STATIC_TABLE
from fefat.market.raw_manifest import RawManifest
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


@pytest.mark.parametrize("importer", IMPORTERS)
def test_an_import_whose_store_another_import_holds_writes_no_record_and_is_refused_after_its_wait(
    importer: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The original's copy under `raw` comes before the lock, the last of what can refuse an
    # import, so it is all that stays: the raw manifest does not record it, and the next import
    # of the file writes it again.
    store = Store(tmp_path / "data")
    monkeypatch.setattr(stores, "IMPORT_LOCK_WAIT", timedelta(seconds=0.2))

    held = held_alone(store.folder / IMPORT_LOCK_FILE_NAME, timedelta(seconds=1))
    with held, pytest.raises(ValueError, match="alone within"):
        imported_through(importer, store, tmp_path / "cache")

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
    holding, read = threading.Event(), threading.Event()
    released: list[float] = []
    written: list[float] = []

    def another_import() -> None:
        with held_alone(store.folder / IMPORT_LOCK_FILE_NAME, timedelta(seconds=5)):
            holding.set()
            read.wait(timeout=30)
            time.sleep(0.3)
            released.append(time.perf_counter())

    def told(stage: ImportStage) -> None:
        if stage is ImportStage.FILE_READ:
            read.set()
        else:
            written.append(time.perf_counter())

    other = threading.Thread(target=another_import)
    other.start()
    holding.wait(timeout=30)
    import_file(
        sample_request("ninjatrader"),
        store,
        tmp_path / "cache",
        imported_on=IMPORTED_ON,
        instruments=STATIC_TABLE,
        progress=told,
    )
    other.join()

    assert written[0] > released[0]
    assert len(store.raw.manifest().files) == 1


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
