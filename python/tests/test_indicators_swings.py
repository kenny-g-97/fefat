"""The swing detector of step 3.6, by hand (Done means 1 and the step's test): a swing high or low
is flagged on the n-th bar after it, with its price, never sooner, and a frame cut at any bar
flags what the whole frame flags up to it, so no later bar takes a swing back (no repainting)."""

from datetime import date

import polars as pl

import fefat as ff
from session_bars import bar, frame

HIGHS = [1, 2, 5, 3, 2, 4, 6, 4, 3, 2]
LOWS = [0, 1, 4, 2, 1, 3, 5, 3, 2, 1]
"""Highs with swings at the third and seventh bars, and lows with one at the fifth, for n = 2."""


def swing_bars(rows: int) -> pl.DataFrame:
    """The first `rows` five-minute bars of a session of `HIGHS` and `LOWS`."""
    clocks = [f"08:{5 * index:02d}" for index in range(len(HIGHS))]
    bars = (
        bar(date(2026, 3, 6), clock, high, low, low, 1, low)
        for clock, high, low in zip(clocks, HIGHS, LOWS, strict=True)
    )
    return frame(*bars).head(rows)


def test_a_swing_is_flagged_on_the_nth_bar_after_it_with_its_price() -> None:
    # Past the warm-up of 2n bars: the high of 5 on the third bar shows on the fifth, the high
    # of 6 on the seventh shows on the ninth, and the low of 1 on the fifth shows on the seventh.
    computed = ff.indicators.swings(n=2).evaluate(swing_bars(10)).collect().slice(4)

    assert computed.get_column("swing_high").to_list() == [True, False, False, False, True, False]
    assert computed.get_column("swing_low").to_list() == [False, False, True, False, False, False]
    assert computed.get_column("swing_high_price").to_list() == [5, None, None, None, 6, None]
    assert computed.get_column("swing_low_price").to_list() == [None, None, 1, None, None, None]


def test_a_swing_is_confirmed_only_after_n_bars_and_never_taken_back() -> None:
    # The step's test: the swing of the third bar shows on no bar until the second after it has
    # closed, and a frame cut after any bar flags what the whole frame flags up to that bar.
    swings = ff.indicators.swings(n=2)
    whole = swings.evaluate(swing_bars(10)).collect()

    before = swings.evaluate(swing_bars(4)).collect()
    for rows in range(1, len(HIGHS)):
        cut = swings.evaluate(swing_bars(rows)).collect()
        for output in ("swing_high", "swing_low"):
            assert cut.get_column(output).equals(whole.get_column(output).head(rows))

    assert not before.get_column("swing_high").fill_null(False).any()
    assert whole.get_column("swing_high").head(5).fill_null(False).to_list()[-1]
