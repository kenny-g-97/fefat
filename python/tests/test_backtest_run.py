"""`ff.backtest.run` (step 2.10) on the fixtures' store: a run evaluates its signals, runs the
engine over the engine cache, writes every artifact with its schema and `run.json` under
`FEFAT_HOME/workspaces/default/artifacts/runs/<run key>/` (Done means 1), and a second
identical call returns the run already written without running the engine again (Done means 2)."""

import os
from datetime import date
from decimal import Decimal

import fefat_engine
import polars as pl
import pytest

import fefat as ff
from fefat.backtest import ARTIFACT_SCHEMAS, RunConfig, RunRecord
from fefat.config import resolve_paths
from fefat.market.fidelity import TickFidelity
from fefat.market.layout import DatasetOrigin
from fefat.reference.settings import SlippageTicks
from fefat.strategy.signal_frame import require_column_types
from notebook_runs import store_with


def breakout(stop_ticks: int = 12) -> ff.SignalStrategy:
    """A long on a close above the highest of the 12 closes before it, with a stop of
    `stop_ticks` and a target twice as far."""
    return ff.SignalStrategy(
        instrument="ES",
        timeframe="5m",
        features={"highest": pl.col("close").rolling_max(12).shift(1)},
        long_entry=pl.col("close") > pl.col("highest"),
        short_entry=pl.lit(False),
        execution=ff.Execution(
            entry=ff.Market(),
            stop=ff.Stop(ticks=stop_ticks),
            targets=[ff.Target(ticks=2 * stop_ticks)],
            sizing=ff.Fixed(1),
        ),
    )


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


@pytest.mark.usefixtures("fixture_store")
def test_a_perpetual_pays_the_funding_rates_the_store_holds() -> None:
    # BACKLOG's perpetual's funding from the store (F-FND-01): a long of 0.1 BTC held from 01:00
    # to 23:00 UTC pays at the fixtures' funding times of 08:00 and 16:00, which its trade counts.
    utc = pl.from_epoch("ts_close", time_unit="ns")
    at = lambda hour: (utc.dt.hour() == hour) & (utc.dt.minute() == 0)  # noqa: E731
    strategy = ff.SignalStrategy(
        instrument="BTCUSDT-PERP",
        timeframe="5m",
        long_entry=at(1),
        short_entry=pl.lit(False),
        long_exit=at(23),
        execution=ff.Execution(entry=ff.Market(), sizing=ff.Fixed(0.1)),
    )

    with pytest.warns(UserWarning, match="binance-default"):
        run = ff.backtest.run(strategy, "2026-03-07", "2026-03-07")

    funding = run.costs.filter(pl.col("reason") == "funding")
    assert funding.height == 2
    [trade] = run.trades.iter_rows(named=True)
    assert trade["funding"] == -funding.get_column("amount").sum() != 0
    assert trade["pnl"] == trade["gross_pnl"] - trade["fees"] + trade["funding"]
    assert "funding" in {dataset.schema_name for dataset in run.record.datasets}
    assert run.record.config.fee_table == "binance-default"


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
