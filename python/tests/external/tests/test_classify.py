"""Matching the engines' trades and classifying every difference (step 2.14, Done means 2): each
engine's trade is held to the replay of its own rules on the 1-minute bars, a pair both rules
give is explained by a class, and a fill the rules do not give is `unknown`."""

from datetime import time
from zoneinfo import ZoneInfo

import polars as pl

from fefat_xcheck.classify import MATCH, TRADE_COLUMNS, DifferenceClass, classify, summarise
from fefat_xcheck.conventions import (
    NAUTILUS_ADAPTIVE,
    NAUTILUS_OHLC,
    NINJATRADER,
    EngineConventions,
    Extreme,
)
from fefat_xcheck.replay import Rules

TICK = 250_000_000
POINT = 1_000_000_000
MINUTE = 60_000_000_000
DECISION = 1_000_000 * MINUTE
"""1971-11-26 10:40 UTC, on the 5-minute grid."""
NEVER = time(23, 59)
UTC = ZoneInfo("UTC")


def price(points: float) -> int:
    return round(points * POINT)


def rules(conventions: EngineConventions, flat_by: time = NEVER) -> Rules:
    """The other engine's rules: entries two ticks from the close, the flat-by in UTC."""
    return Rules(conventions, TICK, 2, flat_by, UTC)


def bars(*rows: tuple[int, float, float, float, float]) -> pl.DataFrame:
    """1-minute bars, each (minutes after the decision, open, high, low, close) in points."""
    return pl.DataFrame(
        {
            "ts_close": [DECISION + minutes * MINUTE for minutes, *_ in rows],
            "open": [price(open) for _, open, *_ in rows],
            "high": [price(high) for _, _, high, *_ in rows],
            "low": [price(low) for *_, low, _ in rows],
            "close": [price(close) for *_, close in rows],
        }
    )


def trade(
    decision: int = DECISION,
    side: str = "long",
    entry_kind: str = "market",
    entry_minutes: int = 1,
    entry: float = 100.25,
    exit_minutes: int = 5,
    exit: float = 103.0,
    exit_reason: str = "target",
    stop: float = 97.0,
    target: float = 103.0,
) -> dict[str, object]:
    return {
        "entry_decision": decision,
        "side": side,
        "entry_kind": entry_kind,
        "entry_ts": decision + entry_minutes * MINUTE,
        "entry_price": price(entry),
        "exit_ts": decision + exit_minutes * MINUTE,
        "exit_price": price(exit),
        "exit_reason": exit_reason,
        "stop_price": price(stop),
        "target_price": price(target),
        "gross_pnl": 0.0,
    }


def trades(*rows: dict[str, object]) -> pl.DataFrame:
    return pl.DataFrame(list(rows), schema=TRADE_COLUMNS)


QUIET = bars(
    (0, 100.0, 100.25, 99.75, 100.0),
    (1, 100.25, 100.5, 100.0, 100.25),
    (2, 100.25, 101.0, 100.0, 100.75),
    (3, 100.75, 101.5, 100.5, 101.25),
    (4, 101.25, 102.0, 101.0, 101.75),
    (5, 101.75, 103.25, 101.5, 103.0),
)
"""A quiet climb to the target in the fifth minute, the decision's bar closing at 100."""


def test_identical_trades_the_rules_give_match() -> None:
    classified = classify(trades(trade()), trades(trade()), QUIET, rules(NINJATRADER))

    assert classified["outcome"].to_list() == [MATCH]
    assert classified["entry_outcome"].to_list() == [MATCH]
    assert classified["exit_outcome"].to_list() == [MATCH]


def test_a_market_entry_at_the_decisions_close_against_the_next_open_is_bar_boundary() -> None:
    nautilus = trade(entry_minutes=0, entry=100.0)

    classified = classify(trades(trade()), trades(nautilus), QUIET, rules(NAUTILUS_OHLC))

    assert classified["entry_outcome"].to_list() == [str(DifferenceClass.BAR_BOUNDARY)]
    assert classified["exit_outcome"].to_list() == [MATCH]
    assert classified["outcome"].to_list() == [str(DifferenceClass.BAR_BOUNDARY)]
    assert classified["entry_ticks"].to_list() == [1]


def test_a_market_entry_at_the_same_price_matches_whatever_its_stamp() -> None:
    """The next minute opens at the previous close, so both conventions give one price."""
    steady = bars(
        (0, 100.0, 100.25, 99.75, 100.25),
        (1, 100.25, 100.5, 100.0, 100.25),
        (2, 100.25, 101.0, 100.0, 100.75),
        (3, 100.75, 101.5, 100.5, 101.25),
        (4, 101.25, 102.0, 101.0, 101.75),
        (5, 101.75, 103.25, 101.5, 103.0),
    )
    fefat = trade(entry=100.25)
    nautilus = trade(entry_minutes=0, entry=100.25)

    classified = classify(trades(fefat), trades(nautilus), steady, rules(NAUTILUS_OHLC))

    assert classified["outcome"].to_list() == [MATCH]


def test_a_market_entry_off_its_rules_is_unknown() -> None:
    nautilus = trade(entry_minutes=0, entry=100.5)

    classified = classify(trades(trade()), trades(nautilus), QUIET, rules(NAUTILUS_OHLC))

    assert classified["entry_outcome"].to_list() == [str(DifferenceClass.UNKNOWN)]
    assert classified["outcome"].to_list() == [str(DifferenceClass.UNKNOWN)]


def test_a_fefat_exit_off_its_rules_is_unknown() -> None:
    """A target filled better than its price (F-LMT-03 forbids) stays unknown."""
    fefat = trade(exit=103.25)

    classified = classify(trades(fefat), trades(trade()), QUIET, rules(NINJATRADER))

    assert classified["exit_outcome"].to_list() == [str(DifferenceClass.UNKNOWN)]


WIDE_THIRD_BAR = bars(
    (0, 100.0, 100.25, 99.75, 100.0),
    (1, 100.25, 100.5, 100.0, 100.25),
    (2, 100.25, 101.0, 100.0, 100.75),
    (3, 100.5, 103.25, 96.75, 101.0),
)
"""The third minute reaches both legs, its open nearer its high."""


def test_both_legs_in_one_later_bar_where_the_other_path_reaches_the_target_first() -> None:
    fefat = trade(exit_minutes=3, exit=97.0, exit_reason="stop")
    ninjatrader = trade(exit_minutes=3, exit=103.0)
    nautilus = trade(entry_minutes=0, entry=100.0, exit_minutes=3, exit=103.0)

    nearest = classify(trades(fefat), trades(ninjatrader), WIDE_THIRD_BAR, rules(NINJATRADER))
    ohlc = classify(trades(fefat), trades(nautilus), WIDE_THIRD_BAR, rules(NAUTILUS_OHLC))

    assert nearest["outcome"].to_list() == [str(DifferenceClass.BAR_PATH)]
    assert nearest["exit_ticks"].to_list() == [-24]
    assert ohlc["entry_outcome"].to_list() == [str(DifferenceClass.BAR_BOUNDARY)]
    assert ohlc["exit_outcome"].to_list() == [str(DifferenceClass.BAR_PATH)]


def test_the_other_engine_taking_the_leg_its_path_reaches_second_is_unknown() -> None:
    """A short's stop lies above: the nearest extreme first, the high, reaches it before the
    target at the low, so NinjaTrader taking the target is not what its rules give."""
    fefat = trade(
        side="short", exit_minutes=3, exit=103.0, exit_reason="stop", stop=103.0, target=97.0
    )
    other = trade(side="short", exit_minutes=3, exit=97.0, stop=103.0, target=97.0)

    classified = classify(trades(fefat), trades(other), WIDE_THIRD_BAR, rules(NINJATRADER))

    assert classified["exit_outcome"].to_list() == [str(DifferenceClass.UNKNOWN)]


def test_a_short_whose_bar_reaches_its_target_first_under_the_adaptive_path_is_bar_path() -> None:
    """The bar opens nearer its low than its high, so the adaptive path visits the low, the
    short's target, before the high, its stop (F-BAR-02 fills the stop)."""
    low_first = bars(
        (0, 100.0, 100.25, 99.75, 100.0),
        (1, 100.25, 100.5, 100.0, 100.25),
        (2, 99.0, 103.25, 96.75, 101.0),
    )
    fefat = trade(
        side="short", exit_minutes=2, exit=103.0, exit_reason="stop", stop=103.0, target=97.0
    )
    nautilus = trade(
        side="short",
        entry_minutes=0,
        entry=100.0,
        exit_minutes=2,
        exit=97.0,
        stop=103.0,
        target=97.0,
    )

    adaptive = classify(trades(fefat), trades(nautilus), low_first, rules(NAUTILUS_ADAPTIVE))
    ohlc = classify(trades(fefat), trades(nautilus), low_first, rules(NAUTILUS_OHLC))

    assert adaptive["exit_outcome"].to_list() == [str(DifferenceClass.BAR_PATH)]
    assert ohlc["exit_outcome"].to_list() == [str(DifferenceClass.UNKNOWN)]


def test_a_stop_released_on_the_tick_already_past_it_fills_at_that_tick_in_nautilus() -> None:
    """A buy limit two ticks under the close fills on the next bar's low tick in Nautilus, and
    the stop it releases is already below that tick: Nautilus fills it at the low, FEFAT at the
    stop's level on the way down (the real pair of 2026-08-03 13:40 UTC, in ticks)."""
    bar = bars((0, 100.0, 101.25, 99.0, 101.5), (1, 101.5, 102.75, 95.25, 100.5))
    fefat = trade(
        entry_kind="limit",
        entry=101.0,
        exit_minutes=1,
        exit=98.5,
        exit_reason="stop",
        stop=98.5,
        target=104.5,
    )
    nautilus = trade(
        entry_kind="limit",
        entry=101.0,
        exit_minutes=1,
        exit=95.25,
        exit_reason="stop",
        stop=98.5,
        target=104.5,
    )

    classified = classify(trades(fefat), trades(nautilus), bar, rules(NAUTILUS_OHLC))

    assert classified["entry_outcome"].to_list() == [MATCH]
    assert classified["exit_outcome"].to_list() == [str(DifferenceClass.LEG_RELEASED_THROUGH)]
    assert classified["exit_ticks"].to_list() == [13]


def test_a_target_released_on_the_tick_already_past_it_fills_at_that_tick_in_nautilus() -> None:
    """A buy stop two ticks over the close fills on the next bar's high tick, which is already
    above the target it releases: Nautilus fills the target at the high, FEFAT at its price."""
    bar = bars((0, 100.0, 101.25, 99.0, 100.0), (1, 100.0, 107.0, 99.75, 105.0))
    fefat = trade(entry_kind="stop", entry=100.5, exit_minutes=1, exit=103.0)
    nautilus = trade(entry_kind="stop", entry=100.5, exit_minutes=1, exit=107.0)

    classified = classify(trades(fefat), trades(nautilus), bar, rules(NAUTILUS_ADAPTIVE))

    assert classified["outcome"].to_list() == [str(DifferenceClass.LEG_RELEASED_THROUGH)]


def test_a_released_leg_at_another_price_than_the_tick_is_unknown() -> None:
    bar = bars((0, 100.0, 101.25, 99.0, 100.0), (1, 100.0, 107.0, 99.75, 105.0))
    fefat = trade(entry_kind="stop", entry=100.5, exit_minutes=1, exit=103.0)
    nautilus = trade(entry_kind="stop", entry=100.5, exit_minutes=1, exit=106.0)

    classified = classify(trades(fefat), trades(nautilus), bar, rules(NAUTILUS_OHLC))

    assert classified["outcome"].to_list() == [str(DifferenceClass.UNKNOWN)]


SELL_LIMIT_BARS = bars(
    (0, 104.0, 104.25, 100.0, 100.0),
    (1, 100.0, 101.75, 95.25, 97.25),
    (2, 97.25, 101.75, 96.75, 101.5),
)
"""A sell limit at 100.5 fills on the way up in the first minute; the target at 97 lies below
the first minute's close and inside the second minute (the real pair of 2026-08-04 18:00 UTC)."""


def test_an_extreme_visited_after_the_entry_in_one_engine_only_is_entry_bar_path() -> None:
    """FEFAT visited the low before the fill (the favourable extreme first, F-BAR-03) and goes
    high, close after it, so the target waits for the next bar; Nautilus's fixed order visits
    the low after the high and fills the target on the rest of the bar."""
    fefat = trade(
        side="short",
        entry_kind="limit",
        entry=100.5,
        exit_minutes=2,
        exit=97.0,
        stop=103.0,
        target=97.0,
    )
    nautilus = trade(
        side="short",
        entry_kind="limit",
        entry=100.5,
        exit_minutes=1,
        exit=97.0,
        stop=103.0,
        target=97.0,
    )

    classified = classify(trades(fefat), trades(nautilus), SELL_LIMIT_BARS, rules(NAUTILUS_OHLC))

    assert classified["entry_outcome"].to_list() == [MATCH]
    assert classified["exit_outcome"].to_list() == [str(DifferenceClass.ENTRY_BAR_PATH)]


def test_a_later_exit_off_its_rules_after_an_entry_inside_a_bar_is_unknown() -> None:
    """The same pair with FEFAT's target filled a tick better than its price: not what F-LMT-03
    gives, so the entry bar's paths explain nothing."""
    fefat = trade(
        side="short",
        entry_kind="limit",
        entry=100.5,
        exit_minutes=2,
        exit=96.75,
        stop=103.0,
        target=97.0,
    )
    nautilus = trade(
        side="short",
        entry_kind="limit",
        entry=100.5,
        exit_minutes=1,
        exit=97.0,
        stop=103.0,
        target=97.0,
    )

    classified = classify(trades(fefat), trades(nautilus), SELL_LIMIT_BARS, rules(NAUTILUS_OHLC))

    assert classified["exit_outcome"].to_list() == [str(DifferenceClass.UNKNOWN)]


def test_a_stop_entry_whose_bar_reaches_the_stop_after_the_fill_in_fefat_only_is_entry_bar_path() -> (
    None
):
    """A sell stop below the open fills on the way down to the low (the favourable extreme
    first); FEFAT then visits the high, the short's adverse extreme, and fills the stop; Nautilus
    visited the high before the low and carries the position into the next bar."""
    bar = bars(
        (0, 100.0, 100.25, 99.0, 100.0),
        (1, 100.0, 104.0, 98.0, 102.5),
        (2, 102.5, 104.0, 102.0, 103.5),
    )
    fefat = trade(
        side="short",
        entry_kind="stop",
        entry=99.5,
        exit_minutes=1,
        exit=103.0,
        exit_reason="stop",
        stop=103.0,
        target=97.0,
    )
    nautilus = trade(
        side="short",
        entry_kind="stop",
        entry=99.5,
        exit_minutes=2,
        exit=103.0,
        exit_reason="stop",
        stop=103.0,
        target=97.0,
    )

    classified = classify(trades(fefat), trades(nautilus), bar, rules(NAUTILUS_OHLC))

    assert classified["exit_outcome"].to_list() == [str(DifferenceClass.ENTRY_BAR_PATH)]


def test_a_trade_of_one_engine_while_the_other_held_a_position_is_a_cascade() -> None:
    earlier = DECISION - 10 * MINUTE
    fefat = trades(trade(decision=earlier, exit_minutes=8), trade())
    other = trades(trade(decision=earlier, exit_minutes=12))

    classified = classify(fefat, other, QUIET, rules(NINJATRADER)).sort("entry_decision")

    assert classified["in_fefat"].to_list() == [True, True]
    assert classified["in_other"].to_list() == [True, False]
    assert classified["outcome"].to_list() == [
        str(DifferenceClass.UNKNOWN),
        str(DifferenceClass.CASCADE),
    ]


def test_a_lone_trade_off_its_rules_is_unknown_even_while_the_other_held_a_position() -> None:
    earlier = DECISION - 10 * MINUTE
    fefat = trades(trade(decision=earlier, exit_minutes=8), trade(entry=150.0))
    other = trades(trade(decision=earlier, exit_minutes=12))

    classified = classify(fefat, other, QUIET, rules(NINJATRADER)).sort("entry_decision")

    assert classified["outcome"].to_list()[1] == str(DifferenceClass.UNKNOWN)
    assert "not what its rules give" in classified["note"].to_list()[1]


def test_a_trade_of_one_engine_while_the_other_was_flat_is_unknown() -> None:
    classified = classify(trades(trade()), trades(), QUIET, rules(NINJATRADER))

    assert classified["outcome"].to_list() == [str(DifferenceClass.UNKNOWN)]
    assert classified["in_other"].to_list() == [False]


FLAT_BY = time(10, 44)
"""The flat-by decision four minutes after the decision, on the test's UTC clock."""
CLIMB_TO_THE_FLAT_BY = (
    (0, 100.0, 100.25, 99.75, 100.0),
    (1, 100.25, 100.5, 100.0, 100.25),
    (2, 100.25, 101.0, 100.0, 100.75),
    (3, 100.75, 101.5, 100.5, 101.25),
)


def test_a_flat_by_exit_at_the_decisions_close_against_the_next_open_is_bar_boundary() -> None:
    at_the_open = bars(
        *CLIMB_TO_THE_FLAT_BY, (4, 101.25, 102.0, 101.0, 101.5), (5, 101.75, 102.0, 101.5, 101.75)
    )
    fefat = trade(exit_minutes=5, exit=101.75, exit_reason="flat_by")
    nautilus = trade(
        entry_minutes=0, entry=100.0, exit_minutes=4, exit=101.5, exit_reason="flat_by"
    )

    classified = classify(
        trades(fefat), trades(nautilus), at_the_open, rules(NAUTILUS_OHLC, FLAT_BY)
    )

    assert classified["exit_outcome"].to_list() == [str(DifferenceClass.BAR_BOUNDARY)]
    assert classified["exit_ticks"].to_list() == [1]


def test_a_flat_by_exit_at_the_same_price_matches_whatever_its_stamp() -> None:
    steady = bars(
        *CLIMB_TO_THE_FLAT_BY, (4, 101.25, 102.0, 101.0, 101.75), (5, 101.75, 102.0, 101.5, 101.75)
    )
    fefat = trade(exit_minutes=5, exit=101.75, exit_reason="flat_by")
    nautilus = trade(
        entry_minutes=0, entry=100.0, exit_minutes=4, exit=101.75, exit_reason="flat_by"
    )

    classified = classify(trades(fefat), trades(nautilus), steady, rules(NAUTILUS_OHLC, FLAT_BY))

    assert classified["exit_outcome"].to_list() == [MATCH]


def test_an_exit_off_its_rules_behind_a_classified_entry_makes_the_trade_unknown() -> None:
    """A market entry the convention explains, then a stop FEFAT filled a bar late: the trade is
    unknown, so that the entry's class hides nothing."""
    late_low = bars(
        *CLIMB_TO_THE_FLAT_BY,
        (4, 101.25, 102.0, 96.75, 101.75),
        (5, 101.75, 103.25, 96.5, 103.0),
    )
    nautilus = trade(entry_minutes=0, entry=100.0, exit_minutes=4, exit=97.0, exit_reason="stop")
    fefat = trade(exit_minutes=5, exit=97.0, exit_reason="stop")

    classified = classify(trades(fefat), trades(nautilus), late_low, rules(NAUTILUS_OHLC))

    assert classified["exit_outcome"].to_list() == [str(DifferenceClass.UNKNOWN)]
    assert classified["outcome"].to_list() == [str(DifferenceClass.UNKNOWN)]
    assert summarise(classified).unknown == 1


def test_a_market_entry_after_a_bucket_whose_last_minute_had_no_bar_is_bar_boundary() -> None:
    """The decision's own minute stored no bar: Nautilus filled at the close of the last bar
    before the decision, FEFAT at the open of the first after it."""
    gap_at_the_decision = bars(
        (-1, 99.5, 100.25, 99.25, 100.0),
        (1, 100.25, 100.5, 100.0, 100.25),
        (5, 101.75, 103.25, 101.5, 103.0),
    )
    nautilus = trade(entry_minutes=0, entry=100.0)

    classified = classify(
        trades(trade()), trades(nautilus), gap_at_the_decision, rules(NAUTILUS_OHLC)
    )

    assert classified["entry_outcome"].to_list() == [str(DifferenceClass.BAR_BOUNDARY)]
    assert classified["exit_outcome"].to_list() == [MATCH]


GAPPED = bars(
    (0, 100.0, 100.25, 99.75, 100.0),
    (1, 100.0, 100.5, 99.5, 99.75),
    (2, 99.75, 100.0, 99.0, 99.25),
    (3, 95.0, 96.0, 92.0, 94.5),
)
"""The fourth minute opens and stays below a short's target at 97."""


def test_a_limit_passed_by_a_gap_fills_clamped_into_the_bar_in_ninjatrader_only() -> None:
    """A short's target, a buy limit, sits above a bar that opens and stays below it: FEFAT
    fills it at its price, NinjaTrader 8 at the bar's high (the real pair of 2026-08-10
    16:30 UTC, in ticks); NautilusTrader would have filled it at its price."""
    fefat = trade(side="short", entry=100.0, exit_minutes=3, exit=97.0, stop=103.0, target=97.0)
    ninjatrader = trade(
        side="short", entry=100.0, exit_minutes=3, exit=96.0, stop=103.0, target=97.0
    )
    nautilus = trade(
        side="short",
        entry_minutes=0,
        entry=100.0,
        exit_minutes=3,
        exit=96.0,
        stop=103.0,
        target=97.0,
    )

    clamped = classify(trades(fefat), trades(ninjatrader), GAPPED, rules(NINJATRADER))
    at_its_price = classify(trades(fefat), trades(nautilus), GAPPED, rules(NAUTILUS_OHLC))

    assert clamped["exit_outcome"].to_list() == [str(DifferenceClass.GAP_LIMIT_CLAMPED)]
    assert clamped["exit_ticks"].to_list() == [4]
    assert at_its_price["exit_outcome"].to_list() == [str(DifferenceClass.UNKNOWN)]


def test_a_longs_target_below_a_bar_that_gaps_past_it_is_clamped_to_the_low() -> None:
    gapped_up = bars(
        (0, 100.0, 100.25, 99.75, 100.0),
        (1, 100.0, 100.5, 99.5, 100.25),
        (2, 105.0, 106.0, 104.0, 105.5),
    )
    fefat = trade(entry=100.0, exit_minutes=2, exit=103.0)
    ninjatrader = trade(entry=100.0, exit_minutes=2, exit=104.0)

    classified = classify(trades(fefat), trades(ninjatrader), gapped_up, rules(NINJATRADER))

    assert classified["exit_outcome"].to_list() == [str(DifferenceClass.GAP_LIMIT_CLAMPED)]


def test_the_summary_counts_trades_and_the_pairs_fills_by_outcome() -> None:
    nautilus = trade(entry_minutes=0, entry=100.0)
    classified = classify(
        trades(trade(), trade(decision=DECISION + 10 * MINUTE)),
        trades(nautilus),
        QUIET,
        rules(NAUTILUS_OHLC),
    )

    summary = summarise(classified)

    assert summary.fefat_trades == 2
    assert summary.other_trades == 1
    assert summary.matched == 1
    assert summary.exact == 0
    assert summary.fills_compared == 2
    assert summary.equal_fills == 1
    assert summary.trades_by_class == {"bar_boundary": 1, "unknown": 1}
    assert summary.fills_by_class == {"bar_boundary": 1}
    assert summary.unknown == 1


def test_the_nearest_extreme_first_on_a_tie_is_the_engines_own() -> None:
    halfway = (price(100.0), price(104.0), price(96.0))
    nearer_high = (price(100.0), price(103.0), price(96.0))

    assert NAUTILUS_ADAPTIVE.first_extreme(*halfway, long=True) == Extreme.LOW
    assert NINJATRADER.first_extreme(*halfway, long=True) == Extreme.HIGH
    assert NAUTILUS_ADAPTIVE.first_extreme(*nearer_high, long=False) == Extreme.HIGH
    assert NAUTILUS_OHLC.first_extreme(*halfway, long=False) == Extreme.HIGH


def test_a_target_at_the_entrys_own_point_fills_there_in_every_engine() -> None:
    """A buy stop two ticks over the close fills at a gap open exactly at the target: FEFAT's
    target is past at the entry's point and fills there at its price (the reference engine's
    `fill`, F-OCO-02, F-LMT-03), as Nautilus's released target does on the open tick, although
    the bar also reaches the stop."""
    bar = bars((0, 100.0, 100.25, 99.75, 100.0), (1, 103.0, 103.5, 96.5, 100.0))
    both = trade(entry_kind="stop", entry=103.0, exit_minutes=1, exit=103.0)

    classified = classify(trades(both), trades(both), bar, rules(NAUTILUS_OHLC))

    assert classified["outcome"].to_list() == [MATCH]
