"""Files that overlap stored data, through both importers (step 5.14, ADR-0021, Done means 1 and
2): a range imported as one file, or as two files that overlap, in either order, leaves the same
rows in the same partitions, for bars kept by month and for prints kept by trade date; a file of
records the store already holds writes no partition; a refused file changes no byte of the
store, the DBN importer included; and an import cut short while it writes is finished by running
it again. Every file is generated in the test's folder, its values made up from its instants."""

import hashlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest
from databento_dbn import F_LAST, Action, OHLCVMsg, RType, Schema, Side, TradeMsg
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from dbn_files import SymbolMapping, dbn_content, mapping, utc, write_dbn
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
        """A price on ES's tick, made up from the record's instant and place."""
        return FIVE_THOUSAND + TICK * ((self.instant // unit + self.place) % 40)


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


def through_a_profile(profile: ImportProfile) -> Callable[[Path, Store, Path], object]:
    def imported(path: Path, store: Store, cache: Path) -> object:
        request = FileImportRequest(path=path, profile=profile)
        return import_file(request, store, cache, imported_on=IMPORTED_ON, instruments=STATIC_TABLE)

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
    @given(data=st.data())
    def either_order_gives_the_whole(data: st.DataObject) -> None:
        stream = data.draw(streams(layout, opens))
        start, stop = data.draw(cuts(layout, stream))
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
    through_databento(part, store, tmp_path / "cache")

    after = tree(store.folder)
    assert unchanged == before
    assert {path: after[path] for path in before if not path.startswith("raw/")} == {
        path: before[path] for path in before if not path.startswith("raw/")
    }
    assert len(store.raw.manifest().files) == 2


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


def test_an_import_cut_short_while_it_writes_is_finished_by_running_it_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The second partition's write fails, as a file another program holds open fails on
    # Windows: the first is written, the error says to run the import again, and the second
    # run, to which the first partition's records read as held, leaves a clean import's store.
    bars = es_bars(utc(2026, 1, 12, 14, 30), utc(2026, 2, 10, 14, 30), *MARCH_9)
    source = march_file(tmp_path, "three-months", bars)
    clean = Store(tmp_path / "clean")
    through_databento(source, clean, tmp_path / "cache")
    store = Store(tmp_path / "data")
    write_partition = Store.write_partition
    written: list[Partition] = []

    def failing_at_the_second(self: Store, partition: Partition, frame: pl.DataFrame) -> object:
        written.append(partition)
        if len(written) == 2:
            raise PermissionError(13, "The process cannot access the file")
        return write_partition(self, partition, frame)

    with monkeypatch.context() as patched:
        patched.setattr(Store, "write_partition", failing_at_the_second)
        with pytest.raises(ValueError, match="run the import again"):
            through_databento(source, store, tmp_path / "cache")
    cut_short = len(store.list_partitions())
    through_databento(source, store, tmp_path / "cache")

    assert cut_short == 1
    assert stored_rows(store) == stored_rows(clean)
    assert [file.path for file in store.raw.manifest().files] == [
        file.path for file in clean.raw.manifest().files
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


def test_the_files_bars_stand_where_a_databento_import_takes_them(tmp_path: Path) -> None:
    # `--differing take-file`: the bar the two dispute is the file's, the manifest says that
    # the import took it, and the file imported again reads as imported.
    store = march_store(tmp_path)
    revised = [*es_bars(MARCH_9[1], close=6_751_000_000_000), *es_bars(utc(2026, 3, 9, 14, 40))]
    source = march_file(tmp_path, "revised", revised)

    report = import_databento(
        source,
        store,
        tmp_path / "cache",
        imported_on=IMPORTED_ON,
        differing=DifferingRecords.TAKE_THE_FILE,
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
        "DBN 3, differing records taken from the file",
    ]
    assert len(again.already_imported) == 1


def test_the_files_bars_stand_where_a_file_import_takes_them(tmp_path: Path) -> None:
    store, cache = Store(tmp_path / "data"), tmp_path / "cache"
    through_a_profile(PRESETS["ninjatrader"])(SAMPLES["ninjatrader"][0], store, cache)
    sample = sample_lines("ninjatrader")
    lines = with_a_lot_more_in_the_last_bar(sample)
    changed = written_export(tmp_path / "exports", "ES 03-26.Last.txt", lines)
    request = FileImportRequest(path=changed, profile=PRESETS["ninjatrader"])

    report = import_file(
        request,
        store,
        cache,
        imported_on=IMPORTED_ON,
        instruments=STATIC_TABLE,
        differing=DifferingRecords.TAKE_THE_FILE,
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
        "import profile ninjatrader, differing records taken from the file",
    ]
