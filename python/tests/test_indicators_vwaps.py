"""The VWAPs of step 3.6, by hand (Done means 1): the session's, which resets at each session's open
and starts from a local time of day on its trade date across a clock change; the week's, which
resets on each week's first trade date; one since a flagged bar, within the sessions it remembers;
and the close's distance from the session's in ATRs and in ticks."""

import re
from datetime import date

import polars as pl
import pytest

import fefat as ff
from fefat.features.runtime import FeatureGraph
from fefat.market.schema import Timeframe
from session_bars import bar, flagged_sessions, frame, traded, values_of

POINT, TICK = 1_000_000_000, 250_000_000
FRIDAY, MONDAY = date(2026, 3, 6), date(2026, 3, 9)
FIVE = Timeframe.parse("5m")


def test_the_session_vwap_weighs_each_bars_vwap_or_typical_price_and_resets_each_session() -> None:
    # Friday: 10 alone, then (10 x 1 + 12 x 3) / 4, which a bar without trades leaves; Monday
    # starts again from a bar without a vwap, weighed at its typical price (21 + 18 + 21) / 3.
    bars = frame(
        bar(FRIDAY, "08:00", 11, 9, 10, 1, vwap=10),
        bar(FRIDAY, "08:05", 13, 11, 12, 3, vwap=12),
        bar(FRIDAY, "08:10", 12, 12, 12, 0),
        bar(MONDAY, "08:00", 21, 18, 21, 2),
        bar(MONDAY, "08:05", 23, 21, 22, 2, vwap=22),
    )

    vwaps = values_of(ff.indicators.session_vwap(), bars, "session_vwap")

    assert vwaps == [10, 11.5, 11.5, 20, 21]


def test_the_session_vwap_starts_from_a_local_time_on_its_trade_date_across_a_clock_change() -> (
    None
):
    # 08:30 Chicago is 14:30 UTC on Friday 2026-03-06 and 13:30 UTC on Monday 03-09, after the
    # clocks moved on Sunday: the VWAP starts from the bar opening at 08:30 on both days.
    bars = frame(
        traded(FRIDAY, "08:25", 100),
        traded(FRIDAY, "08:30", 300),
        traded(FRIDAY, "08:35", 400, volume=3),
        traded(MONDAY, "08:25", 500),
        traded(MONDAY, "08:30", 700),
    )

    vwaps = values_of(ff.indicators.session_vwap(anchor="08:30"), bars, "session_vwap")

    assert vwaps == [None, 300, 375, None, 700]


def test_the_weekly_vwap_resets_on_the_first_trade_date_of_each_week() -> None:
    # Presidents' Day, 2026-02-16, has no trade date of its own, so its week starts on Tuesday.
    days = [date(2026, 2, day) for day in (11, 12, 13, 17, 18)]
    bars = frame(
        *(
            traded(day, "08:00", price)
            for day, price in zip(days, [10, 20, 30, 40, 50], strict=True)
        )
    )

    vwaps = values_of(ff.indicators.weekly_vwap(), bars, "weekly_vwap")

    assert vwaps == [10, 15, 20, 40, 45]
    assert ff.indicators.weekly_vwap().warmup_sessions == 6


def test_a_vwap_since_a_flagged_bar_remembers_the_sessions_it_is_given() -> None:
    # One session forgets Friday's event on Monday until Monday's own; two read it on, as
    # (20 + 30 + 40) / 3 and (20 + 30 + 40 + 50) / 4, after a session of warm-up.
    bars = flagged_sessions()
    one, two = ff.indicators.vwap_since("event"), ff.indicators.vwap_since("event", sessions=2)

    assert values_of(one, bars, "vwap_since") == [None, 20, 25, None, None, 60]
    assert values_of(two, bars, "vwap_since") == [None, 20, 25, 30, 35, 60]
    assert (one.warmup_sessions, two.warmup_sessions) == (0, 1)


@pytest.mark.parametrize(
    ("flag", "got"), [("close", "a column of Int64"), ("roll", "no such column")]
)
def test_a_flag_that_is_no_boolean_column_of_the_bars_is_refused(flag: str, got: str) -> None:
    expected = (
        f"Expected flag to name a Boolean column of the bars, such as roll_flag, got {flag}: {got}."
    )

    with pytest.raises(ValueError, match=re.escape(expected)):
        ff.indicators.vwap_since(flag).evaluate(flagged_sessions())


def test_the_distance_from_the_vwap_counts_atrs_and_the_instruments_ticks() -> None:
    # Half a point above the VWAP is a quarter of an ATR of 2 points and 2 of ES's ticks of a
    # quarter point; a point below is -4 ticks, and no number of ATRs where the ATR is 0.
    read = pl.DataFrame(
        {
            "ts_close": [1, 2],
            "contract": ["ESH2026", "ESM2026"],
            "close": [5_000 * POINT + 2 * TICK, 4_999 * POINT],
            "session_vwap": [5_000.0 * POINT, 5_000.0 * POINT],
            "atr": [2.0 * POINT, 0.0],
        }
    )

    distance = ff.indicators.distance_from_vwap("ES").outputs_over(read).collect()

    assert distance.select("atrs", "ticks").rows() == [(0.25, 2.0), (None, -4.0)]
    expected = "Expected the bars of MES, whose tick the distance counts in, got contract ESH2026."
    with pytest.raises(ValueError, match=re.escape(expected)):
        ff.indicators.distance_from_vwap("MES").outputs_over(read)


def test_the_distance_counts_in_the_tick_of_the_bars_own_root_never_one_it_starts_with() -> None:
    # The reviews: spot bitcoin's root starts its perpetual's, whose tick is ten times its own,
    # so its perpetual's bars measured in spot ticks are refused; the perpetual's own pass.
    read = pl.DataFrame(
        {
            "ts_close": [1],
            "contract": ["BTCUSDT-PERP"],
            "close": [70_001 * POINT],
            "session_vwap": [70_000.0 * POINT],
            "atr": [10.0 * POINT],
        }
    )
    expected = (
        "Expected the bars of BTCUSDT, whose tick the distance counts in, got contract "
        "BTCUSDT-PERP."
    )

    with pytest.raises(ValueError, match=re.escape(expected)):
        ff.indicators.distance_from_vwap("BTCUSDT").outputs_over(read)
    perpetual = ff.indicators.distance_from_vwap("BTCUSDT-PERP").outputs_over(read).collect()
    assert perpetual.get_column("ticks").to_list() == [10.0]


def test_an_anchor_the_clock_skips_on_a_trade_date_is_refused_naming_the_feature() -> None:
    # A calendar trading on Sundays, as bitcoin's does, meets Chicago's clock change of
    # 2026-03-08, which skips 02:30 there: F-TIM-05 refuses such a local time.
    bars = frame(traded(date(2026, 3, 7), "08:00", 10), traded(date(2026, 3, 8), "08:00", 11))
    graph = FeatureGraph.of(
        {"cash_vwap": ff.indicators.session_vwap(anchor="02:30")}, "BTCUSDT-PERP", FIVE
    )
    expected = (
        "Expected feature session_vwap to evaluate over the bars of BTCUSDT-PERP 5m, got: datetime "
        "'2026-03-08 02:30:00' is non-existent in time zone 'America/Chicago'"
    )

    with pytest.raises(ValueError, match=re.escape(expected)):
        graph.evaluate({graph.signal_grid: bars})
