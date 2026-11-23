"""A run's trades as histograms (step 5.7, D-116): net P&L, R multiple, MAE and MFE in ticks, and
the minutes held, each in at most 40 bins of one width, their edges on multiples of it, so that no
bin straddles zero."""

from collections.abc import Sequence

import polars as pl
from hypothesis import given, settings
from hypothesis import strategies as st

from fefat.backtest.distributions import Histogram, trade_distributions

MINUTE = 60_000_000_000
USD = 1_000_000


def trades_of(
    pnl: list[int],
    risk: Sequence[int | None] | None = None,
    ticks: list[int] | None = None,
    held: list[int] | None = None,
) -> pl.DataFrame:
    """Trades with the columns the histograms read, in the artifact's units."""
    count = len(pnl)
    return pl.DataFrame(
        {
            "pnl": pnl,
            "initial_risk": [USD] * count if risk is None else risk,
            "mae_ticks": [0] * count if ticks is None else ticks,
            "mfe_ticks": [0] * count if ticks is None else ticks,
            "entry_ts": [0] * count,
            "exit_ts": [MINUTE] * count if held is None else held,
        },
        schema={
            "pnl": pl.Int64,
            "initial_risk": pl.Int64,
            "mae_ticks": pl.Int64,
            "mfe_ticks": pl.Int64,
            "entry_ts": pl.Int64,
            "exit_ts": pl.Int64,
        },
    )


def test_each_measure_is_counted_in_bins_on_multiples_of_one_width() -> None:
    trades = trades_of(
        pnl=[-150 * USD, -20 * USD, 30 * USD, 90 * USD],
        risk=[100 * USD] * 4,
        ticks=[0, 3, 7, 12],
        held=[5 * MINUTE, 15 * MINUTE, 25 * MINUTE, 95 * MINUTE],
    )

    shown = trade_distributions(trades)

    assert shown.pnl.lower[:2] == (-150.0, -140.0)
    assert shown.pnl.upper[0] == -140.0
    assert sum(shown.pnl.trades) == 4
    assert (shown.pnl.lower[0], shown.pnl.upper[-1]) == (-150.0, 100.0)
    assert shown.r_multiple.lower[:2] == (-1.5, -1.4)
    assert shown.mae_ticks.lower == tuple(float(tick) for tick in range(13))
    assert shown.mae_ticks.trades[0] == shown.mae_ticks.trades[12] == 1
    assert shown.holding_minutes.lower[0] == 5.0
    assert shown.holding_minutes.upper[-1] == 100.0
    assert shown.trades_without_r_multiple == 0


def test_a_trade_without_a_stop_is_left_out_of_the_r_multiples_and_counted() -> None:
    trades = trades_of(pnl=[USD, 2 * USD, 3 * USD], risk=[USD, None, 0])

    shown = trade_distributions(trades)

    assert sum(shown.r_multiple.trades) == 1
    assert shown.trades_without_r_multiple == 2
    assert sum(shown.pnl.trades) == 3


def test_no_trades_give_empty_histograms() -> None:
    shown = trade_distributions(trades_of(pnl=[]))

    empty = Histogram(lower=(), upper=(), trades=())
    assert (shown.pnl, shown.r_multiple, shown.mae_ticks, shown.mfe_ticks) == (empty,) * 4
    assert shown.holding_minutes == empty
    assert shown.trades_without_r_multiple == 0


def test_equal_trades_stand_in_one_bin_of_the_finest_width() -> None:
    shown = trade_distributions(trades_of(pnl=[125 * USD, 125 * USD]))

    assert shown.pnl == Histogram(lower=(125.0,), upper=(125.01,), trades=(2,))


def test_a_break_even_trade_stands_above_zero_and_the_smallest_loss_below_it() -> None:
    shown = trade_distributions(trades_of(pnl=[-1, 0, 1], risk=[10**9] * 3))

    assert shown.pnl == Histogram(lower=(-0.01, 0.0), upper=(0.0, 0.01), trades=(1, 2))
    assert shown.r_multiple == Histogram(lower=(-0.01, 0.0), upper=(0.0, 0.01), trades=(1, 2))


def test_a_decimal_edge_holds_the_value_it_names() -> None:
    # 29 hundredths of an R is below 0.29 as a float, and still stands in the bin from 0.29.
    shown = trade_distributions(trades_of(pnl=[29, 30], risk=[100, 100]))

    assert shown.r_multiple == Histogram(lower=(0.29, 0.3), upper=(0.3, 0.31), trades=(1, 1))


@settings(max_examples=200, deadline=None)
@given(pnl=st.lists(st.integers(-(10**13), 10**13), min_size=1, max_size=200))
def test_the_bins_count_every_trade_and_keep_the_sign_apart(pnl: list[int]) -> None:
    shown = trade_distributions(trades_of(pnl)).pnl

    assert sum(shown.trades) == len(pnl)
    assert len(shown.trades) <= 40
    assert shown.lower[1:] == shown.upper[:-1]
    assert shown.trades[0] > 0
    assert shown.trades[-1] > 0
    below_zero = sum(
        count for upper, count in zip(shown.upper, shown.trades, strict=True) if upper <= 0
    )
    assert below_zero == sum(1 for value in pnl if value < 0)
