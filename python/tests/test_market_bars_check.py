import shutil
from datetime import date
from pathlib import Path

import polars as pl
import pytest

from fefat.market.bars_check import (
    BarDifference,
    BarsReport,
    ComparedBars,
    ComparisonStatus,
    UncomparedBars,
    verify_bars,
)
from fefat.market.layout import Dataset, Partition, YearMonth
from fefat.market.schema import parse_schema_name
from fefat.market.store import Store

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "fixtures"
MARCH_6 = date(2026, 3, 6)
TRADES, SECONDS, MINUTES, FIVE_MINUTES, DAYS = (
    parse_schema_name(name) for name in ("trades", "ohlcv-1s", "ohlcv-1m", "ohlcv-5m", "ohlcv-1d")
)
ES_MINUTES = Partition(
    dataset=Dataset(provider="synthetic", schema_name=MINUTES, root="ES"),
    contract="ESH2026",
    key=YearMonth(year=2026, month=3),
)


def stored_bars(store: Store, partition: Partition, day: date) -> pl.DataFrame:
    return store.scan_partition(partition).filter(pl.col("trade_date") == day).collect()


def seconds_of_march_6() -> int:
    partition = Partition(
        dataset=Dataset(provider="synthetic", schema_name=SECONDS, root="ES"),
        contract="ESH2026",
        key=MARCH_6,
    )
    return Store(FIXTURES).scan_partition(partition).collect().height


def test_the_fixtures_bars_rebuilt_from_their_trades_show_no_differences(tmp_path: Path) -> None:
    # The fixtures hold ES trades and their 1-second and 1-minute bars; no 5-minute or daily
    # bars are stored, so those comparisons have nothing to compare with. The trades of
    # Friday 2026-03-06 resampled to 5-minute and then daily bars equal their daily bar.
    report = verify_bars(Store(FIXTURES), "ES", MARCH_6, tmp_path)

    minutes = stored_bars(Store(FIXTURES), ES_MINUTES, MARCH_6).height
    assert report == BarsReport(
        root="ES",
        trade_date=MARCH_6,
        comparisons=(
            ComparedBars(
                provider="synthetic",
                route=(TRADES, SECONDS),
                reference=(SECONDS,),
                bars_compared=seconds_of_march_6(),
                differences=(),
            ),
            ComparedBars(
                provider="synthetic",
                route=(TRADES, MINUTES),
                reference=(MINUTES,),
                bars_compared=minutes,
                differences=(),
            ),
            ComparedBars(
                provider="synthetic",
                route=(SECONDS, MINUTES),
                reference=(MINUTES,),
                bars_compared=minutes,
                differences=(),
            ),
            UncomparedBars(
                status=ComparisonStatus.NOT_AVAILABLE,
                provider="synthetic",
                route=(MINUTES, FIVE_MINUTES),
                reference=(FIVE_MINUTES,),
            ),
            UncomparedBars(
                status=ComparisonStatus.NOT_AVAILABLE,
                provider="synthetic",
                route=(MINUTES, DAYS),
                reference=(DAYS,),
            ),
            ComparedBars(
                provider="synthetic",
                route=(TRADES, FIVE_MINUTES, DAYS),
                reference=(TRADES, DAYS),
                bars_compared=1,
                differences=(),
            ),
        ),
    )
    assert minutes == 23 * 60 + 1
    assert report.summary().splitlines() == [
        "Bars of ES on 2026-03-06. Comparisons run: 4. Differences: none.",
        f"synthetic: trades -> ohlcv-1s against ohlcv-1s: {seconds_of_march_6():,} compared, "
        "no differences",
        "synthetic: trades -> ohlcv-1m against ohlcv-1m: 1,381 compared, no differences",
        "synthetic: ohlcv-1s -> ohlcv-1m against ohlcv-1m: 1,381 compared, no differences",
        "synthetic: ohlcv-1m -> ohlcv-5m against ohlcv-5m: no ohlcv-5m stored to compare with",
        "synthetic: ohlcv-1m -> ohlcv-1d against ohlcv-1d: no ohlcv-1d stored to compare with",
        "synthetic: trades -> ohlcv-5m -> ohlcv-1d against trades -> ohlcv-1d: 1 compared, "
        "no differences",
    ]


def test_a_stored_bar_that_differs_or_is_missing_is_listed_with_both_sides(tmp_path: Path) -> None:
    # In a copy of the fixtures, the 1-minute bar opening at 2026-03-06 14:30 UTC closes one
    # tick higher than its trades say, and the one opening a minute later is gone.
    shutil.copytree(FIXTURES / "synthetic", tmp_path / "store" / "synthetic")
    store = Store(tmp_path / "store")
    month = store.scan_partition(ES_MINUTES).collect()
    changed, removed = 1_772_807_400_000_000_000, 1_772_807_460_000_000_000
    original = month.filter(pl.col("ts_open") == changed).item(0, "close")
    store.write_partition(
        ES_MINUTES,
        month.filter(pl.col("ts_open") != removed).with_columns(
            close=pl.when(pl.col("ts_open") == changed)
            .then(pl.col("close") + 250_000_000)
            .otherwise(pl.col("close"))
        ),
    )

    report = verify_bars(store, "ES", MARCH_6, tmp_path / "cache")

    differences = (
        BarDifference(
            instrument_id=1001,
            ts_open=changed,
            column="close",
            rebuilt=format_price(original),
            reference=format_price(original + 250_000_000),
        ),
        BarDifference(
            instrument_id=1001,
            ts_open=removed,
            column="bar",
            rebuilt="present",
            reference="missing",
        ),
    )
    by_route = {
        comparison.route: comparison
        for comparison in report.comparisons
        if isinstance(comparison, ComparedBars)
    }
    assert by_route[(TRADES, MINUTES)].differences == differences
    assert by_route[(SECONDS, MINUTES)].differences == differences
    assert by_route[(TRADES, SECONDS)].differences == ()
    assert report.summary().splitlines()[0] == (
        "Bars of ES on 2026-03-06. Comparisons run: 4. Differences: 4."
    )
    assert (
        "  instrument_id 1001, bar opening 2026-03-06T14:30:00Z: close rebuilt "
        f"{format_price(original)}, reference {format_price(original + 250_000_000)}"
    ) in report.summary().splitlines()


def format_price(units: int) -> str:
    """A price in 1e-9 units as the report writes it, such as 6848.25 for 6_848_250_000_000."""
    whole, fraction = divmod(units, 1_000_000_000)
    return f"{whole}.{fraction:09d}".rstrip("0").rstrip(".")


def test_vendor_bars_without_their_trades_leave_the_rebuilding_pending(tmp_path: Path) -> None:
    # A store with the 1-minute bars alone, as the vendor files on this PC hold: rebuilding
    # them waits for trades or 1-second bars, and the resampling check still runs on them.
    shutil.copytree(
        FIXTURES / "synthetic" / "ohlcv-1m", tmp_path / "store" / "synthetic" / "ohlcv-1m"
    )

    report = verify_bars(Store(tmp_path / "store"), "ES", MARCH_6, tmp_path / "cache")

    assert report.summary().splitlines() == [
        "Bars of ES on 2026-03-06. Comparisons run: 1. Differences: none.",
        "synthetic: trades -> ohlcv-1s against ohlcv-1s: no ohlcv-1s stored to compare with",
        "synthetic: trades -> ohlcv-1m against ohlcv-1m: pending, without trades to rebuild from",
        "synthetic: ohlcv-1s -> ohlcv-1m against ohlcv-1m: pending, without ohlcv-1s to rebuild "
        "from",
        "synthetic: ohlcv-1m -> ohlcv-5m against ohlcv-5m: no ohlcv-5m stored to compare with",
        "synthetic: ohlcv-1m -> ohlcv-1d against ohlcv-1d: no ohlcv-1d stored to compare with",
        "synthetic: ohlcv-1m -> ohlcv-5m -> ohlcv-1d against ohlcv-1m -> ohlcv-1d: 1 compared, "
        "no differences",
    ]


def test_a_root_without_data_or_a_day_without_a_session_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Expected trades or bars of MES in the store, got none"):
        verify_bars(Store(FIXTURES), "MES", MARCH_6, tmp_path)
    with pytest.raises(ValueError, match="got 2026-03-07, a Saturday"):
        verify_bars(Store(FIXTURES), "ES", date(2026, 3, 7), tmp_path)
