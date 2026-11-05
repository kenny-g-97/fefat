import os
import shutil
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from polars.testing import assert_frame_equal

import fefat
import gen_fixtures
from fefat.config import resolve_paths
from fefat.market import instruments
from fefat.market.api import DATASETS_COLUMNS, SIGNAL_BAR_COLUMNS, datasets, load, roll_calendar
from fefat.market.calendar import SessionTable, sessions_of
from fefat.market.catalog import CATALOG, RollRule
from fefat.market.continuous import RollCalendar, volume_rolls
from fefat.market.instruments import InstrumentTable
from fefat.market.layout import Dataset, Partition, PartitionRequest
from fefat.market.quality import assess_quality
from fefat.market.quality_report import write_quality_report
from fefat.market.schema import parse_schema_name
from fefat.market.store import Store

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "fixtures"
SYNTHETIC = FIXTURES / "synthetic"
MARCH_5, MARCH_6, MARCH_9 = date(2026, 3, 5), date(2026, 3, 6), date(2026, 3, 9)
BUCKETS_OF_FIVE_MINUTES = 276
"""A CME equity index session of 23 hours, 17:00 to 16:00 Chicago, in 5-minute buckets."""


def utc(*fields: int) -> int:
    """The instant of a UTC date and time, in nanoseconds since the Unix epoch."""
    year, month, day, *clock = fields
    return int(datetime(year, month, day, *clock, tzinfo=UTC).timestamp()) * 1_000_000_000


@pytest.fixture
def fixtures_as_data(monkeypatch: pytest.MonkeyPatch) -> None:
    """The repository's fixtures as the data folder, which `load` only reads."""
    monkeypatch.setenv("FEFAT_DATA_DIR", str(FIXTURES))


def data_folder_with(monkeypatch: pytest.MonkeyPatch, folder: Path, *schemas: str) -> Path:
    """`folder` as the data folder, holding the fixtures' datasets of `schemas`."""
    for schema in schemas:
        shutil.copytree(SYNTHETIC / schema, folder / "synthetic" / schema)
    monkeypatch.setenv("FEFAT_DATA_DIR", str(folder))
    return folder


def fixture_gap(tmp_path: Path) -> int:
    """The gap of the fixtures' roll from ESH2026 to ESM2026 at the open of 2026-03-09, from
    the roll calendar of their 1-minute bars (`fefat.market.continuous`)."""
    es = instruments.get("ES")
    sessions = sessions_of(es.session_calendar(), tmp_path)
    dataset = Dataset(provider="synthetic", schema_name=parse_schema_name("ohlcv-1m"), root="ES")
    request = PartitionRequest(dataset=dataset, start=date(2026, 3, 5), end=MARCH_9)
    bars = Store(FIXTURES).scan_contracts(request).collect()
    calendar = volume_rolls(bars, sessions, es, bars.select(pl.col("ts_close").max()).item())
    return calendar.rolls().item(0, "gap")


@pytest.mark.usefixtures("fixtures_as_data")
def test_a_continuous_load_returns_the_fronts_signal_bars_on_the_session_grid(
    tmp_path: Path,
) -> None:
    # The roll calendar decides each session's front from the session before it, so its rows,
    # and the series, start with the fixtures' second session, 2026-03-06; the front rolls from
    # ESH2026 to ESM2026 at the open of 03-09.
    bars = load("ES", "5m", "2026-03-05", "2026-03-09", fidelity="1m").collect()

    assert bars.schema == SIGNAL_BAR_COLUMNS
    assert bars.height == 2 * BUCKETS_OF_FIVE_MINUTES
    assert bars.group_by("trade_date", "contract").len().sort("trade_date").rows() == [
        (MARCH_6, "ESH2026", BUCKETS_OF_FIVE_MINUTES),
        (MARCH_9, "ESM2026", BUCKETS_OF_FIVE_MINUTES),
    ]
    assert bars.get_column("ts_open").is_sorted()
    assert bars.filter("roll_flag").select("contract", "ts_open").rows() == [
        ("ESM2026", utc(2026, 3, 8, 22))
    ]
    offsets = bars.group_by("contract").agg(pl.col("adj_offset").unique()).sort("contract")
    assert offsets.rows() == [("ESH2026", [0]), ("ESM2026", [-fixture_gap(tmp_path)])]
    assert bars.filter(pl.col("close") != pl.col("close_raw") + pl.col("adj_offset")).is_empty()
    assert bars.filter(pl.col("zero_volume") != (pl.col("volume") == 0)).is_empty()


@pytest.mark.usefixtures("fixtures_as_data")
def test_a_window_holds_the_same_rows_whatever_day_it_starts() -> None:
    # The roll calendar comes from the whole dataset, so a window starting at the roll still
    # flags the new front's first bar and adjusts its prices by the same offset.
    whole = load("ES", "5m", "2026-03-05", "2026-03-09").collect()

    rolled_day = load("ES", "5m", "2026-03-09", "2026-03-09").collect()

    assert_frame_equal(rolled_day, whole.filter(pl.col("trade_date") == MARCH_9))
    assert rolled_day.item(0, "roll_flag") is True


@pytest.mark.usefixtures("fixtures_as_data")
def test_a_load_per_contract_holds_each_contracts_own_grid_and_raw_prices() -> None:
    # ESM2026 trades from the first open but holds 26 minutes without trades on 2026-03-05,
    # which the grid fills as zero-volume rows at the close before them.
    bars = load("ES", "1m", "2026-03-05", "2026-03-09", continuous=False, fidelity="1m").collect()

    assert bars.group_by("contract").len().sort("contract").rows() == [
        ("ESH2026", 3 * 1380),
        ("ESM2026", 3 * 1380),
    ]
    assert bars.select(pl.col("zero_volume").sum()).item() == 26
    assert bars.filter(pl.col("adj_offset") != 0).is_empty()
    assert bars.filter(pl.col("close_raw") != pl.col("close")).is_empty()
    assert not bars.get_column("roll_flag").any()
    assert_frame_equal(bars, bars.sort("contract", "ts_open"))


@pytest.mark.usefixtures("fixtures_as_data")
def test_a_contract_loads_alone_and_a_perpetual_as_one_series() -> None:
    contract = load("ESM2026", "1m", "2026-03-05", "2026-03-09", fidelity="1m").collect()
    perpetual = load("BTCUSDT-PERP", "1h", "2026-03-07", "2026-03-07", fidelity="1m").collect()

    assert contract.get_column("contract").unique().to_list() == ["ESM2026"]
    assert contract.height == 3 * 1380
    assert perpetual.height == 24
    assert perpetual.get_column("contract").unique().to_list() == ["BTCUSDT-PERP"]


@pytest.mark.usefixtures("fixtures_as_data")
@pytest.mark.parametrize("symbol", ["ESM2026", "BTCUSDT-PERP"])
def test_a_continuous_load_of_what_no_roll_calendar_splices_is_refused(symbol: str) -> None:
    with pytest.raises(ValueError, match="Expected continuous=False or no continuous"):
        load(symbol, "1m", "2026-03-06", "2026-03-06", continuous=True)


@pytest.mark.usefixtures("fixtures_as_data")
def test_the_roll_calendar_is_the_one_load_splices_with(tmp_path: Path) -> None:
    # Step 2.9: a backtest across a roll takes its rolls from this calendar (F-ROL-01): the
    # fixtures' ES rolls once, at the open of 2026-03-09, where the spliced bars flag the front.
    calendar = roll_calendar("ES")
    ((trade_date, session_open, rolled_from, contract, gap, reason),) = calendar.rolls().rows()
    bars = load("ES", "1m", "2026-03-06", "2026-03-09").collect()
    flagged = bars.filter(pl.col("roll_flag"))

    assert (trade_date, rolled_from, contract, reason) == (MARCH_9, "ESH2026", "ESM2026", "volume")
    assert session_open == utc(2026, 3, 8, 22)
    assert gap == fixture_gap(tmp_path)
    assert flagged.get_column("contract").to_list() == ["ESM2026"]
    assert flagged.item(0, "ts_open") >= session_open


def test_loads_build_a_roll_calendar_once_while_its_bars_keep_their_stamp(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # D-71, step 3.3: a notebook's loop of loads and the feature cache's partitions build a
    # product's roll calendar once, and again once a partition of the bars it reads is written.
    store = Store(data_folder_with(monkeypatch, tmp_path, "ohlcv-1m"))
    built: list[RollCalendar] = []

    def counted_rolls(*arguments: Any) -> RollCalendar:
        built.append(volume_rolls(*arguments))
        return built[-1]

    monkeypatch.setattr("fefat.market.roll_calendars.volume_rolls", counted_rolls)
    load("ES", "5m", "2026-03-06", "2026-03-09")
    load("ES", "15m", "2026-03-09", "2026-03-09")
    rolls = roll_calendar("ES").rolls()
    built_once = len(built)
    (march,) = (
        file.partition
        for file in store.list_partitions()
        if file.partition.dataset.root == "ES" and file.partition.contract == "ESH2026"
    )
    store.write_partition(march, store.scan_partition(march).collect())

    assert built_once == 1
    assert roll_calendar("ES").rolls().equals(rolls)
    assert len(built) == 2


@pytest.mark.usefixtures("fixtures_as_data")
def test_a_continuous_load_of_a_product_whose_roll_rule_load_does_not_apply_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Step 2.9 (D-51): load rolls by volume alone, so a catalog that names open interest for ES
    # refuses the continuous load rather than rolling it by volume.
    by_open_interest = CATALOG.products[0].model_copy(
        update={"root": "ES", "roll_rule": RollRule.OPEN_INTEREST}
    )
    products = (*CATALOG.products, by_open_interest)
    monkeypatch.setattr(
        "fefat.market.roll_calendars.CATALOG", CATALOG.model_copy(update={"products": products})
    )

    with pytest.raises(ValueError, match="Expected the roll rule volume for ES"):
        load("ES", "1m", "2026-03-06", "2026-03-09")


@pytest.mark.usefixtures("fixtures_as_data")
def test_bars_built_from_trades_match_the_one_minute_bars_but_the_last_held_back() -> None:
    # The fixtures' trades end 50 ms before the close of 2026-03-09, and whether a later trade
    # came is not in the data, so the bucket that closes at the close is held back (D-43);
    # the last 1-second bar closes at the close, so the bars built from them are complete.
    from_trades = load("ES", "1m", "2026-03-06", "2026-03-09", fidelity="trades").collect()
    from_bars = load("ES", "1m", "2026-03-06", "2026-03-09", fidelity="1m").collect()
    from_seconds = load("ES", "5m", "2026-03-06", "2026-03-09", fidelity="1s").collect()

    compared = ("ts_open", "contract", "open", "high", "low", "close", "volume")
    assert from_bars.height == from_trades.height + 1
    assert from_bars.item(-1, "ts_open") == utc(2026, 3, 9, 20, 59)
    held = from_bars.head(from_trades.height)
    assert_frame_equal(from_trades.select(compared), held.select(compared))
    assert from_seconds.height == 2 * BUCKETS_OF_FIVE_MINUTES


@pytest.mark.usefixtures("fixtures_as_data")
def test_a_timeframe_finer_than_the_data_is_refused() -> None:
    with pytest.raises(ValueError, match="Expected a timeframe of 1m or coarser"):
        load("ES", "1s", "2026-03-06", "2026-03-06", fidelity="1m")


def test_without_finer_data_a_load_takes_the_one_minute_bars_and_trades_are_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    data_folder_with(monkeypatch, tmp_path, "ohlcv-1m")

    bars = load("ES", "1m", "2026-03-06", "2026-03-06").collect()

    assert bars.height == 1380
    with pytest.raises(ValueError, match="Expected trades of ES in the store, got none"):
        load("ES", "1m", "2026-03-06", "2026-03-06", fidelity="trades")


def test_a_window_whose_front_opens_without_trades_fills_from_the_session_before(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The copy's bars of 2026-03-09 start 10 minutes after the open. A window starting that day
    # reads the session before it too, so its first rows are the zero-volume buckets priced at
    # ESM2026's last close of 03-06, as in a window that starts earlier.
    store = Store(data_folder_with(monkeypatch, tmp_path, "ohlcv-1m"))
    late_open = (pl.col("trade_date") != MARCH_9) | (pl.col("ts_open") >= utc(2026, 3, 8, 22, 10))
    for file in store.list_partitions():
        rows = store.scan_partition(file.partition).collect()
        store.write_partition(file.partition, rows.filter(late_open))

    whole = load("ES", "1m", "2026-03-05", "2026-03-09").collect()
    one_day = load("ES", "1m", "2026-03-09", "2026-03-09").collect()

    assert one_day.height == 1380
    assert_frame_equal(one_day, whole.filter(pl.col("trade_date") == MARCH_9))


def test_a_first_session_the_data_starts_inside_decides_no_front(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The copy's bars of 2026-03-05 start at 12:00 UTC, 13 hours after that session's open, so
    # its volumes are partial: the roll calendar starts from 03-06's bars, and its rows, which
    # run from the second session of the bars, from 03-09.
    store = Store(data_folder_with(monkeypatch, tmp_path, "ohlcv-1m"))
    for file in store.list_partitions():
        rows = store.scan_partition(file.partition).collect()
        store.write_partition(file.partition, rows.filter(pl.col("ts_open") >= utc(2026, 3, 5, 12)))

    bars = load("ES", "1m", "2026-03-05", "2026-03-09").collect()

    assert bars.get_column("trade_date").unique().to_list() == [MARCH_9]


@pytest.mark.usefixtures("fixtures_as_data")
@pytest.mark.parametrize(
    ("arguments", "refusal"),
    [
        (("ZZ", "1m", "2026-03-06", "2026-03-06"), "or a contract such as MESH2024, got 'ZZ'"),
        (("ES", "1w", "2026-03-06", "2026-03-06"), "Expected a timeframe such as 1s, 5m"),
        (("ES", "1m", "2026-03-9", "2026-03-09"), "Expected the start as a date such as"),
        (("ES", "1m", "2026-03-09", "2026-03-06"), "Expected the start 2026-03-09 on or before"),
        (("ES", "1m", datetime(2026, 3, 6, tzinfo=UTC), "2026-03-06"), "got the instant"),
        (("ESZ2026", "1m", "2026-03-06", "2026-03-06"), "Expected bars of ESZ2026 from"),
    ],
)
def test_arguments_that_name_no_load_are_refused(
    arguments: tuple[str, str, str | date, str | date], refusal: str
) -> None:
    with pytest.raises(ValueError, match=refusal):
        load(*arguments)


def two_providers_of_es(monkeypatch: pytest.MonkeyPatch, folder: Path) -> None:
    """The fixtures' 1-minute bars from `synthetic`, and those of ESH2026 alone from `vendor`."""
    data_folder_with(monkeypatch, folder, "ohlcv-1m")
    shutil.copytree(
        SYNTHETIC / "ohlcv-1m",
        folder / "vendor" / "ohlcv-1m",
        ignore=shutil.ignore_patterns("contract=ESM2026"),
    )


def test_a_root_under_two_providers_is_refused_unless_a_provider_is_named(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    two_providers_of_es(monkeypatch, tmp_path)

    with pytest.raises(
        ValueError,
        match="Expected one provider of ES in the store, got synthetic and vendor; name one "
        "with provider=",
    ):
        load("ES", "1m", "2026-03-06", "2026-03-06")


@pytest.mark.parametrize(
    ("provider", "contracts"), [("vendor", ["ESH2026"]), ("synthetic", ["ESH2026", "ESM2026"])]
)
def test_a_named_provider_loads_its_own_datasets(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, provider: str, contracts: list[str]
) -> None:
    two_providers_of_es(monkeypatch, tmp_path)

    bars = load("ES", "1m", "2026-03-06", "2026-03-06", continuous=False, provider=provider)

    assert bars.select("contract").unique().sort("contract").collect().to_series().to_list() == (
        contracts
    )


def test_a_provider_without_the_root_is_refused_with_the_providers_that_hold_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    two_providers_of_es(monkeypatch, tmp_path)

    with pytest.raises(
        ValueError,
        match=r"Expected a provider of ES in the store \(synthetic and vendor\), got 'databento'",
    ):
        load("ES", "1m", "2026-03-06", "2026-03-06", provider="databento")


@pytest.mark.usefixtures("fixtures_as_data")
def test_datasets_lists_each_dataset_with_its_trade_dates_fidelity_and_quality() -> None:
    listed = datasets()

    march_7 = date(2026, 3, 7)
    btc, es = ("synthetic", "BTCUSDT-PERP"), ("synthetic", "ES")
    imported = ("import", "Synthetic data of scripts/gen_fixtures.py; no licence applies", None, 1)
    assert listed.schema == DATASETS_COLUMNS
    assert listed.rows() == [
        (*btc, "ohlcv-1m", "1m", 1, march_7, march_7, "unchecked", None, *imported),
        (*btc, "ohlcv-1s", "1s", 1, march_7, march_7, "unchecked", None, *imported),
        (*btc, "trades", "trades", 1, march_7, march_7, "unchecked", None, *imported),
        (*es, "ohlcv-1m", "1m", 2, MARCH_5, MARCH_9, "unchecked", None, *imported),
        (*es, "ohlcv-1s", "1s", 2, MARCH_5, MARCH_9, "unchecked", None, *imported),
        (*es, "trades", "trades", 2, MARCH_5, MARCH_9, "unchecked", None, *imported),
    ]


@pytest.mark.usefixtures("fixtures_as_data")
def test_datasets_shows_the_version_of_the_product_catalog() -> None:
    assert datasets().get_column("catalog_version").unique().to_list() == [CATALOG.version]


def test_datasets_shows_the_status_of_a_written_quality_report(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store_folder = data_folder_with(monkeypatch, tmp_path / "store", "ohlcv-1m")
    report = assess_quality(Store(store_folder), "synthetic", "ES", tmp_path / "cache")
    write_quality_report(report, store_folder / "reports")

    listed = datasets().filter(pl.col("root") == "ES")

    assert listed.select("schema", "fidelity", "quality", "checked_through").rows() == [
        ("ohlcv-1m", "1m", "clean", MARCH_9)
    ]


def test_the_sdk_offers_the_data_api_as_ff_market() -> None:
    assert fefat.market.load is load
    assert fefat.market.datasets is datasets


@pytest.mark.parametrize(
    "read",
    [
        pytest.param(
            lambda: load("ES", "5m", "2026-03-06", "2026-03-09", fidelity="trades"), id="trades"
        ),
        pytest.param(lambda: load("ES", "5m", "2026-03-06", "2026-03-09"), id="finest"),
        pytest.param(
            lambda: fefat.features.compute({}, "ES", "5m", "2026-03-06", "2026-03-09"),
            id="compute",
        ),
    ],
)
def test_bars_of_sessions_no_one_minute_bars_decide_the_front_of_are_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, read: Any
) -> None:
    # The copy's trades run to 2026-03-09 and its 1-minute bars stop with 03-06, so no front of
    # 03-09 is decided: splicing would leave that session out. The code review of the Phase 3
    # exit: a load without a fidelity, and compute, which choose each date's level for its front,
    # left it out without a word.
    store = Store(data_folder_with(monkeypatch, tmp_path, "trades", "ohlcv-1m"))
    for file in store.list_partitions():
        if str(file.partition.dataset.schema_name) == "ohlcv-1m":
            rows = store.scan_partition(file.partition).collect()
            store.write_partition(file.partition, rows.filter(pl.col("trade_date") <= MARCH_6))

    with pytest.raises(ValueError, match="through 2026-03-09, got fronts through 2026-03-06"):
        read()


def test_a_root_load_without_bars_in_its_window_is_refused(fixtures_as_data: None) -> None:
    # A window past the data, or on the dataset's first session, which never has a front, gave
    # an empty frame; a notebook then computed over nothing without an error.
    with pytest.raises(ValueError, match="Expected bars of ES from 2026-03-16 to 2026-03-18"):
        load("ES", "1m", "2026-03-16", "2026-03-18", fidelity="1m")
    # Step 3.2: without a fidelity, no level holds a date of the window, so no dataset is read.
    with pytest.raises(ValueError, match="Expected bars of ES from 2026-03-16 to 2026-03-18"):
        load("ES", "1m", "2026-03-16", "2026-03-18")


def test_a_load_builds_each_trade_date_from_the_finest_level_that_holds_it() -> None:
    # D-71: ESH2026's 1-minute bars cover 2026-03-02 to 03-13 and its trades start on 03-10, so
    # the bars build the dates before 03-10 and the trades the dates from it, where a load once
    # built every date from the finest data held and gave no bars before the trades began.
    synthetic = resolve_paths(os.environ).data_dir / "synthetic"
    dates = ["--dates", "2026-03-02..2026-03-13", "--contracts", "ESH2026"]
    assert gen_fixtures.main(["--out", str(synthetic), *dates, "--ticks-from", "2026-03-10"]) == 0

    bars = load("ES", "5m", "2026-03-03", "2026-03-13").collect()

    minutes = load("ES", "5m", "2026-03-03", "2026-03-13", fidelity="1m").collect()
    trades = load("ES", "5m", "2026-03-10", "2026-03-13", fidelity="trades").collect()
    before = pl.col("trade_date") < date(2026, 3, 10)
    assert bars.get_column("trade_date").unique().len() == 9
    assert_frame_equal(bars.filter(before), minutes.filter(before))
    assert_frame_equal(bars.filter(~before), trades)


def test_a_date_no_level_holds_has_the_same_rows_in_a_window_ending_on_it_and_one_past_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The leakage audit of step 3.2: with ESH2026's 1-minute bars of 2026-03-06 removed, a window
    # ending on 03-06 once stopped its grid at the bars' last date and a window running past it
    # gave 03-06 zero-volume rows; both give them, as the fidelity named gives them.
    store = Store(data_folder_with(monkeypatch, tmp_path, "ohlcv-1m"))
    for file in store.list_partitions():
        rows = store.scan_partition(file.partition).collect()
        store.write_partition(file.partition, rows.filter(pl.col("trade_date") != MARCH_6))

    ending = load("ESH2026", "5m", "2026-03-05", "2026-03-06").collect()
    running_past = load("ESH2026", "5m", "2026-03-05", "2026-03-09").collect()

    named = load("ESH2026", "5m", "2026-03-05", "2026-03-06", fidelity="1m").collect()
    assert ending.filter(pl.col("trade_date") == MARCH_6).height == BUCKETS_OF_FIVE_MINUTES
    assert ending.equals(running_past.filter(pl.col("trade_date") <= MARCH_6))
    assert ending.equals(named)


def test_a_spliced_load_builds_each_trade_date_from_the_finest_level_its_front_holds(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The step review: ESH2026 is the front on 2026-03-06, so ESM2026's trades of that day build
    # none of the series' bars. With ESH2026's trades of 03-06 gone, the date takes its front's
    # 1-minute bars, where it once took the trades and gave the front a session of empty buckets.
    data_folder_with(monkeypatch, tmp_path, "trades", "ohlcv-1m")
    front = tmp_path / "synthetic" / "trades" / "root=ES" / "contract=ESH2026"
    shutil.rmtree(front / "date=2026-03-06")

    bars = load("ES", "5m", "2026-03-06", "2026-03-06").collect()

    minutes = load("ES", "5m", "2026-03-06", "2026-03-06", fidelity="1m").collect()
    assert bars.get_column("contract").unique().to_list() == ["ESH2026"]
    assert bars.get_column("volume").equals(minutes.get_column("volume"))
    assert bars.get_column("zero_volume").sum() < BUCKETS_OF_FIVE_MINUTES


@pytest.mark.usefixtures("fixtures_as_data")
def test_the_kept_roll_calendar_gives_a_copy_of_its_rows() -> None:
    # The step review: the calendar is kept for every later load in the process, so a notebook
    # that changes the rows it was given in place changes no load after it.
    rows = roll_calendar("ES").rows
    rows[0, "adj_offset"] = 999

    assert roll_calendar("ES").rows.item(0, "adj_offset") == 0


def test_a_stretch_no_dataset_holds_has_the_rows_any_window_holding_it_gives(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The leakage audit of step 3.3: bitcoin's 1-minute bars end with 2026-03-07 and its trades
    # start on 03-10. A window ending on 03-08 held the stretch between them back, while one that
    # reached the trades gave it empty buckets, so a date's rows depended on the window's end.
    store = Store(data_folder_with(monkeypatch, tmp_path, "ohlcv-1m", "trades"))
    trades = Dataset(
        provider="synthetic", schema_name=parse_schema_name("trades"), root="BTCUSDT-PERP"
    )
    saturday = Partition(dataset=trades, contract="BTCUSDT-PERP", key=date(2026, 3, 7))
    later = 3 * 24 * 3_600_000_000_000
    rows = store.scan_partition(saturday).collect()
    tuesday = Partition(dataset=trades, contract="BTCUSDT-PERP", key=date(2026, 3, 10))
    store.write_partition(
        tuesday, rows.with_columns(pl.col("ts_recv") + later, pl.col("ts_event") + later)
    )
    shutil.rmtree((store.folder / saturday.relative_path()).parent)

    ending = load("BTCUSDT-PERP", "5m", "2026-03-07", "2026-03-08").collect()
    past = load("BTCUSDT-PERP", "5m", "2026-03-07", "2026-03-10").collect()

    assert ending.equals(past.filter(pl.col("trade_date") <= date(2026, 3, 8)))
    sunday = ending.filter(pl.col("trade_date") == date(2026, 3, 8))
    assert sunday.height == 288
    assert sunday.get_column("zero_volume").all()


def test_a_kept_roll_calendar_is_built_again_for_another_instrument_or_session_table(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The ponytail review: the kept calendar's stamp names the instrument, whose last trade rule
    # forces rolls, and the session table, beside the bars it reads.
    data_folder_with(monkeypatch, tmp_path, "ohlcv-1m")
    built: list[RollCalendar] = []

    def counted_rolls(*arguments: Any) -> RollCalendar:
        built.append(volume_rolls(*arguments))
        return built[-1]

    monkeypatch.setattr("fefat.market.roll_calendars.volume_rolls", counted_rolls)
    roll_calendar("ES")
    roll_calendar("ES")
    another_es = instruments.get("ES").model_copy(update={"sources": ("another source",)})
    with monkeypatch.context() as patched:
        patched.setattr(InstrumentTable, "get", lambda *_, **__: another_es)
        roll_calendar("ES")
    with monkeypatch.context() as patched:
        patched.setattr(SessionTable, "key", "another session table")
        roll_calendar("ES")

    assert len(built) == 3
