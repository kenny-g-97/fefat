"""Matching the engines' trades and classifying every difference (step 2.14, Done means 2): each
class's predicate checks the 1-minute bars support its explanation, and a difference no
predicate explains is `unknown`."""

import polars as pl

from fefat_xcheck.classify import MATCH, TRADE_COLUMNS, DifferenceClass, classify, summarise
from fefat_xcheck.conventions import NAUTILUS_ADAPTIVE, NAUTILUS_OHLC, NINJATRADER

TICK = 250_000_000
POINT = 1_000_000_000
MINUTE = 60_000_000_000
DECISION = 1_000_000 * MINUTE


def price(points: float) -> int:
    return round(points * POINT)


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


def test_identical_trades_match() -> None:
    classified = classify(trades(trade()), trades(trade()), QUIET, NINJATRADER, TICK)

    assert classified["outcome"].to_list() == [MATCH]
    assert classified["entry_outcome"].to_list() == [MATCH]
    assert classified["exit_outcome"].to_list() == [MATCH]


def test_a_market_entry_at_the_decisions_close_against_the_next_open_is_bar_boundary() -> None:
    nautilus = trade(entry_minutes=0, entry=100.0)

    classified = classify(trades(trade()), trades(nautilus), QUIET, NAUTILUS_OHLC, TICK)

    assert classified["entry_outcome"].to_list() == [str(DifferenceClass.BAR_BOUNDARY)]
    assert classified["exit_outcome"].to_list() == [MATCH]
    assert classified["outcome"].to_list() == [str(DifferenceClass.BAR_BOUNDARY)]
    assert classified["entry_ticks"].to_list() == [1]


def test_a_market_entry_at_the_same_price_matches_whatever_its_stamp() -> None:
    nautilus = trade(entry_minutes=0, entry=100.25)

    classified = classify(trades(trade()), trades(nautilus), QUIET, NAUTILUS_OHLC, TICK)

    assert classified["outcome"].to_list() == [MATCH]


def test_a_market_entry_off_both_conventions_is_unknown() -> None:
    nautilus = trade(entry_minutes=0, entry=100.5)

    classified = classify(trades(trade()), trades(nautilus), QUIET, NAUTILUS_OHLC, TICK)

    assert classified["outcome"].to_list() == [str(DifferenceClass.UNKNOWN)]


WIDE_THIRD_BAR = bars(
    (0, 100.0, 100.25, 99.75, 100.0),
    (1, 100.25, 100.5, 100.0, 100.25),
    (2, 100.25, 101.0, 100.0, 100.75),
    (3, 100.5, 103.25, 96.75, 101.0),
)


def test_both_legs_in_one_bar_where_the_other_path_reaches_the_target_first_is_bar_path() -> None:
    fefat = trade(exit_minutes=3, exit=97.0, exit_reason="stop")
    other = trade(exit_minutes=3, exit=103.0, exit_reason="target")

    nearest = classify(trades(fefat), trades(other), WIDE_THIRD_BAR, NINJATRADER, TICK)
    ohlc = classify(trades(fefat), trades(other), WIDE_THIRD_BAR, NAUTILUS_OHLC, TICK)

    assert nearest["exit_outcome"].to_list() == [str(DifferenceClass.BAR_PATH)]
    assert nearest["outcome"].to_list() == [str(DifferenceClass.BAR_PATH)]
    assert nearest["exit_ticks"].to_list() == [-24]
    assert ohlc["outcome"].to_list() == [str(DifferenceClass.BAR_PATH)]


def test_both_legs_in_one_bar_where_the_other_path_reaches_the_stop_first_is_unknown() -> None:
    """A short's stop lies above: the nearest extreme first, the high, reaches it before the
    target at the low, so an engine of that path taking the target is unexplained."""
    fefat = trade(
        side="short", exit_minutes=3, exit=103.0, exit_reason="stop", stop=103.0, target=97.0
    )
    other = trade(
        side="short", exit_minutes=3, exit=97.0, exit_reason="target", stop=103.0, target=97.0
    )

    classified = classify(trades(fefat), trades(other), WIDE_THIRD_BAR, NINJATRADER, TICK)

    assert classified["outcome"].to_list() == [str(DifferenceClass.UNKNOWN)]


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
    other = trade(
        side="short", exit_minutes=2, exit=97.0, exit_reason="target", stop=103.0, target=97.0
    )

    adaptive = classify(trades(fefat), trades(other), low_first, NAUTILUS_ADAPTIVE, TICK)
    ohlc = classify(trades(fefat), trades(other), low_first, NAUTILUS_OHLC, TICK)

    assert adaptive["outcome"].to_list() == [str(DifferenceClass.BAR_PATH)]
    assert ohlc["outcome"].to_list() == [str(DifferenceClass.UNKNOWN)]


def test_a_stop_released_on_the_tick_already_past_it_fills_at_that_tick_in_nautilus() -> None:
    """A buy limit two ticks under the close fills on the next bar's low tick in Nautilus, and
    the stop it releases is already below that tick: Nautilus fills it at the low, FEFAT at the
    stop's level on the way down (the real pair of 2026-08-03 13:40 UTC, in ticks)."""
    bar = bars((0, 100.0, 101.25, 99.0, 101.5), (1, 101.5, 102.75, 95.25, 100.5))
    fefat = trade(
        entry_kind="limit",
        entry_minutes=1,
        entry=101.0,
        exit_minutes=1,
        exit=98.5,
        exit_reason="stop",
        stop=98.5,
        target=104.5,
    )
    nautilus = trade(
        entry_kind="limit",
        entry_minutes=1,
        entry=101.0,
        exit_minutes=1,
        exit=95.25,
        exit_reason="stop",
        stop=98.5,
        target=104.5,
    )

    classified = classify(trades(fefat), trades(nautilus), bar, NAUTILUS_OHLC, TICK)

    assert classified["entry_outcome"].to_list() == [MATCH]
    assert classified["exit_outcome"].to_list() == [str(DifferenceClass.LEG_RELEASED_THROUGH)]
    assert classified["exit_ticks"].to_list() == [13]


def test_a_target_released_on_the_tick_already_past_it_fills_at_that_tick_in_nautilus() -> None:
    """A buy stop two ticks over the close fills on the next bar's high tick, which is already
    above the target it releases: Nautilus fills the target at the high, FEFAT at its price."""
    bar = bars((0, 100.0, 101.25, 99.0, 100.0), (1, 100.0, 107.0, 99.75, 105.0))
    fefat = trade(
        entry_kind="stop",
        entry_minutes=1,
        entry=100.5,
        exit_minutes=1,
        exit=103.0,
        exit_reason="target",
        stop=97.0,
        target=103.0,
    )
    nautilus = trade(
        entry_kind="stop",
        entry_minutes=1,
        entry=100.5,
        exit_minutes=1,
        exit=107.0,
        exit_reason="target",
        stop=97.0,
        target=103.0,
    )

    classified = classify(trades(fefat), trades(nautilus), bar, NAUTILUS_ADAPTIVE, TICK)

    assert classified["outcome"].to_list() == [str(DifferenceClass.LEG_RELEASED_THROUGH)]


def test_a_released_leg_at_another_price_than_the_tick_is_unknown() -> None:
    bar = bars((0, 100.0, 101.25, 99.0, 100.0), (1, 100.0, 107.0, 99.75, 105.0))
    fefat = trade(
        entry_kind="stop",
        entry_minutes=1,
        entry=100.5,
        exit_minutes=1,
        exit=103.0,
        exit_reason="target",
        stop=97.0,
        target=103.0,
    )
    nautilus = trade(
        entry_kind="stop",
        entry_minutes=1,
        entry=100.5,
        exit_minutes=1,
        exit=106.0,
        exit_reason="target",
        stop=97.0,
        target=103.0,
    )

    classified = classify(trades(fefat), trades(nautilus), bar, NAUTILUS_OHLC, TICK)

    assert classified["outcome"].to_list() == [str(DifferenceClass.UNKNOWN)]


def test_an_extreme_visited_after_the_entry_in_one_engine_only_is_entry_bar_path() -> None:
    """A sell limit above the open fills on the way up. FEFAT visited the low before the fill
    (the favourable extreme first, F-BAR-03) and goes high, close after it, so the target below
    waits for the next bar; Nautilus's fixed order visits the low after the high and fills the
    target on the rest of the bar (the real pair of 2026-08-04 18:00 UTC, in ticks)."""
    bar = bars(
        (0, 104.0, 104.25, 100.0, 100.0),
        (1, 100.0, 101.75, 95.25, 97.25),
        (2, 97.25, 101.75, 96.75, 101.5),
    )
    fefat = trade(
        side="short",
        entry_kind="limit",
        entry_minutes=1,
        entry=100.5,
        exit_minutes=2,
        exit=97.0,
        exit_reason="target",
        stop=103.0,
        target=97.0,
    )
    nautilus = trade(
        side="short",
        entry_kind="limit",
        entry_minutes=1,
        entry=100.5,
        exit_minutes=1,
        exit=97.0,
        exit_reason="target",
        stop=103.0,
        target=97.0,
    )

    classified = classify(trades(fefat), trades(nautilus), bar, NAUTILUS_OHLC, TICK)

    assert classified["entry_outcome"].to_list() == [MATCH]
    assert classified["exit_outcome"].to_list() == [str(DifferenceClass.ENTRY_BAR_PATH)]


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
        entry_minutes=1,
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
        entry_minutes=1,
        entry=99.5,
        exit_minutes=2,
        exit=103.0,
        exit_reason="stop",
        stop=103.0,
        target=97.0,
    )

    classified = classify(trades(fefat), trades(nautilus), bar, NAUTILUS_OHLC, TICK)

    assert classified["exit_outcome"].to_list() == [str(DifferenceClass.ENTRY_BAR_PATH)]


def test_a_trade_of_one_engine_while_the_other_held_a_position_is_a_cascade() -> None:
    earlier = DECISION - 10 * MINUTE
    fefat = trades(trade(decision=earlier, exit_minutes=8), trade())
    other = trades(trade(decision=earlier, exit_minutes=12))

    classified = classify(fefat, other, QUIET, NINJATRADER, TICK).sort("entry_decision")

    assert classified["in_fefat"].to_list() == [True, True]
    assert classified["in_other"].to_list() == [True, False]
    assert classified["outcome"].to_list() == [
        str(DifferenceClass.UNKNOWN),
        str(DifferenceClass.CASCADE),
    ]


def test_a_trade_of_one_engine_while_the_other_was_flat_is_unknown() -> None:
    classified = classify(trades(trade()), trades(), QUIET, NINJATRADER, TICK)

    assert classified["outcome"].to_list() == [str(DifferenceClass.UNKNOWN)]
    assert classified["in_other"].to_list() == [False]


def test_a_flat_by_exit_at_the_decisions_close_against_the_next_open_is_bar_boundary() -> None:
    fefat = trade(exit_minutes=5, exit=101.75, exit_reason="flat_by")
    nautilus = trade(
        entry_minutes=0, entry=100.0, exit_minutes=4, exit=101.75, exit_reason="flat_by"
    )
    nautilus_at_close = trade(
        entry_minutes=0, entry=100.0, exit_minutes=4, exit=101.5, exit_reason="flat_by"
    )
    flat_by_bars = bars(
        (0, 100.0, 100.25, 99.75, 100.0),
        (1, 100.25, 100.5, 100.0, 100.25),
        (2, 100.25, 101.0, 100.0, 100.75),
        (3, 100.75, 101.5, 100.5, 101.25),
        (4, 101.25, 102.0, 101.0, 101.5),
        (5, 101.75, 102.0, 101.5, 101.75),
    )

    same_price = classify(trades(fefat), trades(nautilus), flat_by_bars, NAUTILUS_OHLC, TICK)
    at_close = classify(trades(fefat), trades(nautilus_at_close), flat_by_bars, NAUTILUS_OHLC, TICK)

    assert same_price["exit_outcome"].to_list() == [MATCH]
    assert at_close["exit_outcome"].to_list() == [str(DifferenceClass.BAR_BOUNDARY)]
    assert at_close["exit_ticks"].to_list() == [1]


def test_the_summary_counts_trades_and_fills_by_outcome() -> None:
    nautilus = trade(entry_minutes=0, entry=100.0)
    classified = classify(
        trades(trade(), trade(decision=DECISION + 10 * MINUTE)),
        trades(nautilus),
        QUIET,
        NAUTILUS_OHLC,
        TICK,
    )

    summary = summarise(classified)

    assert summary.fefat_trades == 2
    assert summary.other_trades == 1
    assert summary.matched == 1
    assert summary.exact == 0
    assert summary.fills_compared == 2
    assert summary.equal_fills == 1
    assert summary.trades_by_class == {"bar_boundary": 1, "unknown": 1}
    assert summary.fills_by_class == {"bar_boundary": 1, "unknown": 2}
    assert summary.unknown == 1


def test_the_nearest_extreme_first_on_a_tie_is_the_engines_own() -> None:
    from fefat_xcheck.conventions import Extreme

    halfway = (price(100.0), price(104.0), price(96.0))
    nearer_high = (price(100.0), price(103.0), price(96.0))

    assert NAUTILUS_ADAPTIVE.first_extreme(*halfway, long=True) == Extreme.LOW
    assert NINJATRADER.first_extreme(*halfway, long=True) == Extreme.HIGH
    assert NAUTILUS_ADAPTIVE.first_extreme(*nearer_high, long=False) == Extreme.HIGH
    assert NAUTILUS_OHLC.first_extreme(*halfway, long=False) == Extreme.HIGH
