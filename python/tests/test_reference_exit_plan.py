"""Step 2.8's exit plans in the reference engine, rule by rule (`fefat.reference.exit_plan`): the
rounding of computed distances, the targets' shares of the lots, a stop moved only in the
position's favour and never through the market, for a long and a short alike, whole steps, and
the condition under which a skipping replay may pass over a bar (F-PLN-05)."""

from fractions import Fraction

import pytest

from fefat.reference.exit_plan import (
    ExitPlan,
    LivePlan,
    PlannedLeg,
    TicksAway,
    TicksTrigger,
    TrailingPlan,
    f_pln_01,
    f_pln_03,
    f_pln_05,
    f_rnd_01,
    f_trl_03,
    place_exit_plan,
)
from fefat.reference.orders import Book, OrderKind, OrderRole, Side, WorkingOrder

TICK = 250_000_000
"""ES's tick, 0.25, in 1e-9 units."""


def price(points: str) -> int:
    return int(Fraction(points) * 1_000_000_000)


@pytest.mark.parametrize(
    ("distance", "away_from_entry", "ticks"),
    [
        (Fraction(3_500_175, 1_000_000) * 1_000_000_000, False, 14),
        (Fraction(26, 10) * 1_000_000_000, True, 11),
        (Fraction(195, 100) * 1_000_000_000, False, 7),
        (Fraction(3, 10) * TICK, False, 1),
        (Fraction(3, 10) * TICK, True, 1),
        (Fraction(4) * TICK, True, 4),
    ],
)
def test_a_distance_rounds_toward_the_entry_for_stops_and_away_for_targets(
    distance: Fraction, away_from_entry: bool, ticks: int
) -> None:
    # F-RND-01: S-template-015's 14.0007 ticks, S-template-014's 10.4 and 7.8, and at least one.
    assert f_rnd_01(distance, TICK, away_from_entry) == ticks


@pytest.mark.parametrize(
    ("lots", "fractions", "shares"),
    [
        (3, ["0.5", "0.5", "1"], [1, 1, 1]),
        (1, ["0.5", "1"], [0, 1]),
        (2, ["0.5", "1"], [1, 1]),
        (10, ["0.25", "0.5", "0.75"], [2, 4, 3]),
    ],
)
def test_each_target_closes_its_fraction_of_the_lots_left_rounded_down(
    lots: int, fractions: list[str], shares: list[int]
) -> None:
    # F-PLN-01: 10 lots: 2.5 -> 2, then 0.5 of 8 = 4, then 0.75 of 4 = 3, leaving 1 lot.
    assert f_pln_01(lots, [Fraction(fraction) for fraction in fractions]) == shares


@pytest.mark.parametrize(
    ("side", "stop", "proposed", "market", "moved"),
    [
        (Side.BUY, "4998.25", "5000.25", "5001.25", "5000.25"),
        (Side.BUY, "4998.25", "5001.25", "5001.25", "5001.00"),
        (Side.BUY, "5000.25", "4999.75", "5001.25", None),
        (Side.BUY, "5001.00", "5001.25", "5001.25", None),
        (Side.SELL, "5001.75", "4999.75", "4998.75", "4999.75"),
        (Side.SELL, "5001.75", "4998.75", "4998.75", "4999.00"),
        (Side.SELL, "4999.75", "5000.25", "4998.75", None),
    ],
)
def test_a_stop_moves_only_in_the_positions_favour_and_never_through_the_market(
    side: Side, stop: str, proposed: str, market: str, moved: str | None
) -> None:
    # F-PLN-03: a long's stop rises, at most to a tick below the market; a short's falls, at
    # most to a tick above it; a move the other way leaves it.
    expected = None if moved is None else price(moved)
    assert f_pln_03(side, price(stop), price(proposed), price(market), TICK) == expected


@pytest.mark.parametrize(
    ("side", "stop", "level", "moved"),
    [
        (Side.BUY, "4998.75", "4999.50", "4999.25"),
        (Side.BUY, "5000.25", "5000.50", "5000.25"),
        (Side.BUY, "5000.25", "5001.25", "5001.25"),
        (Side.SELL, "5001.25", "5000.50", "5000.75"),
        (Side.SELL, "5001.25", "5001.50", "5001.25"),
    ],
)
def test_a_trailing_stop_moves_by_whole_steps(
    side: Side, stop: str, level: str, moved: str
) -> None:
    # F-TRL-03, in steps of 2 ticks (0.50): S-template-025's moves, and a short's mirror.
    assert f_trl_03(side, price(stop), price(level), 2, TICK) == price(moved)


def live_long(trailing: TrailingPlan | None) -> LivePlan:
    """A long of 1 lot filled at 5000.25 with the market at 5000.00, a stop 8 ticks under the
    fill, and `trailing`, its plan placed in a book of its own."""
    book = Book(position=1)
    plan = ExitPlan(PlannedLeg(TicksAway(8)), (), None, trailing)
    entry = WorkingOrder(
        id=book.new_id(),
        side=Side.BUY,
        kind=OrderKind.MARKET,
        price=None,
        lots=1,
        role=OrderRole.ENTRY,
        placed_at=0,
        activation=0,
        seen_after=0,
        plan=plan,
    )
    place_exit_plan(book, entry, price("5000.25"), price("5000.00"), 0, 0, TICK)
    return book.plans[entry.id]


def test_a_bar_is_skipped_only_where_no_plan_could_move_in_it() -> None:
    # F-PLN-05: a trailing stop follows a new best price, so a bar above the best price so far,
    # 5000.00, must be replayed; one that only reaches it need not be.
    trailing = TrailingPlan(4, None, None, None, None, True)
    following = live_long(trailing)
    assert f_pln_05(following, price("4999.75"), price("5000.00"), TICK)
    assert not f_pln_05(following, price("4999.75"), price("5000.25"), TICK)

    # A trailing stop waiting for its activation at 5000.25 + 8 ticks = 5002.25 must be replayed
    # where a bar reaches that level, and so must the best price it follows meanwhile.
    waiting = live_long(TrailingPlan(4, None, None, None, TicksTrigger(8), True))
    assert not f_pln_05(waiting, price("4999.75"), price("5002.25"), TICK)

    # Without breakeven or a trailing stop nothing moves: any bar may be passed over.
    still = live_long(None)
    assert f_pln_05(still, price("4990.00"), price("5010.00"), TICK)
