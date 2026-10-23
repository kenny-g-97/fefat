"""The market-data notebook (step 1.11) runs top to bottom, as Run All does, on a store of
synthetic data, and skips with a message the cells whose data the store lacks."""

import os
import shutil
from datetime import date
from pathlib import Path

import polars as pl
import pytest

from export_samples import ESH2026_MINUTES, IMPORTED_ON, PRESETS, written_export
from fefat.config import resolve_paths
from fefat.market.bars import resample_bars
from fefat.market.bars_check import ComparisonStatus
from fefat.market.builtin_calendars import BUILT_IN
from fefat.market.calendar import sessions_of
from fefat.market.calendar_definition import CalendarId
from fefat.market.importers.file_import import FileImportRequest, import_file
from fefat.market.saved_instruments import instrument_table
from fefat.market.schema import Timeframe, TimeUnit
from fefat.market.store import Store
from fefat_app.cli import main
from notebook_runs import run_notebook, store_with

ROOT = Path(__file__).resolve().parents[2]
NOTEBOOK = ROOT / "notebooks" / "01-market-data.ipynb"
SYNTHETIC = ROOT / "fixtures" / "synthetic"
NINJATRADER_SAMPLE = SYNTHETIC / "exports" / "ninjatrader" / "ES 03-26.Last.txt"
NO_WHOLE_SESSION = "Skipped: your store holds no whole session of ES's trades from synthetic"


def store_minute_bars_before(day: date) -> None:
    """The fixtures' ES 1-minute bars of the trade dates before `day`, from the provider
    `synthetic`."""
    minutes = resolve_paths(os.environ).data_dir / "synthetic" / "ohlcv-1m" / "root=ES"
    shutil.copytree(SYNTHETIC / "ohlcv-1m" / "root=ES", minutes)
    for part in minutes.rglob("part.parquet"):
        pl.read_parquet(part).filter(pl.col("trade_date") < day).write_parquet(part)


def store_trades_without(*trade_dates: str) -> None:
    """The fixtures' trades from the provider `synthetic`, without those of `trade_dates`."""
    shutil.copytree(
        SYNTHETIC / "trades",
        resolve_paths(os.environ).data_dir / "synthetic" / "trades",
        ignore=shutil.ignore_patterns(*(f"date={day}" for day in trade_dates)),
    )


def import_hourly_bars(folder: Path) -> None:
    """The fixtures' ESH2026 bars resampled to hours, written as TradingView writes an hourly
    chart, and imported through a copy of its preset: bars coarser than 5 minutes."""
    paths = resolve_paths(os.environ)
    hour = Timeframe(count=1, unit=TimeUnit.HOUR)
    sessions = sessions_of(BUILT_IN[CalendarId.CME_EQUITY_INDEX], paths.cache_dir)
    hours = resample_bars(pl.read_parquet(ESH2026_MINUTES), hour, sessions, 2**62)
    rows = [
        f"{bar['ts_open'] // 1_000_000_000},{bar['open'] / 1e9},{bar['high'] / 1e9},"
        f"{bar['low'] / 1e9},{bar['close'] / 1e9},{bar['volume']}"
        for bar in hours.iter_rows(named=True)
    ]
    path = written_export(
        folder, "CME_MINI_ESH2026, 60.csv", ["time,open,high,low,close,Volume", *rows]
    )
    profile = PRESETS["tradingview"].model_copy(
        update={"name": "tradingview-hourly", "timeframe": hour}
    )
    store = Store(paths.data_dir)
    request = FileImportRequest(path=path, profile=profile)
    instruments = instrument_table(store.folder)
    import_file(request, store, paths.cache_dir, imported_on=IMPORTED_ON, instruments=instruments)


def test_the_notebook_runs_on_your_bars_and_on_an_import_through_a_preset(
    capsys: pytest.CaptureFixture[str],
) -> None:
    store_with("ohlcv-1m")
    main(["data", "import", "file", str(NINJATRADER_SAMPLE), "--profile", "ninjatrader"])
    capsys.readouterr()

    namespace = run_notebook(NOTEBOOK)

    printed = capsys.readouterr().out
    # Without MES, the notebook takes the 1-minute bars with the most contracts: the fixtures'
    # ES, whose year holds the roll to ESM2026, from an offset of 0 on ESH2026.
    assert (namespace["ROOT"], namespace["PROVIDER"]) == ("ES", "synthetic")
    rolls = namespace["rolls"]
    assert rolls.select("trade_date", "rolled_from", "contract").rows() == [
        (date(2026, 3, 9), "ESH2026", "ESM2026")
    ]
    assert rolls.item(0, "step") == rolls.item(0, "adj_offset")
    report = namespace["report"]
    assert report.comparisons_run() > 0
    assert report.difference_count() == 0
    assert "Differences: none." in printed
    assert NO_WHOLE_SESSION in printed
    imported = namespace["IMPORTED"]
    assert (imported["provider"], imported["root"]) == ("ninjatrader", "ES")
    assert namespace["quality"].summary() in printed


def test_the_notebook_rebuilds_bars_from_trades_and_skips_the_import_it_lacks(
    capsys: pytest.CaptureFixture[str],
) -> None:
    store_with("ohlcv-1m", "trades")

    namespace = run_notebook(NOTEBOOK)

    printed = capsys.readouterr().out
    assert namespace["ticks"].status is ComparisonStatus.COMPARED
    assert namespace["report"].difference_count() == 0
    assert NO_WHOLE_SESSION not in printed
    assert namespace["IMPORTED"] is None
    assert "Skipped: no dataset imported through a preset" in printed


def test_the_notebook_rebuilds_bars_from_trades_that_end_before_the_minute_bars(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Trades of 2026-03-05 and 03-06 only, while the 1-minute bars run to 03-09: the rebuild
    # takes 03-06, the last whole session of the trades, not 03-09, the last of the bars.
    store_with("ohlcv-1m")
    store_trades_without("2026-03-09")

    namespace = run_notebook(NOTEBOOK)

    assert namespace["ticks"].status is ComparisonStatus.COMPARED
    assert NO_WHOLE_SESSION not in capsys.readouterr().out
    assert namespace["DAY"] == date(2026, 3, 9)
    assert namespace["TICK_DAY"] == date(2026, 3, 6)


def test_the_notebook_rebuilds_bars_from_trades_that_run_past_the_minute_bars(
    tmp_path: Path,
) -> None:
    # 1-minute bars of 2026-03-05 and 03-06 only, and trades to 03-09 with a print 400 ms after
    # its close, as the fixtures have after 03-06's, so that 03-09 is a whole session of the
    # trades: the rebuild takes 03-06, the last both cover, where there are bars to compare.
    store_minute_bars_before(date(2026, 3, 9))
    store_trades_without()
    sessions = sessions_of(BUILT_IN[CalendarId.CME_EQUITY_INDEX], tmp_path / "cache")
    in_the_break = sessions.session(date(2026, 3, 9)).close + 400_000_000
    part = (
        resolve_paths(os.environ).data_dir
        / "synthetic/trades/root=ES/contract=ESM2026/date=2026-03-09/part.parquet"
    )
    trades = pl.read_parquet(part)
    print_after_the_close = trades.tail(1).with_columns(
        ts_recv=pl.lit(in_the_break, dtype=pl.Int64),
        ts_event=pl.lit(in_the_break, dtype=pl.Int64),
        sequence=pl.col("sequence") + 1,
    )
    pl.concat([trades, print_after_the_close]).write_parquet(part)

    namespace = run_notebook(NOTEBOOK)

    assert namespace["ticks"].status is ComparisonStatus.COMPARED
    assert namespace["DAY"] == namespace["TICK_DAY"] == date(2026, 3, 6)


def test_the_notebook_never_rebuilds_the_first_session_of_a_trades_file(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # A file's first session can start after its open, as a download from midnight UTC does,
    # so trades of 2026-03-06 alone hold no session the rebuild can take as whole.
    store_with("ohlcv-1m")
    store_trades_without("2026-03-05", "2026-03-09")

    namespace = run_notebook(NOTEBOOK)

    assert namespace["TICK_DAY"] is None
    assert NO_WHOLE_SESSION in capsys.readouterr().out


def test_the_notebook_skips_trades_that_share_no_session_with_the_minute_bars(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # 1-minute bars of 2026-03-05 and 03-06, and trades of 03-09 alone.
    store_minute_bars_before(date(2026, 3, 9))
    store_trades_without("2026-03-05", "2026-03-06")

    namespace = run_notebook(NOTEBOOK)

    assert namespace["TICK_DAY"] is None
    assert NO_WHOLE_SESSION in capsys.readouterr().out


def test_the_notebook_loads_an_import_coarser_than_five_minutes_at_its_own_timeframe(
    tmp_path: Path, recwarn: pytest.WarningsRecorder
) -> None:
    store_with("ohlcv-1m")
    import_hourly_bars(tmp_path)

    namespace = run_notebook(NOTEBOOK)

    assert any("holds 1-hour bars" in str(warning.message) for warning in recwarn)
    imported = namespace["IMPORTED"]
    assert (imported["provider"], imported["schema"]) == ("tradingview", "ohlcv-1h")
    assert namespace["timeframe"] == "1h"
    assert namespace["week"].get_column("contract").unique().to_list() == ["ESH2026"]
    assert namespace["quality"].provider == "tradingview"


def test_the_notebook_says_what_to_do_on_a_store_without_minute_bars() -> None:
    with pytest.raises(ValueError, match=r"Expected 1-minute bars .* import your files first"):
        run_notebook(NOTEBOOK)
