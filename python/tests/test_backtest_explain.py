"""`Run.explain(trade_id)` (step 2.11, Done means 2) on the fixtures: a trade replayed through the
reference engine on the run's own records prints each event with its rule and each fill with its
rule and slippage, and the reference's fills are the Rust engine's. On trade prints, a losing
trade shows its stop's trigger and its fill; on 1-minute bars every trade of the breakout agrees,
the one held across the fixtures' roll of 2026-03-09 among them; an id that is no trade's, fills
the engines do not share, a trade of prints across the roll, and data changed since the run are
refused."""

import os
import shutil

import polars as pl
import pytest

import fefat as ff
from fefat.backtest import Run, RunConfig
from fefat.backtest.explain import EnginesDisagreementError
from fefat.config import resolve_paths
from fefat.market.schema import Timeframe
from notebook_runs import breakout, store_with

START, END = "2026-03-05", "2026-03-09"


@pytest.fixture(autouse=True)
def fixture_store() -> None:
    store_with("trades", "ohlcv-1s", "ohlcv-1m")


def backtest(config: RunConfig | None = None) -> Run:
    with pytest.warns(UserWarning, match="F-FEE-01"):
        return ff.backtest.run(breakout(), START, END, config)


def test_a_losing_trade_shows_its_stops_trigger_and_its_fill_with_rule_and_slippage(
    capsys: pytest.CaptureFixture[str],
) -> None:
    run = backtest()
    trade = run.trades.row(1, named=True)
    assert (trade["exit_reason"], trade["pnl"] < 0) == ("stop", True)

    explanation = run.explain(trade["entry_order"])

    printed = capsys.readouterr().out
    assert printed.strip() == explanation.text()
    assert explanation.reference_fills == explanation.rust_fills
    assert len(explanation.rust_fills) == 2
    stop = explanation.rust_fills[1]
    triggered = [line for line in explanation.lines if " triggered " in line]
    assert len(triggered) == 1
    assert f"order {stop.order}: the trade at" in triggered[0]
    assert triggered[0].endswith("[F-STP-01]")
    assert f"  order {stop.order} sell 1 at" in printed
    assert "(F-STP-03, taker, 1 ticks)" in printed
    assert explanation.lines[0].startswith(f"Trade {trade['entry_order']}: long 1 ESH2026 at ")
    assert ", out by stop on " in explanation.lines[0]


def test_every_trade_on_bars_agrees_the_one_across_the_roll_too() -> None:
    run = backtest(RunConfig(fidelity=Timeframe.parse("1m")))

    explained = [run.explain(order) for order in run.trades.get_column("entry_order")]

    assert all(each.reference_fills == each.rust_fills for each in explained)
    assert sum(len(each.rust_fills) for each in explained) == run.fills.height
    across = run.trades.filter(pl.col("rolls") == 1).item(0, "entry_order")
    lines = next(each.lines for each in explained if each.trade_id == across)
    assert any(" rolled " in line and "[F-ROL-01]" in line for line in lines)
    # The stop moved by the roll's gap (F-ROL-03); the new front's first bar opened below it.
    stopped = [line for line in lines if "the stop at" in line]
    assert stopped == [
        "    the bar from 2026-03-08T22:00:00Z to 2026-03-08T22:01:00Z, open 6917.5, high "
        "6917.75, low 6917.25, close 6917.75, opened past the stop at 6920"
    ]
    reached = [line for each in explained for line in each.lines if "reached the stop" in line]
    assert len(reached) == run.trades.height - 1


def test_an_id_that_is_no_trades_is_refused_with_the_ids_there_are() -> None:
    run = backtest()

    with pytest.raises(ValueError, match=r"its entry order, such as 1, 4, 7, .*got 2"):
        run.explain(2)


def test_fills_the_engines_do_not_share_are_refused() -> None:
    run = backtest()
    copy = run.folder.with_name("tampered")
    shutil.copytree(run.folder, copy)
    fills = pl.read_parquet(copy / "fills.parquet")
    moved = fills.with_columns(price=pl.col("price") + (pl.col("order") == 5) * 250_000_000)
    moved.write_parquet(copy / "fills.parquet")

    with pytest.raises(EnginesDisagreementError, match="fills of trade 4 to be the Rust engine's"):
        Run.open(copy).explain(4)


def test_a_trade_of_prints_across_the_roll_waits_for_its_replay() -> None:
    run = backtest()
    across = run.trades.filter(pl.col("rolls") == 1).item(0, "entry_order")

    with pytest.raises(ValueError, match="trade prints on one contract, got one decided on"):
        run.explain(across)


def test_data_changed_since_the_run_is_refused() -> None:
    run = backtest()
    trades = resolve_paths(os.environ).data_dir / "synthetic" / "trades" / "root=ES"
    part = trades / "contract=ESH2026" / "date=2026-03-05" / "part.parquet"
    part.write_bytes(part.read_bytes() + b"changed")

    with pytest.raises(ValueError, match="the data changed since the run"):
        run.explain(1)
