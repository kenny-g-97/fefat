"""Files that overlap stored data, through both importers (step 5.14, ADR-0021, Done means 1 and
2): a range imported as one file, or as two files that overlap, in either order, leaves the same
rows in the same partitions, for bars kept by month and for prints kept by trade date; a file of
records the store already holds writes no partition; a refused file changes no byte of the
store, the DBN importer included; an import cut short while it writes is finished by running
it again; and what an import refuses whatever it is told, prints without a sequence of their
own that dispute a second their file may hold part of, and bars that differ in a back-adjusted
series. Every file is generated in the test's folder, its values made up from its instants."""

import hashlib
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest
from databento_dbn import F_LAST, Action, OHLCVMsg, RType, Schema, Side, TradeMsg
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from dbn_files import Interval, SymbolMapping, dbn_content, mapping, utc, write_dbn
from export_samples import (
    PRESETS,
    SAMPLES,
    a_new_product_profile,
    five_minute_file,
    sample_lines,
    with_a_lot_more_in_the_last_bar,
    written_export,
)
from fefat.market.importers.databento import import_databento
from fefat.market.importers.file_import import FileImportRequest, import_file
from fefat.market.importers.file_report import AlreadyImported, FileImportReport
from fefat.market.importers.partition_merge import DifferingRecords
from fefat.market.importers.profiles import ImportProfile
from fefat.market.instruments import STATIC_TABLE
from fefat.market.layout import (
    Dataset,
    DatasetMetadata,
    DatasetOrigin,
    Partition,
    SeriesKind,
    SizeUnit,
    YearMonth,
)
from fefat.market.saved_instruments import instrument_table
from fefat.market.schema import parse_schema_name
from fefat.market.store import Store

MINUTE = 60_000_000_000
SECOND = 1_000_000_000
TICK = 250_000_000
FIVE_THOUSAND = 5_000_000_000_000
ONE_MINUTE = int(RType.from_str("ohlcv-1m"))
IMPORTED_ON = date(2026, 11, 14)
TRADE_DATES = (date(2026, 3, 30), date(2026, 3, 31), date(2026, 4, 1), date(2026, 4, 2))
"""Four sessions of ES across a month end, two in each month."""
ESM6 = [mapping("ESM6", 1003, date(2025, 6, 20), date(2026, 6, 20))]
ESH6 = [mapping("ESH6", 1001, date(2025, 3, 21), date(2026, 3, 21))]
SECOND_STAMPED_PRINTS = ImportProfile.model_validate(
    {
        "name": "ibkr-ticks",
        "provider": "ibkr",
        "description": "IBKR Time and Sales from the TWS API",
        "layout": {"delimiter": ",", "header": True},
        "columns": {"timestamp": "time", "ticks": {"price": "price", "size": "size"}},
        "timestamp": {"format": "unix_s", "time_zone": "UTC"},
        "timeframe": "ticks",
        "contract_in_file_name": "(?P<contract>[A-Z0-9]{1,4}[FGHJKMNQUVXZ][0-9]{4})",
    }
)
"""Prints stamped to the second, without a side or a sequence of their own (D-70)."""


@dataclass(frozen=True)
class Record:
    """A record of a generated stream: its place in the stream, its instant, its place among
    the records of that instant, and its session's trade date."""

    index: int
    instant: int
    place: int
    trade_date: date

    def price(self, unit: int) -> int:
        """A price on ES's tick, made up from the record's instant and place, which comes back
        at a place no sooner than 4,001 units later, so that prints a day apart differ: two
        files that overlap would otherwise read as a file read a day off (ADR-0024)."""
        steps = self.instant // unit * 7_919 + self.place * 104_729
        return FIVE_THOUSAND + TICK * (steps % 4_001)


@dataclass(frozen=True)
class Layout:
    """One way a stream reaches the store: the unit its instants step by, whether an instant
    holds several records, how its partitions are keyed, the file it is written as, and the
    importer that reads it."""

    name: str
    unit: int
    prints: bool
    by_month: bool
    written: Callable[[Path, Sequence[Record]], Path]
    imported: Callable[[Path, Store, Path], object]

    def key(self, record: Record) -> date:
        """The trade date, or the first day of the month, that keys the record's partition."""
        return record.trade_date.replace(day=1) if self.by_month else record.trade_date


def dbn_bars(folder: Path, records: Sequence[Record]) -> Path:
    bars = [
        OHLCVMsg(ONE_MINUTE, 1, 1003, record.instant, close - TICK, close + TICK, close - 2 * TICK, close, 1 + record.instant // MINUTE % 9)
        for record in records
        for close in [record.price(MINUTE)]
    ]  # fmt: skip
    return write_dbn(folder / "es.ohlcv-1m.dbn", dbn_content(Schema("ohlcv-1m"), ESM6, bars))


def dbn_trades(folder: Path, records: Sequence[Record]) -> Path:
    trades = [
        TradeMsg(publisher_id=1, instrument_id=1003, ts_event=record.instant - 1_000, price=record.price(SECOND), size=1 + record.place, action=Action("T"), side=Side("B"), depth=0, ts_recv=record.instant, flags=F_LAST, sequence=record.index)
        for record in records
    ]  # fmt: skip
    return write_dbn(folder / "es.trades.dbn", dbn_content(Schema("trades"), ESM6, trades))


def ninjatrader_bars(folder: Path, records: Sequence[Record]) -> Path:
    """The bars as NinjaTrader exports them: stamped at their close in UTC, prices in points."""
    lines = []
    for record in records:
        close = record.price(MINUTE)
        stamp = datetime.fromtimestamp((record.instant + MINUTE) // SECOND, UTC)
        prices = [close - TICK, close + TICK, close - 2 * TICK, close]
        fields = [f"{Decimal(price) / SECOND}" for price in prices]
        volume = 1 + record.instant // MINUTE % 9
        lines.append(f"{stamp:%Y%m%d %H%M%S};{';'.join(fields)};{volume}")
    return written_export(folder, "ES 06-26.Last.txt", lines)


def second_stamped_prints(folder: Path, records: Sequence[Record]) -> Path:
    lines = [
        f"{record.instant // SECOND},{Decimal(record.price(SECOND)) / SECOND},{1 + record.place}"
        for record in records
    ]
    return written_export(folder, "ESM2026-prints.csv", ["time,price,size", *lines])


def through_databento(path: Path, store: Store, cache: Path) -> object:
    return import_databento(path, store, cache, imported_on=IMPORTED_ON)


def through_a_profile(
    profile: ImportProfile, differing: DifferingRecords = DifferingRecords.REFUSE
) -> Callable[[Path, Store, Path], object]:
    def imported(path: Path, store: Store, cache: Path) -> object:
        return import_file(
            FileImportRequest(path=path, profile=profile),
            store,
            cache,
            imported_on=IMPORTED_ON,
            instruments=STATIC_TABLE,
            differing=differing,
        )

    return imported


LAYOUTS = [
    Layout("DBN 1-minute bars", MINUTE, False, True, dbn_bars, through_databento),
    Layout("DBN trades", SECOND, True, False, dbn_trades, through_databento),
    Layout(
        "NinjaTrader 1-minute bars",
        MINUTE,
        False,
        True,
        ninjatrader_bars,
        through_a_profile(PRESETS["ninjatrader"]),
    ),
    Layout(
        "prints stamped to the second",
        SECOND,
        True,
        False,
        second_stamped_prints,
        through_a_profile(SECOND_STAMPED_PRINTS),
    ),
]


@st.composite
def streams(draw: st.DrawFn, layout: Layout, opens: Sequence[int]) -> list[Record]:
    """A stream in clock order: in each session a run of three to five neighbouring instants,
    each holding one record, or one to three where the layout's instants hold prints."""
    records: list[Record] = []
    for trade_date, session_open in zip(TRADE_DATES, opens, strict=True):
        first = draw(st.integers(0, 600))
        for step in range(draw(st.integers(3, 5))):
            held = draw(st.integers(1, 3)) if layout.prints else 1
            instant = session_open + (first + step) * layout.unit
            records += [
                Record(len(records) + place, instant, place, trade_date) for place in range(held)
            ]
    return records


@st.composite
def cuts(draw: st.DrawFn, layout: Layout, stream: Sequence[Record]) -> tuple[int, int]:
    """Where file B starts and file A stops, both inside one partition, so that the partition
    takes a record only A holds, one both hold, and one only B holds: B starts on the first
    record of an instant after the partition's first, and A stops after it, before the
    partition's last record, inside an instant where the draw falls there."""
    key = draw(st.sampled_from(sorted({layout.key(record) for record in stream})))
    inside = [record for record in stream if layout.key(record) == key]
    last = inside[-1].index
    starts = [
        record.index
        for record in inside[1:]
        if record.place == 0 and record.instant != inside[0].instant and record.index < last
    ]
    start = draw(st.sampled_from(starts))
    return start, draw(st.integers(start + 1, last))


def stored_rows(store: Store) -> dict[str, list[tuple[object, ...]]]:
    """Each partition of the store with its rows, and each `dataset.json` with its bytes."""
    rows: dict[str, list[tuple[object, ...]]] = {}
    for file in store.list_partitions():
        path = file.partition.relative_path().as_posix()
        rows[path] = store.scan_partition(file.partition).collect().rows()
    for described in store.folder.rglob("dataset.json"):
        rows[described.relative_to(store.folder).as_posix()] = [(described.read_bytes(),)]
    return rows


@pytest.mark.parametrize("layout", LAYOUTS, ids=lambda layout: layout.name)
def test_a_range_as_one_file_or_as_two_that_overlap_in_either_order_leaves_the_same_rows(
    layout: Layout, tmp_path: Path
) -> None:
    # Done means 1: file A is the stream's start and file B its end; the two overlap inside a
    # month of bars or a trade date of prints, which so takes a record only A holds, one both
    # hold, and one only B holds, and A may stop inside an instant of prints, which B holds
    # whole. The whole stream, A then B, and B then A leave one store.
    cache = tmp_path / "cache"
    sessions = STATIC_TABLE.sessions_of("ES", cache)
    opens = [sessions.session(trade_date).open for trade_date in TRADE_DATES]
    examples = iter(range(1_000_000))

    @settings(
        max_examples=5,
        deadline=None,
        database=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    @given(drawn=st.data())
    def either_order_gives_the_whole(drawn: st.DataObject) -> None:
        stream = drawn.draw(streams(layout, opens))
        start, stop = drawn.draw(cuts(layout, stream))
        folder = tmp_path / f"example-{next(examples)}"
        files = {
            "whole": layout.written(folder / "files" / "whole", stream),
            "a": layout.written(folder / "files" / "a", stream[:stop]),
            "b": layout.written(folder / "files" / "b", stream[start:]),
        }
        stores = {}
        for name, order in (
            ("whole", ["whole"]),
            ("a then b", ["a", "b"]),
            ("b then a", ["b", "a"]),
        ):
            stores[name] = Store(folder / name.replace(" ", "-"))
            for file in order:
                layout.imported(files[file], stores[name], cache)

        whole = stored_rows(stores["whole"])
        kept = [rows for path, rows in whole.items() if path.endswith("part.parquet")]
        assert sum(len(rows) for rows in kept) == len(stream)
        assert stored_rows(stores["a then b"]) == whole
        assert stored_rows(stores["b then a"]) == whole
        # ADR-0021: a partition's bytes, and so its hash, follow from its rows.
        as_one_file = partition_hashes(stores["whole"])
        assert partition_hashes(stores["a then b"]) == as_one_file
        assert partition_hashes(stores["b then a"]) == as_one_file
        # Done means 2, a merge run a second time: the stream as one file, every record of
        # which the merged store holds, writes no partition, digest, or dataset.json.
        merged = stores["a then b"]
        before = files_but_the_originals(merged)
        layout.imported(files["whole"], merged, cache)
        assert files_but_the_originals(merged) == before

    either_order_gives_the_whole()


def tree(folder: Path) -> dict[str, tuple[str, int]]:
    """Every file under `folder` with the SHA-256 of its bytes and its modification time."""
    return {
        path.relative_to(folder).as_posix(): (
            hashlib.sha256(path.read_bytes()).hexdigest(),
            path.stat().st_mtime_ns,
        )
        for path in sorted(folder.rglob("*"))
        if path.is_file()
    }


def files_but_the_originals(store: Store) -> dict[str, tuple[str, int]]:
    """The store's files, each with its hash and time, without the originals kept under `raw`,
    where every import keeps its own."""
    return {path: file for path, file in tree(store.folder).items() if not path.startswith("raw/")}


def partition_hashes(store: Store) -> dict[str, str]:
    """The SHA-256 of each partition's file in the store."""
    return {
        path: sha256
        for path, (sha256, _) in tree(store.folder).items()
        if path.endswith("part.parquet")
    }


def es_bars(
    *opens: int, close: int = 6_750_000_000_000, instrument_id: int = 1001
) -> list[OHLCVMsg]:
    return [
        OHLCVMsg(ONE_MINUTE, 1, instrument_id, instant, close, close + TICK, close - TICK, close, 10)
        for instant in opens
    ]  # fmt: skip


def march_file(
    folder: Path, name: str, bars: list[OHLCVMsg], mappings: Sequence[SymbolMapping] = ESH6
) -> Path:
    content = dbn_content(Schema("ohlcv-1m"), mappings, bars)
    return write_dbn(folder / "files" / name / "es.ohlcv-1m.dbn", content)


MARCH_9 = (utc(2026, 3, 9, 14, 30), utc(2026, 3, 9, 14, 31), utc(2026, 3, 9, 14, 32))
MARCH = Partition(
    dataset=Dataset(provider="databento", schema_name=parse_schema_name("ohlcv-1m"), root="ES"),
    contract="ESH2026",
    key=YearMonth(year=2026, month=3),
)


def march_store(tmp_path: Path) -> Store:
    """A store holding three one-minute bars of ESH2026 on 2026-03-09, from a DBN file."""
    store = Store(tmp_path / "data")
    through_databento(march_file(tmp_path, "first", es_bars(*MARCH_9)), store, tmp_path / "cache")
    return store


def test_a_file_of_records_the_store_holds_writes_no_partition(tmp_path: Path) -> None:
    # Done means 2, a merge run a second time: the same file again reads as imported and
    # touches nothing, and its records under another file, which the raw manifest does not
    # know, are held one by one, so that no partition, digest, or dataset.json is written.
    store = march_store(tmp_path)
    before = tree(store.folder)
    again = march_file(tmp_path, "first", es_bars(*MARCH_9))
    part = march_file(tmp_path, "part", es_bars(*MARCH_9[:2]))

    through_databento(again, store, tmp_path / "cache")
    unchanged = tree(store.folder)
    held = import_databento(part, store, tmp_path / "cache", imported_on=IMPORTED_ON)

    after = tree(store.folder)
    assert unchanged == before
    assert {path: after[path] for path in before if not path.startswith("raw/")} == {
        path: before[path] for path in before if not path.startswith("raw/")
    }
    assert len(store.raw.manifest().files) == 2
    (merge,) = held.files[0].merges
    assert (merge.records_added, merge.records_held) == (0, 2)
    assert (merge.partitions_changed, merge.partitions_unchanged) == (0, 1)


def test_a_file_that_changes_no_partition_is_not_gone_over_again_to_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The code review of step 5.14: a DBN file was decoded a third time, and an export's
    # partitions gone over again, though the check had found nothing for the pass to write.
    store, cache = march_store(tmp_path), tmp_path / "cache"
    through_a_profile(PRESETS["ninjatrader"])(SAMPLES["ninjatrader"][0], store, cache)
    part = march_file(tmp_path, "part", es_bars(*MARCH_9[:2]))
    shorter = sample_lines("ninjatrader")[:-1]
    export = written_export(tmp_path / "exports", "ES 03-26.Last.txt", shorter)
    monkeypatch.setattr("fefat.market.importers.databento.write_records", refusing)
    monkeypatch.setattr("fefat.market.importers.file_import.write_merges", refusing)

    through_databento(part, store, cache)
    through_a_profile(PRESETS["ninjatrader"])(export, store, cache)

    assert len(store.raw.manifest().files) == 4


def test_a_databento_file_whose_later_month_differs_writes_none_of_its_earlier_months(
    tmp_path: Path,
) -> None:
    # Done means 2 and D-98: the file's bars of January and February are complete, and were
    # written, before its bar of March refused the file. The whole file is checked first now.
    store = march_store(tmp_path)
    before = tree(store.folder)
    earlier = es_bars(utc(2026, 1, 12, 14, 30), utc(2026, 2, 10, 14, 30))
    differing = es_bars(MARCH_9[1], close=6_751_000_000_000)

    with pytest.raises(ValueError, match=r"got 1 with other values .* trade date 2026-03-09"):
        through_databento(
            march_file(tmp_path, "later", [*earlier, *differing]), store, tmp_path / "cache"
        )

    assert tree(store.folder) == before


def test_a_file_counting_sizes_in_another_unit_is_refused_though_it_adds_nothing(
    tmp_path: Path,
) -> None:
    # The design review of step 5.14: the unit was checked only before a new partition was
    # written, so a file of records the store holds, or of a stored partition's new records,
    # passed whatever its unit.
    store = march_store(tmp_path)
    tenths = DatasetMetadata(
        size_unit=SizeUnit(lot=Decimal("0.1"), asset="contract"),
        origin=DatasetOrigin.IMPORT,
        licence_scope=store.dataset_metadata(MARCH.dataset).licence_scope,
    )
    store.write_dataset_metadata(MARCH.dataset, tenths)
    before = tree(store.folder)

    with pytest.raises(ValueError, match="Expected the size unit of databento/ohlcv-1m/root=ES"):
        through_databento(
            march_file(tmp_path, "part", es_bars(*MARCH_9[:2])), store, tmp_path / "cache"
        )

    assert tree(store.folder) == before


def test_a_file_that_overlaps_a_stored_month_without_sharing_a_bar_is_refused(
    tmp_path: Path,
) -> None:
    store = march_store(tmp_path)
    before = tree(store.folder)
    between = es_bars(MARCH_9[0] + MINUTE // 2, MARCH_9[1] + MINUTE // 2)

    with pytest.raises(ValueError, match="got none in common"):
        through_databento(march_file(tmp_path, "shifted", between), store, tmp_path / "cache")

    assert tree(store.folder) == before


def test_a_file_under_another_instrument_id_for_a_stored_contract_is_refused(
    tmp_path: Path,
) -> None:
    store = march_store(tmp_path)
    before = tree(store.folder)
    renumbered = [mapping("ESH6", 1009, date(2025, 3, 21), date(2026, 3, 21))]
    later = es_bars(utc(2026, 3, 9, 14, 40), instrument_id=1009)

    with pytest.raises(ValueError, match="under the instrument_id it holds, 1001, got 1009"):
        through_databento(
            march_file(tmp_path, "renumbered", later, renumbered), store, tmp_path / "cache"
        )

    assert tree(store.folder) == before


def test_an_export_whose_bars_differ_from_the_stored_ones_is_refused_whole(
    tmp_path: Path,
) -> None:
    # The sample's bars again, the last one with one lot more, as an export made before its
    # last bar was complete differs from a later one.
    store = Store(tmp_path / "data")
    request = FileImportRequest(path=SAMPLES["ninjatrader"][0], profile=PRESETS["ninjatrader"])
    through_a_profile(PRESETS["ninjatrader"])(request.path, store, tmp_path / "cache")
    before = tree(store.folder)
    lines = with_a_lot_more_in_the_last_bar(sample_lines("ninjatrader"))
    changed = written_export(tmp_path / "exports", "ES 03-26.Last.txt", lines)

    with pytest.raises(ValueError, match=r"got 1 with other values .* trade date 2026-03-09"):
        through_a_profile(PRESETS["ninjatrader"])(changed, store, tmp_path / "cache")

    assert tree(store.folder) == before


@contextmanager
def the_second_write_failing(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """`Store.write_partition` failing at its second call from here on, as the write of a file
    another program holds open fails on Windows."""
    write_partition = Store.write_partition
    written: list[Partition] = []

    def failing_at_the_second(self: Store, partition: Partition, frame: pl.DataFrame) -> object:
        written.append(partition)
        if len(written) == 2:
            raise PermissionError(13, "The process cannot access the file")
        return write_partition(self, partition, frame)

    with monkeypatch.context() as patched:
        patched.setattr(Store, "write_partition", failing_at_the_second)
        yield


def test_an_import_cut_short_while_it_writes_is_finished_by_running_it_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The second partition's write fails: the first is written, the error says to run the
    # import again, and the second run, to which the first partition's records read as held,
    # leaves a clean import's store.
    bars = es_bars(utc(2026, 1, 12, 14, 30), utc(2026, 2, 10, 14, 30), *MARCH_9)
    source = march_file(tmp_path, "three-months", bars)
    clean = Store(tmp_path / "clean")
    through_databento(source, clean, tmp_path / "cache")
    store = Store(tmp_path / "data")

    with the_second_write_failing(monkeypatch), pytest.raises(ValueError, match="run the import"):
        through_databento(source, store, tmp_path / "cache")
    cut_short = len(store.list_partitions())
    through_databento(source, store, tmp_path / "cache")

    assert cut_short == 1
    assert stored_rows(store) == stored_rows(clean)
    assert [file.path for file in store.raw.manifest().files] == [
        file.path for file in clean.raw.manifest().files
    ]


def test_a_take_file_import_cut_short_and_run_again_records_what_it_was_told(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The code review of step 5.14: the manifest said that the file's records were taken where
    # a run counted records that differ, and the run that finishes a cut-short import counts
    # none: the first run took February's bar before March's write failed, so it reads as held.
    store, cache = Store(tmp_path / "data"), tmp_path / "cache"
    february = utc(2026, 2, 10, 14, 30)
    through_databento(march_file(tmp_path, "first", es_bars(february, *MARCH_9)), store, cache)
    revised = [*es_bars(february, close=6_751_000_000_000), *es_bars(utc(2026, 3, 9, 14, 40))]
    source = march_file(tmp_path, "revised", revised)
    take = DifferingRecords.TAKE_THE_FILE

    with the_second_write_failing(monkeypatch), pytest.raises(ValueError, match="run the import"):
        import_databento(source, store, cache, imported_on=IMPORTED_ON, differing=take)
    again = import_databento(source, store, cache, imported_on=IMPORTED_ON, differing=take)

    (merge,) = again.files[0].merges
    assert (merge.records_added, merge.records_held, merge.records_differing) == (1, 1, 0)
    assert sorted(file.vendor_version for file in store.raw.manifest().files) == [
        "DBN 3",
        "DBN 3, the file's records taken where they differ",
    ]


def refusing(*_: object, **__: object) -> None:
    raise ValueError("refused before a partition was written")


@pytest.mark.parametrize(
    "refuses",
    ["fefat.market.importers.databento.checked_raw_path", "fefat.market.raw_files.RawFiles.write"],
    ids=["the raw path's check", "the copy under raw"],
)
def test_what_can_refuse_a_databento_file_does_so_before_its_first_partition_is_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, refuses: str
) -> None:
    # The design review of step 5.14: a single file's raw path was checked, and its copy under
    # `raw` verified against its hash, only after its partitions were written.
    monkeypatch.setattr(refuses, refusing)
    source = march_file(tmp_path, "first", es_bars(*MARCH_9))

    with pytest.raises(ValueError, match="refused before a partition was written"):
        through_databento(source, Store(tmp_path / "data"), tmp_path / "cache")

    assert tree(tmp_path / "data") == {}


@pytest.mark.parametrize(
    "refuses",
    [
        "fefat.market.importers.file_import.instrument_is_saved",
        "fefat.market.raw_files.RawFiles.write",
    ],
    ids=["the new instrument", "the copy under raw"],
)
def test_what_can_refuse_an_export_does_so_before_its_first_partition_is_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, refuses: str
) -> None:
    request = FileImportRequest(path=five_minute_file(tmp_path), profile=a_new_product_profile())
    store = Store(tmp_path / "data")
    monkeypatch.setattr(refuses, refusing)

    with pytest.raises(ValueError, match="refused before a partition was written"):
        import_file(
            request,
            store,
            tmp_path / "cache",
            imported_on=IMPORTED_ON,
            instruments=instrument_table(store.folder),
        )

    assert tree(tmp_path / "data") == {}


TAKE_THE_FILE_OR_ITS_TEXT = pytest.mark.parametrize(
    "take", [DifferingRecords.TAKE_THE_FILE, "take-file"], ids=["the option", "its text"]
)
"""The option, and the text a command or a notebook gives for it, which the write pass read as
refuse while the report said taken (the ponytail review of step 5.14)."""


@TAKE_THE_FILE_OR_ITS_TEXT
def test_the_files_bars_stand_where_a_databento_import_takes_them(
    tmp_path: Path, take: DifferingRecords | str
) -> None:
    # `--differing take-file`: the bar the two dispute is the file's, the manifest says that
    # the import was told so, and the file imported again reads as imported.
    store = march_store(tmp_path)
    revised = [*es_bars(MARCH_9[1], close=6_751_000_000_000), *es_bars(utc(2026, 3, 9, 14, 40))]
    source = march_file(tmp_path, "revised", revised)

    report = import_databento(
        source, store, tmp_path / "cache", imported_on=IMPORTED_ON, differing=take
    )
    again = import_databento(source, store, tmp_path / "cache", imported_on=IMPORTED_ON)

    (merge,) = report.files[0].merges
    counted = (merge.records_added, merge.records_held, merge.records_differing)
    assert counted == (1, 0, 1) and merge.stored_records_disputed == 1
    assert store.scan_partition(MARCH).collect().get_column("close").to_list() == [
        6_750_000_000_000,
        6_751_000_000_000,
        6_750_000_000_000,
        6_750_000_000_000,
    ]
    assert "1 that differ, the file's taken in place of 1 stored record" in report.summary()
    assert sorted(file.vendor_version for file in store.raw.manifest().files) == [
        "DBN 3",
        "DBN 3, the file's records taken where they differ",
    ]
    assert len(again.already_imported) == 1


@TAKE_THE_FILE_OR_ITS_TEXT
def test_the_files_bars_stand_where_a_file_import_takes_them(
    tmp_path: Path, take: DifferingRecords | str
) -> None:
    store, cache = Store(tmp_path / "data"), tmp_path / "cache"
    through_a_profile(PRESETS["ninjatrader"])(SAMPLES["ninjatrader"][0], store, cache)
    sample = sample_lines("ninjatrader")
    lines = with_a_lot_more_in_the_last_bar(sample)
    changed = written_export(tmp_path / "exports", "ES 03-26.Last.txt", lines)
    request = FileImportRequest(path=changed, profile=PRESETS["ninjatrader"])

    report = import_file(
        request, store, cache, imported_on=IMPORTED_ON, instruments=STATIC_TABLE, differing=take
    )
    again = import_file(request, store, cache, imported_on=IMPORTED_ON, instruments=STATIC_TABLE)

    assert isinstance(report, FileImportReport) and isinstance(again, AlreadyImported)
    merge = report.merge
    assert (merge.records_added, merge.records_differing, merge.stored_records_disputed) == (
        0,
        1,
        1,
    )
    assert (merge.partitions_changed, merge.partitions_unchanged) == (1, 0)
    (march,) = (file.partition for file in store.list_partitions())
    volume = int(sample[-1].rsplit(";", 1)[1])
    assert store.scan_partition(march).collect().item(-1, "volume") == volume + 1
    assert sorted(file.vendor_version for file in store.raw.manifest().files) == [
        "import profile ninjatrader",
        "import profile ninjatrader, the file's records taken where they differ",
    ]


def test_an_import_told_that_the_files_stand_records_so_though_nothing_differs(
    tmp_path: Path,
) -> None:
    # The manifest records the rule an import ran under, not what one run of it counted.
    store, cache = Store(tmp_path / "data"), tmp_path / "cache"
    take = DifferingRecords.TAKE_THE_FILE
    first = march_file(tmp_path, "first", es_bars(*MARCH_9))

    import_databento(first, store, cache, imported_on=IMPORTED_ON, differing=take)
    through_a_profile(PRESETS["ninjatrader"], take)(SAMPLES["ninjatrader"][0], store, cache)

    assert sorted(file.vendor_version for file in store.raw.manifest().files) == [
        "DBN 3, the file's records taken where they differ",
        "import profile ninjatrader, the file's records taken where they differ",
    ]


def session_prints(cache: Path, trade_date: date, *held: int) -> list[Record]:
    """Prints of ESM2026 in the session of `trade_date`, `held` of them in each of as many
    seconds in a row."""
    opened = STATIC_TABLE.sessions_of("ES", cache).session(trade_date).open
    records: list[Record] = []
    for second, prints in enumerate(held):
        instant = opened + (600 + second) * SECOND
        records += [
            Record(len(records) + place, instant, place, trade_date) for place in range(prints)
        ]
    return records


def store_of_prints(tmp_path: Path, stream: Sequence[Record]) -> Store:
    """A store holding the stream, imported as one file of prints stamped to the second."""
    store = Store(tmp_path / "data")
    whole = second_stamped_prints(tmp_path / "whole", stream)
    through_a_profile(SECOND_STAMPED_PRINTS)(whole, store, tmp_path / "cache")
    return store


@pytest.mark.parametrize("differing", list(DifferingRecords))
def test_prints_that_start_inside_a_stored_second_are_refused_whatever_the_import_is_told(
    tmp_path: Path, differing: DifferingRecords
) -> None:
    # The code review of step 5.14: prints without a sequence of their own are told apart by
    # their place in their second, so a file that starts inside one reads as disputing it, and
    # taken, it would leave the second's last two prints in place of its three. The file's
    # first second is its contract's first, in the first of its two sessions.
    cache = tmp_path / "cache"
    monday, tuesday = TRADE_DATES[:2]
    stream = [*session_prints(cache, monday, 3, 2), *session_prints(cache, tuesday, 1)]
    store = store_of_prints(tmp_path, stream)
    before = tree(store.folder)
    inside = second_stamped_prints(tmp_path / "inside", stream[1:])

    with pytest.raises(
        ValueError, match=r"to start on a whole instant, .* got 2 at its first instant, 2026-03-2"
    ):
        through_a_profile(SECOND_STAMPED_PRINTS, differing)(inside, store, cache)

    assert tree(store.folder) == before


@pytest.mark.parametrize("differing", list(DifferingRecords))
def test_prints_that_stop_inside_a_second_they_dispute_are_refused_whatever_the_import_is_told(
    tmp_path: Path, differing: DifferingRecords
) -> None:
    # The engine accuracy review of step 5.14: the file's last second, in the second of its two
    # sessions, holds two prints, the second of them other than the stored one, where the store
    # holds three; taken, it would drop the third, which the file never held.
    cache = tmp_path / "cache"
    monday, tuesday = TRADE_DATES[:2]
    stream = [*session_prints(cache, monday, 1), *session_prints(cache, tuesday, 1, 3)]
    store = store_of_prints(tmp_path, stream)
    before = tree(store.folder)
    stopping = [*stream[:3], replace(stream[3], place=7)]
    source = second_stamped_prints(tmp_path / "stopping", stopping)

    with pytest.raises(ValueError, match="got 2 prints where the store holds 3"):
        through_a_profile(SECOND_STAMPED_PRINTS, differing)(source, store, cache)

    assert tree(store.folder) == before


def test_seconds_of_prints_the_file_holds_whole_are_taken_where_the_files_stand(
    tmp_path: Path,
) -> None:
    # A second between the file's first and its last is the file's whole, here the first second
    # of its second session, which is no edge of the file though it opens a partition; and its
    # last second holds as many prints as the store's. Both are the file's once the import is
    # told so.
    cache = tmp_path / "cache"
    monday, tuesday = TRADE_DATES[:2]
    stream = [*session_prints(cache, monday, 1), *session_prints(cache, tuesday, 2, 2)]
    store = store_of_prints(tmp_path, stream)
    revised = [stream[0], replace(stream[1], place=7), *stream[2:4], replace(stream[4], place=9)]
    source = second_stamped_prints(tmp_path / "revised", revised)
    request = FileImportRequest(path=source, profile=SECOND_STAMPED_PRINTS)

    with pytest.raises(ValueError, match="got 4 with other values"):
        import_file(request, store, cache, imported_on=IMPORTED_ON, instruments=STATIC_TABLE)
    report = import_file(
        request,
        store,
        cache,
        imported_on=IMPORTED_ON,
        instruments=STATIC_TABLE,
        differing=DifferingRecords.TAKE_THE_FILE,
    )

    assert isinstance(report, FileImportReport)
    merge = report.merge
    assert (merge.records_added, merge.records_held, merge.records_differing) == (0, 1, 4)
    assert merge.stored_records_disputed == 4
    assert (merge.partitions_changed, merge.partitions_unchanged) == (1, 1)
    sessions = {file.partition.key: file.partition for file in store.list_partitions()}
    assert store.scan_partition(sessions[tuesday]).collect().get_column("size").to_list() == [
        8,
        2,
        1,
        10,
    ]


def test_an_export_that_starts_on_the_bar_it_completes_is_taken_where_the_files_stand(
    tmp_path: Path,
) -> None:
    # A bar has its instant to itself, so an export that starts on the bar it completes holds
    # that instant whole: the refusal of a file's first instant in dispute is for prints
    # numbered by their place alone.
    store, cache = Store(tmp_path / "data"), tmp_path / "cache"
    ninjatrader = PRESETS["ninjatrader"]
    through_a_profile(ninjatrader)(SAMPLES["ninjatrader"][0], store, cache)
    first, *rest = sample_lines("ninjatrader")[-3:]
    completed = with_a_lot_more_in_the_last_bar([first])
    later = written_export(tmp_path / "exports", "ES 03-26.Last.txt", [*completed, *rest])

    report = through_a_profile(ninjatrader, DifferingRecords.TAKE_THE_FILE)(later, store, cache)

    assert isinstance(report, FileImportReport)
    assert (report.merge.records_held, report.merge.records_differing) == (2, 1)


def test_an_export_that_only_carries_a_dated_contract_on_is_merged(tmp_path: Path) -> None:
    # A dated contract's file needs no bar in common with the store: the rule of a shared bar
    # is for a back-adjusted series alone, whose earlier prices a roll moves.
    store, cache = Store(tmp_path / "data"), tmp_path / "cache"
    ninjatrader, lines = PRESETS["ninjatrader"], sample_lines("ninjatrader")
    earlier = written_export(tmp_path / "earlier", "ES 03-26.Last.txt", lines[:-100])
    later = written_export(tmp_path / "later", "ES 03-26.Last.txt", lines[-100:])
    through_a_profile(ninjatrader)(earlier, store, cache)

    report = through_a_profile(ninjatrader)(later, store, cache)

    assert isinstance(report, FileImportReport)
    merge = report.merge
    assert (merge.records_added, merge.records_held, merge.records_differing) == (100, 0, 0)


BACK_ADJUSTED = PRESETS["tradingview"].model_copy(
    update={
        "name": "es-back-adjusted",
        "series": SeriesKind.CONTINUOUS_BACK_ADJUSTED,
        "instrument": "ES",
        "contract_in_file_name": None,
    }
)
"""TradingView's layout read as one back-adjusted continuous series of ES."""


def adjusted_export(folder: Path, bars: Sequence[str], moved_by: int = 0) -> Path:
    """An export of the back-adjusted series: `bars`, lines of TradingView's sample, each price
    moved by `moved_by` points, as the platform moves every bar before a roll at that roll."""
    header = sample_lines("tradingview")[0]
    moved = [
        ",".join([time, *(str(Decimal(price) + moved_by) for price in prices), volume])
        for time, *prices, volume in (bar.split(",") for bar in bars)
    ]
    return written_export(folder, "ES continuous, 1.csv", [header, *moved])


@pytest.mark.parametrize(
    ("stored", "moved_by", "counted"),
    [(None, 5, "100 of its records at other values"), (-100, 0, "100 that the store lacks")],
    ids=["adjusted again since", "carried on without a bar in common"],
)
def test_a_file_without_a_bar_of_the_stored_back_adjusted_series_is_refused_whatever_it_is_told(
    tmp_path: Path, stored: int | None, moved_by: int, counted: str
) -> None:
    # The leakage audit of step 5.14: a platform adjusts a back-adjusted series again at each
    # roll, so a later export holds every bar before that roll at other prices. Its last hundred
    # bars taken over the stored ones, or added after them, would leave two price bases in one
    # series, and without a bar the two share, the file cannot be told from one adjusted since.
    bars = sample_lines("tradingview")[1:]
    store, cache = Store(tmp_path / "data"), tmp_path / "cache"
    first = adjusted_export(tmp_path / "first", bars[:stored])
    through_a_profile(BACK_ADJUSTED)(first, store, cache)
    before = tree(store.folder)
    later = adjusted_export(tmp_path / "later", bars[-100:], moved_by)

    for differing in DifferingRecords:
        with pytest.raises(ValueError, match=f"the store holds of the back-adjusted .*{counted}"):
            through_a_profile(BACK_ADJUSTED, differing)(later, store, cache)

    assert tree(store.folder) == before


def test_a_back_adjusted_series_takes_its_last_bar_from_a_file_that_shares_its_other_bars(
    tmp_path: Path,
) -> None:
    # The code review of the fixes: an export that holds stored bars unchanged was made on the
    # store's price basis, so its one bar that differs, the store's last, which an earlier export
    # took before it was complete, is left to the rule for differing records.
    bars = sample_lines("tradingview")[1:]
    store, cache = Store(tmp_path / "data"), tmp_path / "cache"
    through_a_profile(BACK_ADJUSTED)(adjusted_export(tmp_path / "first", bars), store, cache)
    time, *prices, volume = bars[-1].split(",")
    completed = ",".join([time, *prices, str(int(volume) + 1)])
    later = adjusted_export(tmp_path / "later", [*bars[-100:-1], completed])
    request = FileImportRequest(path=later, profile=BACK_ADJUSTED)

    with pytest.raises(ValueError, match="got 1 with other values"):
        import_file(request, store, cache, imported_on=IMPORTED_ON, instruments=STATIC_TABLE)
    report = import_file(
        request,
        store,
        cache,
        imported_on=IMPORTED_ON,
        instruments=STATIC_TABLE,
        differing=DifferingRecords.TAKE_THE_FILE,
    )

    assert isinstance(report, FileImportReport)
    merge = report.merge
    assert (merge.records_added, merge.records_held, merge.records_differing) == (0, 99, 1)
    (month,) = (file.partition for file in store.list_partitions())
    assert store.scan_partition(month).collect().item(-1, "volume") == int(volume) + 1


@pytest.mark.parametrize(
    ("switched_on", "earlier", "later", "refusal"),
    [
        (
            date(2026, 2, 1),
            utc(2026, 1, 12, 14, 30),
            utc(2026, 2, 10, 14, 30),
            "under the instrument_id this file gives ESH2026 before them, 1001, got 1009",
        ),
        (
            date(2026, 2, 16),
            utc(2026, 2, 10, 14, 30),
            utc(2026, 2, 17, 14, 30),
            "under one instrument_id, got 1001, 1009",
        ),
    ],
    ids=["in two months", "in one month"],
)
def test_a_databento_file_that_gives_a_contract_new_to_the_store_two_ids_is_refused(
    tmp_path: Path, switched_on: date, earlier: int, later: int, refusal: str
) -> None:
    # Done means 2, from the plan's design review: with no stored partition beside them, a
    # file whose symbology names ESH2026 by one id and then another wrote it under both, and
    # one cut short while it wrote was refused when run again, its first months then stored.
    intervals = [
        Interval(date(2025, 3, 21), switched_on, "1001"),
        Interval(switched_on, date(2026, 3, 21), "1009"),
    ]
    bars = [*es_bars(earlier), *es_bars(later, instrument_id=1009)]
    source = march_file(tmp_path, "two-ids", bars, [SymbolMapping("ESH6", intervals)])

    with pytest.raises(ValueError, match=refusal):
        through_databento(source, Store(tmp_path / "data"), tmp_path / "cache")

    assert tree(tmp_path / "data") == {}
