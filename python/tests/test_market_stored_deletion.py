"""Deleting a provider's data of one root (step 5.18, ADR-0023): what a delete removes, said before
and done after, with every other file as it was; a file imported again as new, under other
arguments too; a raw file that feeds another root still stored kept, then gone with the last of
its roots and its batch's side files with it; a delete held up anywhere finished by asking again;
and no file outside the pair's removed, whatever text names it."""

import hashlib
import json
import re
import shutil
from datetime import date, timedelta
from pathlib import Path
from typing import Any, NamedTuple

import pytest
from databento_dbn import OHLCVMsg, RType, Schema

import fefat.market.raw_files
import fefat.market.stored_deletion
from dbn_files import dbn_content, mapping, utc
from export_samples import (
    IMPORTED_ON,
    PRESETS,
    SAMPLES,
    SYNTHETIC,
    sample_request,
)
from fefat.market.importers.databento import import_databento
from fefat.market.importers.file_import import FileImportRequest, import_file
from fefat.market.importers.file_report import FileImportReport
from fefat.market.instruments import STATIC_TABLE
from fefat.market.layout import Dataset
from fefat.market.quality import assess_quality
from fefat.market.quality_report import write_quality_report
from fefat.market.schema import parse_schema_name
from fefat.market.store import IMPORT_LOCK_FILE_NAME, Store
from fefat.market.store_files import held_alone, write_atomically
from fefat.market.stored_deletion import (
    DeleteRefusedError,
    NoStoredDataError,
    StoredDataDeletion,
    delete_stored_data,
    planned_deletion,
)

EXPORT_SHA256 = hashlib.sha256(SAMPLES["ninjatrader"][0].read_bytes()).hexdigest()
ES_EXPORT = f"user/{EXPORT_SHA256}/ES 03-26.Last.txt"
MES_EXPORT = f"user/{EXPORT_SHA256}/MES 03-26.Last.txt"
ES_FROM_NINJATRADER = (
    "data/ninjatrader/ohlcv-1m/root=ES/",
    f"data/raw/{ES_EXPORT}",
    "data/reports/ninjatrader/ES/",
    "cache/engine/ninjatrader/ES/",
)
"""Where the files of ES from ninjatrader lie, relative to the test's folder."""
JOB = "GLBX-20260310-SYNTHETIC0"
BATCH = SYNTHETIC / "databento-batch" / JOB
DATA_FILE = "glbx-mdp3-20260304-20260309.ohlcv-1m.dbn"
ONE_MINUTE = int(RType.from_str("ohlcv-1m"))


class Folders(NamedTuple):
    """A store with its reports' folder beside its data, as `FefatPaths` puts it, and a cache."""

    store: Store
    reports: Path
    cache: Path

    def plan(self, provider: str, root: str) -> StoredDataDeletion:
        return planned_deletion(self.store, self.reports, self.cache, provider, root)

    def delete(self, provider: str, root: str) -> StoredDataDeletion:
        return delete_stored_data(self.store, self.reports, self.cache, provider, root)

    def pairs(self) -> list[tuple[str, str]]:
        """The provider and root of each dataset the store lists, once each."""
        listed = [(dataset.provider, dataset.root) for dataset in self.store.list_datasets()]
        return sorted(set(listed))


def folders_in(folder: Path) -> Folders:
    return Folders(Store(folder / "data"), folder / "data" / "reports", folder / "cache")


def tree(folder: Path) -> dict[str, str]:
    """Every file under `folder`, by its path relative to it, with the SHA-256 of its bytes."""
    return {
        path.relative_to(folder).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in folder.rglob("*")
        if path.is_file()
    }


def cached_month(folders: Folders, provider: str, root: str) -> None:
    """A month of the engine cache of `provider`'s `root`, as a build leaves it, with the
    contract's lock beside its folder."""
    month = folders.cache / "engine" / provider / root / f"{root}H2026" / "2026-03"
    month.mkdir(parents=True)
    (month / "index.json").write_text("{}\n", encoding="utf-8")
    (month.parent.with_name(f"{root}H2026.lock")).write_bytes(b"")


def two_roots_and_another_provider(folder: Path) -> Folders:
    """ES and MES from ninjatrader, imported from one export's bytes under two names, so that both
    copies share a folder under `raw`, and the fixtures' 1-minute bars from synthetic, ES among
    them: each pair with its quality report, and the two of ninjatrader with a cached month."""
    folders = folders_in(folder)
    store, cache = folders.store, folders.cache
    import_file(
        sample_request("ninjatrader"),
        store,
        cache,
        imported_on=IMPORTED_ON,
        instruments=STATIC_TABLE,
    )
    mes = folder / "exports" / "MES 03-26.Last.txt"
    mes.parent.mkdir(parents=True)
    shutil.copyfile(SAMPLES["ninjatrader"][0], mes)
    import_file(
        FileImportRequest(path=mes, profile=PRESETS["ninjatrader"]),
        store,
        cache,
        imported_on=IMPORTED_ON,
        instruments=STATIC_TABLE,
    )
    shutil.copytree(SYNTHETIC / "ohlcv-1m", store.folder / "synthetic" / "ohlcv-1m")
    for provider, root in (("ninjatrader", "ES"), ("ninjatrader", "MES"), ("synthetic", "ES")):
        write_quality_report(assess_quality(store, provider, root, cache), folders.reports)
    cached_month(folders, "ninjatrader", "ES")
    cached_month(folders, "ninjatrader", "MES")
    return folders


def gone_with(before: dict[str, str], places: tuple[str, ...]) -> set[str]:
    return {path for path in before if path.startswith(places)}


def test_a_delete_removes_what_its_plan_says_and_leaves_every_other_file_as_it_was(
    tmp_path: Path,
) -> None:
    # Done means 1. MES's copy shares its folder under raw with ES's and stays with its entry.
    folders = two_roots_and_another_provider(tmp_path)
    es = Dataset(provider="ninjatrader", schema_name=parse_schema_name("ohlcv-1m"), root="ES")
    partitions = len(folders.store.list_partitions(es))
    before = tree(tmp_path)

    plan = folders.plan("ninjatrader", "ES")
    planned = tree(tmp_path)
    deleted = folders.delete("ninjatrader", "ES")
    after = tree(tmp_path)

    gone = gone_with(before, ES_FROM_NINJATRADER)
    assert planned == before
    assert deleted == plan
    assert plan.datasets == (es,)
    assert (plan.partitions, plan.raw_files, plan.side_files, plan.kept_files) == (
        partitions,
        (ES_EXPORT,),
        (),
        (),
    )
    assert plan.quality_report and plan.engine_cache
    assert plan.summary().splitlines() == [
        f"ES from ninjatrader: {partitions} partition of ohlcv-1m.",
        "Raw copies that go, with their entries in the raw manifest, so that their files import "
        "again as new: 1 imported file.",
        "Its quality report goes.",
        "Its engine cache goes.",
    ]
    assert gone >= {f"data/raw/{ES_EXPORT}", "data/ninjatrader/ohlcv-1m/root=ES/dataset.json"}
    assert set(after) == set(before) - gone
    assert {path for path in after if after[path] != before[path]} == {"data/raw/MANIFEST.json"}
    assert [file.path for file in folders.store.raw.manifest().files] == [MES_EXPORT]
    assert folders.pairs() == [
        ("ninjatrader", "MES"),
        ("synthetic", "BTCUSDT-PERP"),
        ("synthetic", "ES"),
    ]
    assert not (folders.store.folder / "ninjatrader" / "ohlcv-1m" / "root=ES").exists()
    assert not (folders.cache / "engine" / "ninjatrader" / "ES").exists()


def test_after_a_delete_a_file_imported_before_imports_again_as_new_under_other_arguments(
    tmp_path: Path,
) -> None:
    # Done means 2, the builder's case after step 5.17: a file imported with its root typed is
    # refused without it (D-50) until its instrument's data is deleted.
    folders = folders_in(tmp_path)
    store, cache = folders.store, folders.cache
    typed = sample_request("ninjatrader", root="ES")
    first = import_file(typed, store, cache, imported_on=IMPORTED_ON, instruments=STATIC_TABLE)
    assert isinstance(first, FileImportReport)
    stored = store.list_partitions()
    with pytest.raises(ValueError, match="a file is imported once, as its first import read it"):
        import_file(
            sample_request("ninjatrader"),
            store,
            cache,
            imported_on=IMPORTED_ON,
            instruments=STATIC_TABLE,
        )

    folders.delete("ninjatrader", "ES")
    again = import_file(
        sample_request("ninjatrader"),
        store,
        cache,
        imported_on=date(2026, 11, 19),
        instruments=STATIC_TABLE,
    )

    assert isinstance(again, FileImportReport)
    (recorded,) = store.raw.manifest().files
    assert (recorded.path, recorded.vendor_version, recorded.imported_on) == (
        ES_EXPORT,
        "import profile ninjatrader",
        date(2026, 11, 19),
    )
    assert [file.partition for file in store.list_partitions()] == [
        file.partition for file in stored
    ]


def two_root_batch(folder: Path) -> Path:
    """The fixtures' batch download with a data file of ES's and MES's bars, a minute of each on
    2026-03-09, and the vendor's manifest publishing its SHA-256."""
    batch = Path(shutil.copytree(BATCH, folder / JOB))
    mappings = [
        mapping("ESH6", 1001, date(2025, 3, 21), date(2026, 3, 21)),
        mapping("MESH6", 7001, date(2025, 3, 21), date(2026, 3, 21)),
    ]
    minute = utc(2026, 3, 9, 14, 30)
    bars = [
        OHLCVMsg(ONE_MINUTE, 1, 1001, minute, 6_750_000_000_000, 6_751_000_000_000, 6_749_000_000_000, 6_750_500_000_000, 10),
        OHLCVMsg(ONE_MINUTE, 1, 7001, minute, 6_750_000_000_000, 6_751_000_000_000, 6_749_000_000_000, 6_750_500_000_000, 40),
    ]  # fmt: skip
    content = dbn_content(Schema("ohlcv-1m"), mappings, bars)
    (batch / DATA_FILE).write_bytes(content)
    published = json.loads((batch / "manifest.json").read_text(encoding="utf-8"))
    for listed in published["files"]:
        if listed["filename"] == DATA_FILE:
            listed["size"] = len(content)
            listed["hash"] = f"sha256:{hashlib.sha256(content).hexdigest()}"
    (batch / "manifest.json").write_text(json.dumps(published, indent=4), encoding="utf-8")
    return batch


def test_a_raw_file_that_feeds_another_root_still_stored_goes_with_the_last_of_its_roots(
    tmp_path: Path,
) -> None:
    # Done means 3: the batch's data file fed ES and MES; its side files feed none.
    folders = folders_in(tmp_path)
    import_databento(
        two_root_batch(tmp_path / "download"), folders.store, folders.cache, imported_on=IMPORTED_ON
    )
    data_file = f"databento/{JOB}/{DATA_FILE}"
    side_files = tuple(
        f"databento/{JOB}/{name}" for name in ("condition.json", "manifest.json", "metadata.json")
    )
    raw = folders.store.folder / "raw"

    first = folders.delete("databento", "ES")

    assert (first.raw_files, first.side_files, first.kept_files) == ((), (), (data_file,))
    assert (
        f"Raw copies kept, since each also feeds another root still stored: {data_file}."
        in first.summary().splitlines()
    )
    assert sorted(file.path for file in folders.store.raw.manifest().files) == sorted(
        (data_file, *side_files)
    )
    assert all((raw / path).is_file() for path in (data_file, *side_files))
    assert folders.pairs() == [("databento", "MES")]

    last = folders.delete("databento", "MES")

    assert (last.raw_files, sorted(last.side_files), last.kept_files) == (
        (data_file,),
        list(side_files),
        (),
    )
    assert folders.store.raw.manifest().files == ()
    assert (raw / "MANIFEST.json").is_file()
    assert not (raw / "databento").exists()
    assert folders.pairs() == []
    assert not (folders.store.folder / "databento").exists()


def held_open(patched: pytest.MonkeyPatch, held: Path) -> None:
    """`held` as Windows treats a file or folder another program holds open: removing it, or
    replacing it, refused with `PermissionError`; everything else as it is."""
    rmtree, unlink = shutil.rmtree, Path.unlink
    replace_atomically = write_atomically

    def refused(path: object) -> None:
        if Path(str(path)) == held:
            raise PermissionError(13, "The process cannot access the file", str(path))

    def removing_tree(path: Any, *arguments: Any, **named: Any) -> None:
        refused(path)
        rmtree(path, *arguments, **named)

    def unlinking(path: Path, *arguments: Any, **named: Any) -> None:
        refused(path)
        unlink(path, *arguments, **named)

    def replacing(path: Path, *arguments: Any, **named: Any) -> None:
        refused(path)
        replace_atomically(path, *arguments, **named)

    patched.setattr(shutil, "rmtree", removing_tree)
    patched.setattr(Path, "unlink", unlinking)
    patched.setattr(fefat.market.raw_files, "write_atomically", replacing)


HELD_UP_AT = {
    "the quality report": "data/reports/ninjatrader/ES",
    "the engine cache": "cache/engine/ninjatrader/ES",
    "a raw copy": f"data/raw/{ES_EXPORT}",
    "the raw manifest": "data/raw/MANIFEST.json",
    "a partition": "data/ninjatrader/ohlcv-1m/root=ES/contract=ESH2026",
    "dataset.json": "data/ninjatrader/ohlcv-1m/root=ES/dataset.json",
}
"""Each place a delete removes or rewrites, in its order (ADR-0023), relative to the test's
folder."""


@pytest.mark.parametrize("place", HELD_UP_AT)
def test_a_delete_held_up_anywhere_leaves_the_pair_listed_and_finishes_when_asked_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, place: str
) -> None:
    # Done means 4: a file held open stands for a crash at the same place, which leaves the
    # same files; the pair stays listed while a record remains, and its dataset after that.
    folders = two_roots_and_another_provider(tmp_path)
    before = tree(tmp_path)
    held = tmp_path / HELD_UP_AT[place]

    with monkeypatch.context() as patched:
        held_open(patched, held)
        with pytest.raises(
            DeleteRefusedError, match=f"Expected to remove {re.escape(str(held))}"
        ) as refused:
            folders.delete("ninjatrader", "ES")
    listed = folders.pairs()
    left = [
        file
        for file in folders.store.list_partitions()
        if file.partition.dataset.provider == "ninjatrader"
    ]
    folders.delete("ninjatrader", "ES")

    assert "close the programs that read it" in str(refused.value)
    assert "delete again, which finishes the delete" in str(refused.value)
    assert ("ninjatrader", "ES") in listed
    assert any(file.partition.dataset.root == "ES" for file in left) == (place != "dataset.json")
    assert set(tree(tmp_path)) == set(before) - gone_with(before, ES_FROM_NINJATRADER)
    assert [file.path for file in folders.store.raw.manifest().files] == [MES_EXPORT]
    assert ("ninjatrader", "ES") not in folders.pairs()


def test_an_entry_of_another_root_stays_though_its_data_was_removed_by_hand(tmp_path: Path) -> None:
    # Done means 4: only an entry that names the root deleted is a candidate.
    folders = two_roots_and_another_provider(tmp_path)
    shutil.rmtree(folders.store.folder / "ninjatrader" / "ohlcv-1m" / "root=MES")

    deleted = folders.delete("ninjatrader", "ES")

    assert deleted.raw_files == (ES_EXPORT,)
    assert [file.path for file in folders.store.raw.manifest().files] == [MES_EXPORT]
    assert (folders.store.folder / "raw" / MES_EXPORT).is_file()


def synthetic_minutes(folder: Path) -> Folders:
    """The fixtures' 1-minute bars from synthetic, ES and BTCUSDT-PERP, as a store holds them."""
    folders = folders_in(folder)
    shutil.copytree(SYNTHETIC / "ohlcv-1m", folders.store.folder / "synthetic" / "ohlcv-1m")
    return folders


@pytest.mark.parametrize(
    ("provider", "root"),
    [
        ("synthetic", "../BTCUSDT-PERP"),
        ("..", "ES"),
        ("synthetic/../synthetic", "ES"),
        ("synthetic", "ES/.."),
        ("synthetic", "root=ES"),
        ("Synthetic", "ES"),
        ("synthetic", "es"),
        ("synthetic", "*"),
        ("raw", "user"),
        ("reports", "synthetic"),
        ("", ""),
    ],
)
def test_a_delete_named_by_any_other_text_removes_nothing(
    tmp_path: Path, provider: str, root: str
) -> None:
    # Done means 4: the datasets are those the store lists, never a path built from the text.
    folders = synthetic_minutes(tmp_path)
    before = tree(tmp_path)

    with pytest.raises(
        NoStoredDataError, match=re.escape(f"Expected stored data of {root} from {provider},")
    ):
        folders.plan(provider, root)
    with pytest.raises(NoStoredDataError):
        folders.delete(provider, root)

    assert tree(tmp_path) == before


def test_a_delete_waits_for_an_import_s_writes_and_is_refused_past_its_wait(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folders = synthetic_minutes(tmp_path)
    monkeypatch.setattr(fefat.market.stored_deletion, "DELETE_WAIT", timedelta(milliseconds=100))
    lock = folders.store.folder / IMPORT_LOCK_FILE_NAME

    with held_alone(lock, timedelta(seconds=1)):
        before = tree(tmp_path)
        with pytest.raises(DeleteRefusedError, match="an import writing to the store"):
            folders.delete("synthetic", "ES")
        held = tree(tmp_path)

    assert held == before
    assert ("synthetic", "ES") in folders.pairs()
