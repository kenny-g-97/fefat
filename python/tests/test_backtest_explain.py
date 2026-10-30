"""`Run.explain(trade_id)` (step 2.11, Done means 2) on the fixtures: a trade replayed through the
reference engine on the run's own records prints each event with its rule and each fill with its
rule and slippage, and the reference's fills are the Rust engine's. On trade prints, a losing
trade shows its stop's trigger and its fill; on 1-minute bars every trade of the breakout agrees,
the one held across the fixtures' roll of 2026-03-09 among them, on the store's own bars when its
prints disagree; an id that is no trade's, fills
the engines do not share, a trade of prints across the roll, and data changed since the run are
refused."""

import json
import os
import shutil
from datetime import date

import polars as pl
import pytest

import fefat as ff
from fefat.backtest import Run, RunConfig
from fefat.backtest.explain import EnginesDisagreementError
from fefat.config import resolve_paths
from fefat.market.schema import Timeframe
from fefat.strategy.spec import OppositeSignal
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


def test_a_run_on_bars_is_explained_on_its_stored_bars_not_bars_built_from_prints() -> None:
    # The engine fills a 1-minute run on the store's 1-minute bars; `load` without a fidelity
    # would build them from the trade prints, which here lie four ticks above them on 03-06.
    trades = resolve_paths(os.environ).data_dir / "synthetic" / "trades" / "root=ES"
    part = trades / "contract=ESH2026" / "date=2026-03-06" / "part.parquet"
    prints = pl.read_parquet(part)
    prints.with_columns(price=pl.col("price") + 4 * 250_000_000).write_parquet(part)
    run = backtest(RunConfig(fidelity=Timeframe.parse("1m")))
    on_the_day = run.trades.filter(pl.col("entry_trade_date") == date(2026, 3, 6))
    assert not on_the_day.is_empty()

    explained = [run.explain(order) for order in on_the_day.get_column("entry_order")]

    assert all(each.reference_fills == each.rust_fills for each in explained)


def test_a_perpetuals_trade_is_replayed_with_the_funding_it_paid() -> None:
    # The funding rates come back from the run's record through the reference's own model.
    store_with("funding")
    utc = pl.from_epoch("ts_close", time_unit="ns")
    at = lambda hour: (utc.dt.hour() == hour) & (utc.dt.minute() == 0)  # noqa: E731
    long_btc = ff.SignalStrategy(
        instrument="BTCUSDT-PERP",
        timeframe="5m",
        long_entry=at(1),
        short_entry=pl.lit(False),
        long_exit=at(23),
        execution=ff.Execution(entry=ff.Market(), sizing=ff.Fixed(0.1)),
    )
    with pytest.warns(UserWarning, match="binance-default"):
        run = ff.backtest.run(long_btc, "2026-03-07", "2026-03-07")

    explanation = run.explain(run.trades.item(0, "entry_order"))

    assert explanation.reference_fills == explanation.rust_fills
    paid = [line for line in explanation.lines if " funding " in line]
    assert len(paid) == 2
    assert all(line.endswith("[F-FND-01]") for line in paid)
    # The step review: a rate of zero, or below a millionth, reads back too, outside the episode.
    copy = run.folder.with_name("small-rates")
    shutil.copytree(run.folder, copy)
    record = json.loads((copy / "run.json").read_bytes())
    funding = record["engine_config"]["funding"]
    record["engine_config"]["funding"] = [{"ts": 1, "rate": 0}, {"ts": 2, "rate": 500}, *funding]
    (copy / "run.json").write_text(json.dumps(record), encoding="utf-8")
    again = Run.open(copy).explain(run.trades.item(0, "entry_order"))
    assert again.reference_fills == explanation.reference_fills


def test_a_trade_reversed_by_an_opposite_signal_ends_at_its_own_exit() -> None:
    # F-ENT-04 under reverse: the decision that closes the trade also enters the other way, and
    # both market orders fill at the next record, the next trade's entry at the exit's instant.
    highest, lowest = (
        pl.col("close").rolling_max(12).shift(1),
        pl.col("close").rolling_min(12).shift(1),
    )
    reversing = ff.SignalStrategy(
        instrument="ES",
        timeframe="5m",
        features={"highest": highest, "lowest": lowest},
        long_entry=pl.col("close") > pl.col("highest"),
        short_entry=pl.col("close") < pl.col("lowest"),
        execution=ff.Execution(
            entry=ff.Market(), on_opposite_signal=OppositeSignal.REVERSE, sizing=ff.Fixed(1)
        ),
    )
    with pytest.warns(UserWarning, match="F-FEE-01"):
        run = ff.backtest.run(reversing, START, END, RunConfig(fidelity=Timeframe.parse("1m")))
    first = run.trades.row(0, named=True)
    assert first["exit_reason"] == "opposite_signal"

    explanation = run.explain(first["entry_order"])

    assert [fill.role for fill in explanation.rust_fills] == ["entry", "opposite_signal"]
    assert explanation.reference_fills == explanation.rust_fills
    reversed_into = run.trades.row(1, named=True)
    with pytest.raises(ValueError, match="entered by reversing a position of 1 lots"):
        run.explain(reversed_into["entry_order"])


def test_a_short_entered_by_the_second_order_of_a_pair_is_numbered_from_the_first() -> None:
    # Step 2.11's engine review: a pair of stop entries takes two ids, the buy's first (F-ENT-01),
    # so the replay of a short its sell opened numbers its orders from the buy's id.
    straddle = ff.SignalStrategy(
        instrument="ES",
        timeframe="5m",
        long_entry=pl.lit(True),
        short_entry=pl.lit(True),
        execution=ff.Execution(
            entry=ff.StopEntry(offset_ticks=2, time_to_live_bars=1),
            stop=ff.Stop(ticks=8),
            targets=[ff.Target(ticks=8)],
            sizing=ff.Fixed(1),
        ),
    )
    with pytest.warns(UserWarning, match="F-FEE-01"):
        run = ff.backtest.run(straddle, START, END, RunConfig(fidelity=Timeframe.parse("1m")))
    shorts = run.trades.filter(pl.col("side") == "short").get_column("entry_order")
    assert not shorts.is_empty()

    explained = [run.explain(order) for order in shorts.head(5)]

    assert all(each.reference_fills == each.rust_fills for each in explained)
    assert all(each.rust_fills[0].order == each.trade_id for each in explained)


def test_a_trade_entered_at_the_instant_the_one_before_closed_is_numbered_from_its_entry() -> None:
    # Step 2.11's second engine review: on 1-minute signals filling on 1-minute bars, a trade
    # opened and closed in one bar places its stop and target at the bar's close (F-BAR-06,
    # F-OCO-02), the instant the next decision enters again; only entries number the replay.
    scalper = ff.SignalStrategy(
        instrument="ES",
        timeframe="1m",
        long_entry=pl.lit(True),
        short_entry=pl.lit(False),
        execution=ff.Execution(
            entry=ff.Market(),
            stop=ff.Stop(ticks=1),
            targets=[ff.Target(ticks=8)],
            sizing=ff.Fixed(1),
        ),
    )
    with pytest.warns(UserWarning, match="F-FEE-01"):
        run = ff.backtest.run(scalper, START, END, RunConfig(fidelity=Timeframe.parse("1m")))
    trades = run.trades.with_columns(closed_before=pl.col("exit_ts").shift(1))
    reentered = trades.filter(pl.col("entry_decision") == pl.col("closed_before"))
    assert not reentered.is_empty()

    explained = [run.explain(order) for order in reentered.get_column("entry_order").head(3)]

    assert all(each.reference_fills == each.rust_fills for each in explained)
