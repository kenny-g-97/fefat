"""The session's levels and clock of step 3.6, by hand (Done means 1): the opening range from the
session's open or a local time, given once its window has closed; the session before, the trade
date before in the session table; the high and low so far; the bars and grid minutes since the
open; and the bars since a flagged bar, within the sessions they remember. A bar without trades
holds the close before it, which none of these reads as a level."""

from datetime import date

import polars as pl

import fefat as ff
from session_bars import bar, flagged_sessions, frame, traded, values_of

FRIDAY, MONDAY = date(2026, 3, 6), date(2026, 3, 9)
LEVELS = ["range_high", "range_low", "range_width"]
NONE = (None, None, None)


def opening() -> pl.DataFrame:
    """Friday's bars from 08:25: the bar of 08:30 traded nothing and holds the close before it,
    30, which no trade in a window from 08:30 made."""
    return frame(
        traded(FRIDAY, "08:25", 30),
        bar(FRIDAY, "08:30", 30, 30, 30, 0),
        bar(FRIDAY, "08:35", 14, 9, 12, 2, vwap=12),
        bar(FRIDAY, "08:40", 20, 5, 15, 1, vwap=15),
        bar(FRIDAY, "08:45", 16, 13, 14, 1, vwap=14),
    )


def test_the_opening_range_is_its_windows_traded_range_given_once_the_window_closes() -> None:
    # Ten minutes from 08:30 hold the bars of 08:30 and 08:35, of which only the second traded;
    # the range is final when the second closes, at 08:40, and null on the bars closing before.
    bars = opening()

    from_anchor = ff.indicators.opening_range(minutes=10, anchor="08:30").evaluate(bars)
    from_open = ff.indicators.opening_range(minutes=10).evaluate(bars)

    assert from_anchor.collect().select(LEVELS).rows() == [NONE] * 2 + [(14, 9, 5)] * 3
    assert from_open.collect().select(LEVELS).rows() == [NONE] + [(30, 30, 0)] * 4


def test_the_session_before_is_the_trade_date_before_in_the_session_table() -> None:
    # Presidents' Day, 2026-02-16, has no trade date, so the session before 02-17 is 02-13's,
    # whatever the bars each holds: its traded bars' high and low and its last bar's close. Its
    # first bucket traded nothing and holds the close before it, 20, above the traded range.
    friday, tuesday = date(2026, 2, 13), date(2026, 2, 17)
    bars = frame(
        bar(friday, "07:55", 20, 20, 20, 0),
        bar(friday, "08:00", 12, 9, 10, 1, vwap=10),
        bar(friday, "08:05", 15, 11, 14, 2, vwap=14),
        bar(friday, "08:10", 14, 14, 14, 0),
        bar(tuesday, "08:00", 14, 14, 14, 0),
        bar(tuesday, "08:05", 20, 16, 18, 1, vwap=18),
    )

    computed = ff.indicators.previous_session().evaluate(bars).collect()

    levels = computed.select("previous_high", "previous_low", "previous_close").rows()
    assert levels == [NONE] * 4 + [(15, 9, 14)] * 2
    assert computed.get_column("warmup").to_list() == [True] * 4 + [False] * 2


def test_the_session_high_and_low_so_far_read_the_bars_that_traded() -> None:
    bars = frame(
        bar(FRIDAY, "08:00", 10, 10, 10, 0),
        bar(FRIDAY, "08:05", 12, 9, 11, 1, vwap=11),
        bar(FRIDAY, "08:10", 11, 8, 10, 1, vwap=10),
        bar(FRIDAY, "08:15", 10, 10, 10, 0),
        bar(MONDAY, "08:00", 20, 19, 19, 1, vwap=19),
    )
    spec = ff.indicators.session_high_low()

    assert values_of(spec, bars, "session_high") == [None, 12, 12, 12, 20]
    assert values_of(spec, bars, "session_low") == [None, 9, 8, 8, 19]


def test_the_time_since_the_open_counts_the_grids_bars_and_minutes_without_its_halts() -> None:
    # The bucket of 08:10 lies in a halt, which the grid leaves out: the bar of 08:15 is the
    # third of the session and closes 15 minutes of grid time after its open.
    bars = frame(
        traded(FRIDAY, "08:00", 10),
        traded(FRIDAY, "08:05", 11),
        traded(FRIDAY, "08:15", 12),
        traded(MONDAY, "08:00", 13),
    )
    spec = ff.indicators.time_since_open()

    assert values_of(spec, bars, "bars_since_open") == [1, 2, 3, 1]
    assert values_of(spec, bars, "minutes_since_open") == [5.0, 10.0, 15.0, 5.0]


def test_the_bars_since_a_flagged_bar_remember_the_sessions_they_are_given() -> None:
    bars = flagged_sessions()
    one, two = ff.indicators.bars_since("event"), ff.indicators.bars_since("event", sessions=2)

    assert values_of(one, bars, "bars_since") == [None, 0, 1, None, None, 0]
    assert values_of(two, bars, "bars_since") == [None, 0, 1, 2, 3, 0]
    assert (one.warmup_sessions, two.warmup_sessions) == (0, 1)
