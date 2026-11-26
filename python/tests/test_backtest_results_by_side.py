"""A saved run's results for all its trades, its long trades, and its short trades (step 5.22,
D-119, D-122): the long and the short trades' counts, net P&L, commissions, and slippage add up to
all trades' (Done means 3); every figure of all trades that the run's metrics hold is theirs
(Done means 1, the SDK's half); a run of long trades alone has no short side; a side's drawdown is
the engine's running drawdown of its closed trades, and its Sharpe ratio counts every trade date
the run was valued on; one tick of slippage on market orders is paid at each market fill's lots;
a fill that reverses a position is shared by the lots each trade takes of it; a perpetual's
funding stands beside its fees; and a run without trades has no side and no average."""

from datetime import date
from decimal import Decimal

import polars as pl
import pytest

import fefat as ff
from fefat.backtest import RunConfig
from fefat.backtest.record import Window
from fefat.backtest.sides import SideAccount, charged_trades
from fefat.market.engine_units import InstrumentParameters, micro_units, money_text
from fefat.reference.orders import PositionSide
from fefat.reference.settings import SlippageTicks
from metrics_by_definition import sharpe_ratios
from notebook_runs import breakout, breakout_both_ways, store_with

WINDOW = ("2026-03-05", "2026-03-09")
ES = InstrumentParameters(tick=250_000_000, money_per_point=50_000_000, lot_step=Decimal(1))
"""ES's tick of 0.25 at 50 a point: a tick is worth 12.50 on a lot."""
SUMMED = ("trades", "wins", "losses", "net_pnl", "gross_profit", "gross_loss", "fees", "slippage")
"""The figures of the sides that add up to all trades'."""
PLANTED_FILLS = {"order": pl.UInt64, "fidelity": pl.String}
"""The fills a side's metrics read: the fidelity each entry filled on."""


def test_the_long_and_the_short_trades_add_up_to_all_trades() -> None:
    # Done means 3: the counts, the net P&L, the commissions, and the slippage, and with them the
    # wins, the losses, and the gross profit and loss, which split the net P&L.
    store_with("ohlcv-1m")
    run = ff.backtest.run(breakout_both_ways(), *WINDOW)

    sides = ff.backtest.results_by_side(run)

    every, long, short = sides.all_trades, sides.long, sides.short
    assert long is not None
    assert short is not None
    assert long.trades > 0
    assert short.trades > 0
    for figure in SUMMED:
        assert getattr(long, figure) + getattr(short, figure) == getattr(every, figure), figure
    assert every.slippage > 0
    assert every.fees > 0


def test_all_trades_hold_the_runs_metrics_to_the_digit() -> None:
    # Done means 1, the SDK's half: each figure the metrics hold is theirs, the drawdown, its
    # spell, and the Sharpe ratio marking open trades; the gross profit and loss are the winners'
    # and the losers' net P&L, which the profit factor divides.
    store_with("ohlcv-1m")
    run = ff.backtest.run(breakout_both_ways(), *WINDOW)

    every = ff.backtest.results_by_side(run).all_trades

    metrics, statistics = run.metrics, run.metrics.trades
    held = (every.trades, every.wins, every.losses, every.win_rate, every.profit_factor)
    assert held == (
        statistics.trades,
        statistics.wins,
        statistics.losses,
        statistics.win_rate,
        statistics.profit_factor,
    )
    means = (every.expectancy, every.expectancy_r, every.average_win, every.average_loss)
    assert means == (
        statistics.expectancy,
        statistics.expectancy_r,
        statistics.average_win,
        statistics.average_loss,
    )
    assert every.net_pnl == metrics.pnl
    assert (every.max_drawdown, every.longest_drawdown_days, every.sharpe) == (
        metrics.drawdown.max_drawdown,
        metrics.drawdown.longest_drawdown_days,
        metrics.daily.sharpe,
    )
    assert every.gross_profit + every.gross_loss == every.net_pnl
    profit, loss = micro_units(every.gross_profit), micro_units(every.gross_loss)
    assert profit / -loss == statistics.profit_factor
    assert statistics.average_win is not None
    assert statistics.average_loss is not None
    assert every.win_loss_ratio == statistics.average_win / -statistics.average_loss
    assert every.trades_per_day == statistics.trades / metrics.daily.days
    assert every.funding is None


def test_a_run_of_long_trades_alone_has_no_short_side() -> None:
    store_with("ohlcv-1m")
    run = ff.backtest.run(breakout(stop_ticks=8), *WINDOW)

    sides = ff.backtest.results_by_side(run)

    assert sides.short is None
    assert sides.long is not None
    alike = (*SUMMED, "trades_per_day", "average_minutes_held", "average_mae_ticks")
    for figure in (*alike, "average_mfe_ticks", "win_rate", "profit_factor", "expectancy_r"):
        assert getattr(sides.long, figure) == getattr(sides.all_trades, figure), figure


def test_a_sides_drawdown_is_the_running_drawdown_of_its_closed_trades() -> None:
    # Its trades walked from the capital in the order they closed, as the step asks.
    store_with("ohlcv-1m")
    run = ff.backtest.run(breakout_both_ways(), *WINDOW)

    sides = ff.backtest.results_by_side(run)

    capital = micro_units(run.config.capital)
    deepest = []
    for side, figures in ((PositionSide.LONG, sides.long), (PositionSide.SHORT, sides.short)):
        assert figures is not None
        pnl = run.trades.filter(pl.col("side") == str(side)).get_column("pnl")
        walk = pl.concat([pl.Series([capital], dtype=pl.Int64), pnl.cum_sum() + capital])
        fall = ff.backtest.running_drawdown(walk).max()
        assert isinstance(fall, int)
        assert figures.max_drawdown == Decimal(money_text(fall))
        deepest.append(fall)
    assert max(deepest) > 0


def test_a_sides_sharpe_ratio_counts_every_trade_date_of_the_run() -> None:
    # The step's If it fails: a day without a trade of the side counts nothing, as the metrics
    # count a flat day, so that the ratio over the run's four days is not the one over the two
    # its trades closed on.
    account = planted_account(days=(2, 3, 4, 5))
    trades = planted_trades(pnl=[100_000_000, -40_000_000], exit_days=[2, 4])

    metrics = account.metrics_of(trades)

    assert metrics.daily.days == 4
    every_day = [("2026-03-02", 100_000_000), ("2026-03-03", 0), ("2026-03-04", -40_000_000)]
    over_the_run = sharpe_ratios([*every_day, ("2026-03-05", 0)], 1)["sharpe"]
    its_own = sharpe_ratios([every_day[0], every_day[2]], 1)["sharpe"]
    assert metrics.daily.sharpe == pytest.approx(over_the_run, rel=1e-12)
    assert metrics.daily.sharpe != pytest.approx(its_own)
    assert metrics.drawdown.max_drawdown == Decimal("40")
    figures = account.figures(trades, metrics)
    assert figures.trades_per_day == 2 / 4


def test_a_sides_spell_under_a_peak_starts_on_the_day_it_fell() -> None:
    # The engine review: the walk holds the equity at the start of each trade date, so that its
    # peak is the last trade date it stood there before the fall. A side at its peak from
    # Tuesday through the weekend, falling on Monday and back on Tuesday,
    # spent one day under its peak, not seven (its trades alone) nor four (the day's point after
    # its trades), and its trough is Monday's.
    account = planted_account(days=(2, 3, 4, 5, 6, 9, 10))
    trades = planted_trades(pnl=[100_000_000, -40_000_000, 40_000_000], exit_days=[3, 9, 10])

    metrics = account.metrics_of(trades)

    drawdown = metrics.drawdown
    assert (drawdown.max_drawdown, drawdown.peak, drawdown.trough) == (
        Decimal("40"),
        date(2026, 3, 9),
        date(2026, 3, 9),
    )
    assert drawdown.longest_drawdown_days == 1
    assert metrics.daily.days == 7


def test_a_trade_closing_on_a_day_the_run_was_not_valued_on_is_refused() -> None:
    account = planted_account(days=(2, 3))
    trades = planted_trades(pnl=[100_000_000], exit_days=[4])

    with pytest.raises(ValueError, match="valued on, got 2026-03-04"):
        account.walk(trades)


def test_one_tick_of_slippage_on_market_orders_is_paid_at_each_market_fills_lots() -> None:
    # The step's test: each market fill a trade's path names pays its tick at its lots, two of
    # them, so that a charge without the lots falls short (the step review), beside what the
    # stops a gap passed recorded against their price (F-STP-04), and the path names its trade's
    # fills, whose fees are the trade's.
    store_with("ohlcv-1m")
    config = RunConfig(slippage_ticks=SlippageTicks(market=1, stop=0))
    run = ff.backtest.run(breakout_both_ways(lots=2), *WINDOW, config)

    sides = ff.backtest.results_by_side(run)

    points = run.trade_paths.filter(pl.col("kind") == "fill").select("trade", "order", "ts")
    paired = points.join(run.fills, on=["order", "ts"])
    fees = paired.group_by("trade").agg(pl.col("fee").sum()).sort("trade").get_column("fee")
    assert fees.to_list() == run.trades.get_column("fees").to_list()
    market = run.orders.filter(pl.col("kind") == "market").get_column("id").to_list()
    at_market = paired.filter(pl.col("order").is_in(market))
    assert run.trades.height > 0
    assert set(at_market.get_column("lots").to_list()) == {2}
    assert set(at_market.get_column("slippage_ticks").to_list()) == {1}
    others = paired.filter(~pl.col("order").is_in(market))
    gapped = others.filter(pl.col("slippage_ticks") > 0)
    assert set(gapped.get_column("role").to_list()) <= {"stop"}
    ticks_paid = (
        at_market.get_column("lots").sum()
        + gapped.select((pl.col("slippage_ticks") * pl.col("lots")).sum()).item()
    )
    assert sides.all_trades.slippage == Decimal(money_text(ticks_paid * 12_500_000))


def test_a_fill_that_reverses_a_position_is_shared_by_the_lots_each_trade_takes() -> None:
    # S-fill-042: one fill closes the long's lot and opens the short's two, so that each trade
    # pays the fill's tick on its own lots; each exit dates its trade; and where a tick is worth a
    # tenth of a micro-unit on a lot, each fill's part is paid rounded up, against the trader
    # (F-FEE-03): the long's two parts a micro-unit each, the short's two lots one.
    trades, paths, fills = reversed_long(short_closed=True)

    charged = charged_trades(trades, paths, fills, ES)

    assert charged.get_column("slippage").to_list() == [25_000_000, 25_000_000]
    assert charged.get_column("exit_trade_date").to_list() == [date(2026, 3, 3), date(2026, 3, 4)]
    tenth = InstrumentParameters(tick=10_000_000, money_per_point=10, lot_step=Decimal("0.00001"))
    assert charged_trades(trades, paths, fills, tenth).get_column("slippage").to_list() == [2, 1]


def test_a_reversal_into_a_position_left_open_charges_the_closed_trade_its_own_lots() -> None:
    # The code and engine reviews: the short the fill opens is still open when the run ends, so
    # it is no trade, and the long pays the fill's tick on the one lot it held, not on three.
    trades, paths, fills = reversed_long(short_closed=False)

    charged = charged_trades(trades, paths, fills, ES)

    assert charged.get_column("slippage").to_list() == [25_000_000]


def test_a_perpetuals_funding_stands_beside_its_fees() -> None:
    store_with("ohlcv-1m", "funding")
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

    every = ff.backtest.results_by_side(run).all_trades

    funding = int(run.trades.get_column("funding").sum())
    assert funding != 0
    assert every.funding == Decimal(money_text(funding))


def test_a_run_without_trades_has_no_side_and_no_average() -> None:
    # Where nothing can be counted a figure is none, as the metrics leave it, and a sum over no
    # trade is zero.
    store_with("ohlcv-1m")
    never = ff.SignalStrategy(
        instrument="ES",
        timeframe="5m",
        long_entry=pl.lit(False),
        short_entry=pl.lit(False),
        execution=ff.Execution(entry=ff.Market(), sizing=ff.Fixed(1)),
    )
    run = ff.backtest.run(never, *WINDOW)

    sides = ff.backtest.results_by_side(run)

    assert (sides.long, sides.short) == (None, None)
    every = sides.all_trades
    sums = (every.trades, every.net_pnl, every.gross_profit, every.gross_loss, every.fees)
    assert sums == (0, 0, 0, 0, 0)
    assert (every.slippage, every.trades_per_day) == (0, 0)
    averages = (every.win_rate, every.profit_factor, every.expectancy, every.win_loss_ratio)
    held = (every.average_minutes_held, every.average_mae_ticks, every.average_mfe_ticks)
    assert (*averages, *held) == (None,) * 7


def planted_trades(pnl: list[int], exit_days: list[int]) -> pl.DataFrame:
    """Long trades of one lot entered by orders 1, 2, ... each `pnl` in micro-units, with a stop
    of 8 ticks and no costs, closing on the days of March 2026 in `exit_days`, a trade a day."""
    count = len(pnl)
    entries = [int(1_772_400_000_000_000_000 + 86_400_000_000_000 * day) for day in exit_days]
    return pl.DataFrame(
        {
            "side": ["long"] * count,
            "lots": [1] * count,
            "entry_order": list(range(1, count + 1)),
            "entry_ts": entries,
            "exit_ts": [entry + 600_000_000_000 for entry in entries],
            "exit_reason": ["stop" if amount < 0 else "target_1" for amount in pnl],
            "gross_pnl": pnl,
            "fees": [0] * count,
            "funding": [0] * count,
            "pnl": pnl,
            "initial_risk": [100_000_000] * count,
            "mae_ticks": [4] * count,
            "mfe_ticks": [6] * count,
            "entry_trade_date": [date(2026, 3, day) for day in exit_days],
            "slippage": [0] * count,
            "exit_trade_date": [date(2026, 3, day) for day in exit_days],
        },
        schema_overrides={"entry_order": pl.UInt64},
    )


def planted_account(days: tuple[int, ...]) -> SideAccount:
    """A side's account on ES from 50,000, valued on the days of March 2026 in `days`, with the
    fills its planted trades' entries read their fidelity from."""
    first, last = date(2026, 3, days[0]), date(2026, 3, days[-1])
    return SideAccount(
        capital=50_000_000_000,
        parameters=ES,
        window=Window(start=first, end=last),
        fills=pl.DataFrame({"order": [1, 2, 3], "fidelity": ["1m"] * 3}, schema=PLANTED_FILLS),
        days=pl.Series([date(2026, 3, day) for day in days], dtype=pl.Date),
        perpetual=False,
    )


def reversed_long(
    short_closed: bool,
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    """The trades, paths, and fills of a long of one lot that order 1 opens at 10 and order 2
    reverses at 20, selling three lots, each at a tick of slippage, into a short of two that
    order 3 closes at 30 without slippage where `short_closed`, and that stays open, no trade,
    where not."""
    trades = pl.DataFrame(
        {"side": ["long", "short"], "entry_order": [1, 2], "entry_ts": [10, 20], "lots": [1, 2]},
        schema={
            "side": pl.String,
            "entry_order": pl.UInt64,
            "entry_ts": pl.Int64,
            "lots": pl.Int64,
        },
    )
    paths = pl.DataFrame(
        {"trade": [0, 0, 1, 1], "order": [1, 2, 2, 3], "ts": [10, 20, 20, 30]},
        schema={"trade": pl.Int64, "order": pl.UInt64, "ts": pl.Int64},
    ).with_columns(kind=pl.lit("fill"))
    fills = pl.DataFrame(
        {
            "order": [1, 2, 3],
            "ts": [10, 20, 30],
            "side": ["buy", "sell", "buy"],
            "lots": [1, 3, 2],
            "slippage_ticks": [1, 1, 0],
            "trade_date": [date(2026, 3, 2), date(2026, 3, 3), date(2026, 3, 4)],
        },
        schema_overrides={"order": pl.UInt64},
    )
    if short_closed:
        return trades, paths, fills
    return trades.head(1), paths.head(2), fills.head(2)
