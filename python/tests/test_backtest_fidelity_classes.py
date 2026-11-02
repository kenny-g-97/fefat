"""The classes of the differences between a run's fills on trade prints and on 1-minute bars
(step 2.16, Done means 2): hand-made trades of the three runs the tick check compares, the run on
the prints, the reference engine's replay of the prints with each print stamped at a decision's
instant moved after it (`restamped`), and the run on the bars, for each class and for each kind
of difference no class explains. Prices are made up, at the ticks that matter."""

from datetime import UTC, datetime
from typing import Any

import polars as pl
import pytest

from fefat.backtest.fidelity_classes import (
    MATCH,
    TRADE_COLUMNS,
    FidelityClass,
    classify,
    summarise,
)

TICK = 250_000_000
SECOND = 1_000_000_000
MINUTE = 60 * SECOND
DECISION = int(datetime(2026, 3, 2, 16, 0, tzinfo=UTC).timestamp()) * SECOND
LATER = DECISION + 5 * MINUTE
PRICE = 5_000 * 1_000_000_000


def at(minutes: int = 0, seconds: int = 0, decision: int = DECISION) -> int:
    return decision + minutes * MINUTE + seconds * SECOND


def on_prints(**changes: Any) -> dict[str, Any]:
    """A long market entry decided at DECISION as a run on prints fills it: in on the print 5 s
    after the decision, out at the target 3 min 10 s later, a stop and a target 12 ticks away."""
    trade = {
        "entry_decision": DECISION,
        "side": "long",
        "entry_kind": "market",
        "entry_ts": at(seconds=5),
        "entry_price": PRICE,
        "entry_level": None,
        "exit_ts": at(minutes=3, seconds=10),
        "exit_price": PRICE + 12 * TICK,
        "exit_reason": "target_1",
        "exit_ambiguous": False,
        "stop_price": PRICE - 12 * TICK,
        "target_price": PRICE + 12 * TICK,
    }
    return {**trade, **changes}


def on_bars(**changes: Any) -> dict[str, Any]:
    """The same trade as the 1-minute run fills it, each fill at the close of its bar."""
    return on_prints(**{"entry_ts": at(minutes=1), "exit_ts": at(minutes=4), **changes})


def trades(*rows: dict[str, Any]) -> pl.DataFrame:
    return pl.DataFrame(list(rows), schema=TRADE_COLUMNS)


def only_row(classified: pl.DataFrame, decision: int = DECISION) -> dict[str, Any]:
    return classified.filter(pl.col("entry_decision") == decision).row(0, named=True)


def outcomes(row: dict[str, Any]) -> tuple[str, str, str]:
    return row["entry_outcome"], row["exit_outcome"], row["outcome"]


def test_a_trade_alike_on_prints_and_bars_matches() -> None:
    classified = classify(trades(on_prints()), trades(on_prints()), trades(on_bars()), TICK)

    row = only_row(classified)
    assert outcomes(row) == (MATCH, MATCH, MATCH)
    assert (row["in_ticks"], row["in_minutes"], row["entry_ticks"], row["exit_ticks"]) == (
        True,
        True,
        0,
        0,
    )


def test_a_market_entry_the_decision_second_moves_is_a_bar_boundary() -> None:
    # On prints the market order fills after the decision's second, a tick higher; with that
    # second's prints after the decision it fills on the first of them, the bar's open.
    ticks = trades(on_prints(entry_ts=at(seconds=1), entry_price=PRICE + TICK))
    restamped = trades(on_prints(entry_ts=DECISION))

    row = only_row(classify(ticks, restamped, trades(on_bars()), TICK))

    assert outcomes(row) == (FidelityClass.BAR_BOUNDARY, MATCH, FidelityClass.BAR_BOUNDARY)
    assert (row["entry_ticks"], row["exit_ticks"]) == (1, 0)
    assert row["note"] == "entry bar_boundary; exit target_1 against target_1: match"


def test_a_trade_on_prints_alone_the_restamped_replay_does_not_make_is_a_bar_boundary() -> None:
    # A limit filled on a print of the second of the decision that cancels it (F-ENT-03).
    limit = on_prints(entry_kind="limit", entry_ts=LATER, entry_level=PRICE)

    row = only_row(classify(trades(limit), trades(), trades(), TICK))

    assert outcomes(row) == (FidelityClass.BAR_BOUNDARY,) * 3
    assert (row["in_ticks"], row["in_minutes"], row["entry_ticks"]) == (True, False, None)


def test_a_trade_on_bars_alone_the_restamped_replay_makes_is_a_bar_boundary() -> None:
    limit = on_bars(entry_kind="limit", entry_level=PRICE)

    row = only_row(classify(trades(), trades(on_prints(entry_kind="limit")), trades(limit), TICK))

    assert outcomes(row) == (FidelityClass.BAR_BOUNDARY,) * 3
    assert (row["in_ticks"], row["in_minutes"]) == (False, True)


def test_both_legs_in_a_bar_the_minute_run_flagged_ambiguous_are_a_bar_path() -> None:
    stopped = on_bars(exit_price=PRICE - 12 * TICK, exit_reason="stop", exit_ambiguous=True)

    row = only_row(classify(trades(on_prints()), trades(on_prints()), trades(stopped), TICK))

    assert outcomes(row) == (MATCH, FidelityClass.BAR_PATH, FidelityClass.BAR_PATH)
    assert row["exit_ticks"] == 24


def test_both_legs_in_a_bar_without_the_ambiguous_flag_are_unknown() -> None:
    stopped = on_bars(exit_price=PRICE - 12 * TICK, exit_reason="stop")

    row = only_row(classify(trades(on_prints()), trades(on_prints()), trades(stopped), TICK))

    assert row["exit_outcome"] == FidelityClass.UNKNOWN


def test_the_rest_of_a_limit_entrys_bar_is_an_entry_bar_path() -> None:
    # The prints after the fill reached the target inside the entry's minute; the 1-minute path
    # after a limit's fill goes to the low and the close (F-BAR-03, F-BAR-04) and carries it on.
    limit = {"entry_kind": "limit", "entry_level": PRICE}
    prints = on_prints(**limit, entry_ts=at(minutes=2, seconds=5), exit_ts=at(2, 40))
    bars = on_bars(**limit, entry_ts=at(minutes=3), exit_ts=at(minutes=6))

    row = only_row(classify(trades(prints), trades(prints), trades(bars), TICK))

    assert outcomes(row) == (MATCH, FidelityClass.ENTRY_BAR_PATH, FidelityClass.ENTRY_BAR_PATH)


def test_a_stop_filled_at_a_print_past_its_level_is_a_stop_through() -> None:
    prints = on_prints(exit_price=PRICE - 13 * TICK, exit_reason="stop")
    bars = on_bars(exit_price=PRICE - 12 * TICK, exit_reason="stop")

    row = only_row(classify(trades(prints), trades(prints), trades(bars), TICK))

    assert outcomes(row) == (MATCH, FidelityClass.STOP_THROUGH, FidelityClass.STOP_THROUGH)
    assert row["exit_ticks"] == -1


def test_a_stop_entry_filled_at_a_print_past_its_level_is_a_stop_through() -> None:
    level = PRICE + 2 * TICK
    entry = {"entry_kind": "stop", "entry_level": level}
    prints = on_prints(**entry, entry_ts=at(2, 5), entry_price=level + TICK)
    bars = on_bars(**entry, entry_ts=at(minutes=3), entry_price=level)

    row = only_row(classify(trades(prints), trades(prints), trades(bars), TICK))

    assert outcomes(row) == (FidelityClass.STOP_THROUGH, MATCH, FidelityClass.STOP_THROUGH)
    assert row["entry_ticks"] == 1


def test_a_stop_filled_at_its_level_on_prints_and_elsewhere_on_bars_is_unknown() -> None:
    prints = on_prints(exit_price=PRICE - 12 * TICK, exit_reason="stop")
    bars = on_bars(exit_price=PRICE - 14 * TICK, exit_reason="stop")

    row = only_row(classify(trades(prints), trades(prints), trades(bars), TICK))

    assert row["exit_outcome"] == FidelityClass.UNKNOWN


def test_a_trade_made_while_the_other_run_held_a_position_is_a_cascade() -> None:
    # The first trade's exit parted the runs in its limit entry's bar; the 1-minute run still
    # held the position at the next decision, where the runs on prints entered again.
    limit = {"entry_kind": "limit", "entry_level": PRICE}
    first = on_prints(**limit, entry_ts=at(2, 5), exit_ts=at(2, 40))
    held = on_bars(**limit, entry_ts=at(minutes=3), exit_ts=at(minutes=9))
    second = on_prints(
        **limit, entry_decision=LATER, entry_ts=at(1, 5, LATER), exit_ts=at(3, 10, LATER)
    )

    classified = classify(trades(first, second), trades(first, second), trades(held), TICK)

    assert only_row(classified)["outcome"] == FidelityClass.ENTRY_BAR_PATH
    row = only_row(classified, LATER)
    assert outcomes(row) == (FidelityClass.CASCADE,) * 3
    assert row["note"] == "a trade on prints alone, the 1-minute run in a position at its decision"


@pytest.mark.parametrize("kind", ["market", "limit"])
def test_a_trade_on_prints_alone_with_the_1_minute_run_flat_is_unknown(kind: str) -> None:
    # The restamped replay makes the trade as the prints do, so the decision second does not
    # explain it, and nothing kept the 1-minute run from entering. The replay's trades carry no
    # level, which the runs on bars give, so only the fills count.
    level = None if kind == "market" else PRICE
    ticks = trades(on_prints(entry_kind=kind, entry_level=level))
    restamped = trades(on_prints(entry_kind=kind))

    row = only_row(classify(ticks, restamped, trades(), TICK))

    assert row["outcome"] == FidelityClass.UNKNOWN


def test_a_market_entrys_exits_in_different_bars_are_unknown() -> None:
    later = on_bars(exit_ts=at(minutes=6))

    row = only_row(classify(trades(on_prints()), trades(on_prints()), trades(later), TICK))

    assert outcomes(row) == (MATCH, FidelityClass.UNKNOWN, FidelityClass.UNKNOWN)


def test_two_trades_of_one_decision_and_side_are_refused() -> None:
    with pytest.raises(ValueError, match="Expected one trade per decision and side, got two"):
        classify(trades(on_prints(), on_prints()), trades(), trades(), TICK)


def test_trades_without_the_classifiers_columns_are_refused() -> None:
    with pytest.raises(ValueError, match="Expected the columns of TRADE_COLUMNS"):
        classify(trades(on_prints()).drop("exit_ambiguous"), trades(), trades(), TICK)


def test_the_summary_counts_the_trades_and_the_fills_by_class() -> None:
    moved = on_prints(entry_ts=at(seconds=1), entry_price=PRICE + TICK)
    alone = on_prints(entry_decision=LATER, entry_kind="limit", entry_ts=LATER)
    ticks = trades(moved, alone)
    restamped = trades(on_prints(entry_ts=DECISION))

    summary = summarise(classify(ticks, restamped, trades(on_bars()), TICK))

    assert (summary.tick_trades, summary.minute_trades, summary.matched) == (2, 1, 1)
    assert (summary.exact, summary.exits_alike) == (0, 1)
    assert (summary.fills_compared, summary.equal_fills) == (2, 1)
    assert summary.trades_by_class == {"bar_boundary": 2}
    assert summary.fills_by_class == {"bar_boundary": 3}
    assert summary.unknown == 0
