"""`ff.backtest.run` (step 2.10) on the fixtures' store: a run evaluates its signals, runs the
engine over the engine cache, writes every artifact with its schema and `run.json` under
`FEFAT_HOME/workspaces/default/artifacts/runs/<run key>/` (Done means 1), and a second
identical call returns the run already written without running the engine again (Done means 2);
from step 2.11, its record holds its metrics (Done means 3 of 2.11)."""

import json
import os
import shutil
import warnings
from datetime import date
from decimal import Decimal
from typing import Any

import fefat_engine
import polars as pl
import pytest

import fefat as ff
import fefat.backtest.run_inputs as run_inputs
from fefat.backtest import ARTIFACT_SCHEMAS, Run, RunConfig, RunRecord
from fefat.backtest.artifacts import read_artifact, write_run
from fefat.backtest.metrics import Metrics
from fefat.config import resolve_paths
from fefat.market.fidelity import TickFidelity
from fefat.market.layout import DatasetOrigin
from fefat.reference.settings import SlippageTicks
from fefat.strategy.signal_frame import require_column_types
from notebook_runs import breakout, store_with


@pytest.fixture(name="fixture_store")
def fixture_fixture_store() -> None:
    """The fixtures' ES and BTC trades, 1-second, and 1-minute bars, and BTC's funding, in
    `FEFAT_DATA_DIR`."""
    store_with("trades", "ohlcv-1s", "ohlcv-1m", "funding")


@pytest.mark.usefixtures("fixture_store")
def test_a_run_on_the_synthetic_month_writes_every_artifact_with_its_schema() -> None:
    # Done means 1.
    run = ff.backtest.run(breakout(), "2026-03-05", "2026-03-09")

    folder = resolve_paths(os.environ).runs_dir / run.hash
    assert run.folder == folder
    written = sorted(path.name for path in folder.iterdir())
    assert written == sorted([f"{name}.parquet" for name in ARTIFACT_SCHEMAS] + ["run.json"])
    for name, schema in ARTIFACT_SCHEMAS.items():
        frame = pl.read_parquet(folder / f"{name}.parquet")
        require_column_types(frame, schema, f"the {name} artifact's")
    record = RunRecord.model_validate_json((folder / "run.json").read_bytes())
    assert record == run.record
    assert record.run_key == run.hash == folder.name
    assert not run.trades.is_empty()
    assert run.fills.height == record.summary.fills


@pytest.mark.usefixtures("fixture_store")
def test_a_second_identical_run_is_the_first_read_back(monkeypatch: pytest.MonkeyPatch) -> None:
    # Done means 2: identical runs are recognised by their key, and the engine does not run.
    first = ff.backtest.run(breakout(), "2026-03-05", "2026-03-09")

    def refused(*_: object) -> object:
        raise AssertionError("Expected the run already written, got the engine run again")

    monkeypatch.setattr(fefat_engine, "run_signal_backtest", refused)
    # The engine's warning of the fee table's first schedule can come from the record alone.
    with pytest.warns(UserWarning, match="F-FEE-01"):
        again = ff.backtest.run(breakout(), "2026-03-05", "2026-03-09")

    assert again.hash == first.hash
    assert again.folder == first.folder
    assert again.trades.equals(first.trades)


@pytest.mark.usefixtures("fixture_store")
def test_another_setting_or_strategy_is_another_run() -> None:
    first = ff.backtest.run(breakout(), "2026-03-05", "2026-03-09")
    slower = ff.backtest.run(breakout(), "2026-03-05", "2026-03-09", RunConfig(latency_ms=500))
    wider = ff.backtest.run(breakout(16), "2026-03-05", "2026-03-09")

    assert len({first.hash, slower.hash, wider.hash}) == 3


@pytest.mark.usefixtures("fixture_store")
def test_the_record_names_every_dataset_its_terms_each_default_and_each_warning() -> None:
    # D-47, D-51, and BACKLOG's fee table and its warning in run.json.
    with pytest.warns(UserWarning, match="F-FEE-01"):
        run = ff.backtest.run(breakout(), "2026-03-05", "2026-03-09")

    record = run.record
    assert {dataset.schema_name for dataset in record.datasets} == {
        "ohlcv-1m",
        "ohlcv-1s",
        "trades",
    }
    assert all(dataset.origin is DatasetOrigin.IMPORT for dataset in record.datasets)
    assert all("Synthetic data" in dataset.licence_scope for dataset in record.datasets)
    config = record.config
    assert (config.fidelity, config.fee_table, config.provider) == (
        TickFidelity.TRADES,
        "retail-default",
        "synthetic",
    )
    assert (config.latency_ms, config.capital) == (100, Decimal(50_000))
    assert config.slippage_ticks == SlippageTicks(market=1, stop=1)
    assert record.fee_table.schedules[0][0] == date(2026, 7, 20)
    assert [warning for warning in record.warnings if "F-FEE-01" in warning]
    assert record.engine_config["fidelity"] == "trades"
    assert record.fidelity_summary == {"trades": record.summary.fills}
    assert (
        run.fills.get_column("trade_date").is_between(record.window.start, record.window.end).all()
    )


@pytest.mark.usefixtures("fixture_store")
def test_equity_is_at_each_signal_bar_or_each_trade_date() -> None:
    run = ff.backtest.run(breakout(), "2026-03-05", "2026-03-09")

    signals = run.signals
    assert run.equity("5m").height == signals.height
    daily = run.equity("1d")
    assert (
        daily.get_column("trade_date").to_list()
        == signals.get_column("trade_date").unique(maintain_order=True).to_list()
    )
    last_equity: int = daily.item(daily.height - 1, "equity")
    assert daily.get_column("pnl").sum() == last_equity - 50_000_000_000
    with pytest.raises(
        ValueError, match="Expected the timeframe 1d or the strategy's, 5m, got '1h'"
    ):
        run.equity("1h")


def long_btc() -> ff.SignalStrategy:
    """A long of 0.1 BTC from 01:00 to 23:00 UTC, without a stop."""
    utc = pl.from_epoch("ts_close", time_unit="ns")
    at = lambda hour: (utc.dt.hour() == hour) & (utc.dt.minute() == 0)  # noqa: E731
    return ff.SignalStrategy(
        instrument="BTCUSDT-PERP",
        timeframe="5m",
        long_entry=at(1),
        short_entry=pl.lit(False),
        long_exit=at(23),
        execution=ff.Execution(entry=ff.Market(), sizing=ff.Fixed(0.1)),
    )


@pytest.mark.usefixtures("fixture_store")
def test_a_perpetual_pays_the_funding_rates_the_store_holds() -> None:
    # BACKLOG's perpetual's funding from the store (F-FND-01): a long of 0.1 BTC held from 01:00
    # to 23:00 UTC pays at the fixtures' funding times of 08:00 and 16:00, which its trade counts.
    with pytest.warns(UserWarning, match="binance-default"):
        run = ff.backtest.run(long_btc(), "2026-03-07", "2026-03-07")

    funding = run.costs.filter(pl.col("reason") == "funding")
    assert funding.height == 2
    [trade] = run.trades.iter_rows(named=True)
    assert trade["funding"] == -funding.get_column("amount").sum() != 0
    assert trade["pnl"] == trade["gross_pnl"] - trade["fees"] + trade["funding"]
    assert "funding" in {dataset.schema_name for dataset in run.record.datasets}
    assert run.record.config.fee_table == "binance-default"
    # Without a stop the trade has no initial risk, so no R.
    assert (trade["initial_risk"], trade["r_multiple"], trade["mae_r"]) == (None, None, None)


@pytest.mark.usefixtures("fixture_store")
def test_a_perpetual_without_funding_rates_in_its_window_is_refused() -> None:
    # Step 2.10's review (F-FND-01): a funding dataset that holds no rate for the window would
    # let the run pay none.
    funding = resolve_paths(os.environ).data_dir / "synthetic" / "funding" / "root=BTCUSDT-PERP"
    (funding / "contract=BTCUSDT-PERP" / "part.parquet").unlink()

    expected = "Expected the funding rates of the perpetual BTCUSDT-PERP received from 2026-03-07"
    with pytest.raises(ValueError, match=expected):
        ff.backtest.run(long_btc(), "2026-03-07", "2026-03-07")


@pytest.mark.usefixtures("fixture_store")
def test_a_rule_without_the_column_it_reads_is_refused_before_the_engine_runs() -> None:
    # BACKLOG's columns a spec names: the Rust template would read a missing trail_ref as null.
    strategy = breakout().model_copy(
        update={
            "execution": ff.Execution(
                entry=ff.Market(),
                stop=ff.Stop(ticks=12),
                trailing=ff.Trailing(column=True),
                sizing=ff.Fixed(1),
            )
        }
    )

    with pytest.raises(ValueError, match="Expected the signal frame's trail_ref for a trailing"):
        ff.backtest.run(strategy, "2026-03-05", "2026-03-09")


@pytest.mark.usefixtures("fixture_store")
def test_a_feature_an_exit_rule_reads_below_one_tick_warns() -> None:
    # BACKLOG's feature below one tick (F-RND-01): an ATR written in points, 1.0, is a billionth.
    strategy = breakout().model_copy(
        update={
            "features": {"highest": pl.col("close").rolling_max(12).shift(1), "atr": pl.lit(1.0)},
            "execution": ff.Execution(entry=ff.Market(), stop=ff.Stop(atr=1.5), sizing=ff.Fixed(1)),
        }
    )

    with pytest.warns(UserWarning, match="the feature atr, which stop_feature reads, lies below"):
        ff.backtest.run(strategy, "2026-03-05", "2026-03-09")


@pytest.mark.usefixtures("fixture_store")
def test_the_warnings_load_raises_are_in_the_record_and_raised_on_every_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The Phase 2 kickoff's amendment (BACKLOG): run.json keeps what `load` warned of.
    def warning_load(*arguments: Any, **keywords: Any) -> pl.LazyFrame:
        warnings.warn("a warning of load", UserWarning, stacklevel=2)
        return ff.market.load(*arguments, **keywords)

    monkeypatch.setattr(run_inputs, "load", warning_load)

    with pytest.warns(UserWarning, match="a warning of load"):
        run = ff.backtest.run(breakout(), "2026-03-05", "2026-03-09")

    assert "a warning of load" in run.record.warnings


@pytest.mark.usefixtures("fixture_store")
def test_a_trades_risk_r_and_values_at_entry_are_those_of_its_stop_and_its_entry_row() -> None:
    # Step 2.10's review: a stop of 12 ticks risks 12 times 12.50 USD on ES's lot, which the R
    # columns divide by, and the features at entry are the entry row's.
    run = ff.backtest.run(breakout(), "2026-03-05", "2026-03-09")

    trades = run.trades.join(
        run.signals.select(pl.col("ts_close").alias("entry_decision"), "highest"),
        on="entry_decision",
    )
    assert not trades.is_empty()
    assert (trades.get_column("initial_risk_ticks") == 12).all()
    assert (trades.get_column("initial_risk") == 12 * 12_500_000).all()
    r_multiple = trades.get_column("pnl") / trades.get_column("initial_risk")
    assert (trades.get_column("r_multiple") == r_multiple).all()
    assert (trades.get_column("mae_r") == trades.get_column("mae_ticks") / 12).all()
    assert (trades.get_column("highest_at_entry") == trades.get_column("highest")).all()


@pytest.mark.usefixtures("fixture_store")
def test_a_trade_entered_at_a_sessions_open_has_the_trade_date_of_its_entry_fill() -> None:
    # Step 2.10's review: an entry decided at a session's last close, 16:00 in Chicago, fills at
    # the next session's open (F-SES-01), so the trade's entry trade date is its fill's.
    chicago = pl.from_epoch("ts_close", time_unit="ns").dt.replace_time_zone("UTC")
    chicago = chicago.dt.convert_time_zone("America/Chicago")
    last_close = (chicago.dt.hour() == 16) & (chicago.dt.minute() == 0)
    strategy = breakout().model_copy(update={"long_entry": last_close})

    run = ff.backtest.run(strategy, "2026-03-05", "2026-03-09")

    filled = run.fills.select(
        pl.col("order").alias("entry_order"), pl.col("trade_date").alias("filled_on")
    )
    decided = run.signals.select(
        pl.col("ts_close").alias("entry_decision"), pl.col("trade_date").alias("decided_on")
    )
    trades = run.trades.join(filled, on="entry_order").join(decided, on="entry_decision")
    assert (trades.get_column("decided_on") < trades.get_column("filled_on")).any()
    assert (trades.get_column("entry_trade_date") == trades.get_column("filled_on")).all()


@pytest.mark.usefixtures("fixture_store")
def test_a_saved_run_opens_without_its_engine_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    # Step 2.10's review: the cache may be deleted at any time, and a saved run reads none of it.
    first = ff.backtest.run(breakout(), "2026-03-05", "2026-03-09")
    engine_cache = resolve_paths(os.environ).cache_dir / "engine"
    shutil.rmtree(engine_cache)

    def refused(*_: object) -> object:
        raise AssertionError("Expected the saved run, got its cache built again")

    monkeypatch.setattr(run_inputs, "build_cache_months", refused)
    again = ff.backtest.run(breakout(), "2026-03-05", "2026-03-09")

    assert again.hash == first.hash
    assert not engine_cache.exists()


@pytest.mark.usefixtures("fixture_store")
def test_saving_a_run_leaves_another_writers_folder_and_keeps_the_run_saved_first() -> None:
    # Step 2.10's review: two processes saving one run each write into a folder of their own, so
    # that neither deletes the other's files, and the second keeps the run the first saved.
    run = ff.backtest.run(breakout(), "2026-03-05", "2026-03-09")
    artifacts = {name: read_artifact(run.folder, name) for name in ARTIFACT_SCHEMAS}
    folder = run.folder.with_name("copy")
    other = folder.with_name("copy.partial")
    other.mkdir()
    (other / "fills.parquet").write_bytes(b"another writer's")

    write_run(folder, artifacts, run.record)
    write_run(folder, artifacts, run.record)

    assert (other / "fills.parquet").read_bytes() == b"another writer's"
    written = sorted(path.name for path in folder.iterdir())
    assert written == sorted([f"{name}.parquet" for name in ARTIFACT_SCHEMAS] + ["run.json"])
    partials = [path.name for path in folder.parent.iterdir() if path.suffix == ".partial"]
    assert partials == ["copy.partial"]


@pytest.mark.usefixtures("fixture_store")
def test_a_runs_metrics_are_stored_in_its_record_and_read_back() -> None:
    # Done means 3 of step 2.11: the metrics serialise to JSON, run.json holds them, and a saved
    # run reads them back; they count the run's own trades, days, and account.
    run = ff.backtest.run(breakout(), "2026-03-05", "2026-03-09")

    metrics = run.metrics
    stored = json.loads((run.folder / "run.json").read_bytes())
    assert Metrics.model_validate(stored["metrics"]) == metrics
    assert Metrics.model_validate_json(metrics.model_dump_json()) == metrics
    assert Run.open(run.folder).metrics == metrics
    assert metrics.trades.trades == run.trades.height > 0
    assert metrics.pnl == run.record.summary.pnl
    assert metrics.daily.days == run.equity("1d").height
    capital = pl.Series("equity", [50_000_000_000], dtype=pl.Int64)
    account = capital.append(run.equity("5m").get_column("equity").drop_nulls())
    deepest = ff.backtest.running_drawdown(account).max()
    assert isinstance(deepest, int)
    assert metrics.drawdown.max_drawdown == Decimal(deepest).scaleb(-6)
    assert metrics.robustness.inputs.num_parameters == 3
    assert metrics.robustness.inputs.slippage_tested


@pytest.mark.usefixtures("fixture_store")
def test_the_pnl_at_one_more_tick_is_that_of_the_run_at_one_more_tick() -> None:
    # 02 section 7 and F-SLP-01: the rerun adds one tick to market and stop orders' slippage.
    run = ff.backtest.run(breakout(), "2026-03-05", "2026-03-09")
    ticks = run.config.slippage_ticks
    more = SlippageTicks(market=ticks.market + 1, stop=ticks.stop + 1)

    slipped = ff.backtest.run(
        breakout(), "2026-03-05", "2026-03-09", RunConfig(slippage_ticks=more)
    )

    assert run.metrics.pnl_at_plus_one_tick == slipped.record.summary.pnl
    assert run.metrics.pnl_at_plus_one_tick < run.metrics.pnl
