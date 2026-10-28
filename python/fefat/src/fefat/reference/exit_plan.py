"""Exit plans in the reference engine (`docs/spec/fill-semantics.md` §21 to §24, step 2.8): the
stop, the targets, the breakeven, and the trailing stop an entry carries (`ExitPlan`), placed when
it fills (`place_exit_plan`), and what follows from them while its position is open (`LivePlan`):
the legs share the open lots, and the stop moves only in the position's favour, at each price the
engine marks and at each decision. Each rule is a small function named after its identifier, as
in `fefat.reference.engine`, and every distance is worked out exactly before it is rounded to the
tick (F-RND-01):

    plan = ExitPlan.in_ticks(stop_ticks=12, target_ticks=24)
    context.market(Side.BUY, 1, plan)
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from decimal import Decimal
from fractions import Fraction
from typing import Any

from fefat.reference.orders import Book, OrderKind, OrderRole, OrderState, Side, WorkingOrder
from fefat.reference.units import instant_text

TARGET_ROLES = (OrderRole.TARGET_1, OrderRole.TARGET_2, OrderRole.TARGET_3)


def exact(number: float) -> Fraction:
    """A number of a specification or a signal frame as the decimal it prints as (F-RND-01)."""
    return Fraction(Decimal(repr(number)))


@dataclass(frozen=True, slots=True)
class TicksAway:
    """A leg `ticks` ticks from its entry's fill: below a long's fill for its stop, above it for
    a target."""

    ticks: int


@dataclass(frozen=True, slots=True)
class AtPrice:
    """A leg at a price of the signal frame, or of an order scenario, wherever the entry fills."""

    price: int


@dataclass(frozen=True, slots=True)
class PercentAway:
    """A stop `percent` % of its entry's fill price from it."""

    percent: Fraction


@dataclass(frozen=True, slots=True)
class RiskMultiple:
    """A target `multiple` times its plan's initial risk from the fill (F-RND-02)."""

    multiple: Fraction


LegPrice = TicksAway | AtPrice | PercentAway | RiskMultiple


@dataclass(frozen=True, slots=True)
class PlannedLeg:
    """A leg of a plan: where it lies, the order id an order scenario gives it, and, for a target,
    the fraction of the lots its earlier targets leave that it closes."""

    price: LegPrice
    order_id: int | None = None
    fraction: Fraction = Fraction(1)


@dataclass(frozen=True, slots=True)
class TicksTrigger:
    """A profit of `ticks` ticks from the fill."""

    ticks: int


@dataclass(frozen=True, slots=True)
class RiskTrigger:
    """A profit of `multiple` times the initial risk."""

    multiple: Fraction


@dataclass(frozen=True, slots=True)
class TargetTrigger:
    """The fill of target `target`, counted from 1."""

    target: int


Trigger = TicksTrigger | RiskTrigger | TargetTrigger


@dataclass(frozen=True, slots=True)
class BreakevenPlan:
    """Breakeven: when `trigger` fires, the stop moves to the fill price plus `offset_ticks`."""

    trigger: Trigger
    offset_ticks: int


@dataclass(frozen=True, slots=True)
class TrailingPlan:
    """A trailing stop: `ticks` behind the best price, its distance at the entry row, none for a
    trailing stop by the column; `multiple` of `feature`, where each decision takes it again;
    whole steps of `step_ticks`; its `activation`; and whether it moves at every price marked."""

    ticks: int | None
    multiple: Fraction | None
    feature: str | None
    step_ticks: int | None
    activation: Trigger | None
    intrabar: bool


@dataclass(frozen=True, slots=True)
class ExitPlan:
    """What an entry carries, placed when it fills (F-PLN-01)."""

    stop: PlannedLeg | None
    targets: tuple[PlannedLeg, ...] = ()
    breakeven: BreakevenPlan | None = None
    trailing: TrailingPlan | None = None

    @classmethod
    def in_ticks(cls, stop_ticks: int, target_ticks: int) -> "ExitPlan":
        """A stop and one target for the whole position, each a number of ticks from the fill:
        the bracket of a strategy protocol's `market` order."""
        return cls(PlannedLeg(TicksAway(stop_ticks)), (PlannedLeg(TicksAway(target_ticks)),))


@dataclass(frozen=True, slots=True)
class Move:
    """A stop moved by its plan, from `before` to `after`, under `rule`."""

    order: int
    before: int
    after: int
    rule: str


@dataclass(frozen=True, slots=True)
class LegFill:
    """What a leg's fill does to its plan (F-PLN-02): the legs it cancels, and the stop it
    reduces with the lots left, if any."""

    cancelled: tuple[WorkingOrder, ...] = ()
    reduced: tuple[int, int] | None = None


# §21 Rounding
def f_rnd_01(distance: Fraction, tick: int, away_from_entry: bool) -> int:
    """A distance worked out exactly, as whole ticks, at least one: rounded down for a stop and a
    trailing stop's distance, so that no stop lies farther away than asked, and up for a target
    and a profit trigger, so that no target lies nearer than asked."""
    ticks = distance / tick
    return max(1, math.ceil(ticks) if away_from_entry else math.floor(ticks))


def f_rnd_02(side: Side, fill: int, stop: int, tick: int) -> int:
    """A plan's initial risk: the ticks from its entry's fill price to its stop's first level,
    at least one."""
    return max(1, side.sign() * (fill - stop) // tick)


def feature_units(row: Mapping[str, Any], feature: str) -> int:
    """The feature's value on `row`, in 1e-9 units of price as one worked out from the bars'
    prices is, read as the decimal it prints as and cut to whole units (F-RND-01); a feature
    missing, or at or below zero, is refused."""
    value = row.get(feature)
    if value is None or not value > 0:
        at = instant_text(row["ts_close"])
        raise ValueError(
            f"Expected the feature {feature} above zero on the signal row closing at {at}, got "
            f"{value}."
        )
    return int(Decimal(repr(value)))


def feature_ticks(multiple: Fraction, units: int, tick: int, away_from_entry: bool) -> int:
    """`multiple` times a feature of `units` 1e-9 units, in whole ticks (F-RND-01)."""
    return f_rnd_01(multiple * units, tick, away_from_entry)


# §22 Exit plans
def f_pln_01(lots: int, fractions: Sequence[Fraction]) -> list[int]:
    """Each target's lots: its fraction of the lots its earlier targets leave, rounded down to
    whole lots; a target of no lots is not placed."""
    left, shares = lots, []
    for fraction in fractions:
        share = math.floor(fraction * left)
        shares.append(share)
        left -= share
    return shares


def f_pln_02(book: Book, filled: WorkingOrder) -> LegFill:
    """A leg's fill works out its plan's open lots: the stop's fill cancels the targets; a
    target's cancels the rest when no lots stay open, a stop triggered on TBBO among them, and
    otherwise reduces the stop, where the plan has one, to the lots left."""
    live = None if filled.leg_of is None else book.plans.get(filled.leg_of)
    if live is None:
        return LegFill()
    if filled.id != live.stop:
        live.open_lots -= filled.lots
        live.filled_targets.add(live.targets[filled.id])
    stop = book.live_order(live.stop)
    if filled.id != live.stop and live.open_lots > 0:
        if stop is None:
            return LegFill()
        stop.lots = live.open_lots
        return LegFill(reduced=(stop.id, stop.lots))
    legs = tuple(order for order in book.live() if order.leg_of == live.entry)
    for order in legs:
        book.close(order, OrderState.CANCELLED)
    return LegFill(cancelled=legs)


def f_pln_03(side: Side, stop: int, proposed: int, market: int, tick: int) -> int | None:
    """A move of a long's stop: up only, and never to or above the market, one tick below it at
    most; none when it would not raise the stop."""
    ceiling = side.opposite().moved(market, 1, tick)
    level = min(proposed, ceiling) if side is Side.BUY else max(proposed, ceiling)
    raised = level > stop if side is Side.BUY else level < stop
    return level if raised else None


def f_pln_04(book: Book, price: int, tick: int) -> list[Move]:
    """At each price marked, once the fills at it are done, each plan follows it: its best
    price, its triggers, and the moves of its breakeven and its trailing stop."""
    return [move for live in book.plans_in_order() for move in live.at_price(book, price, tick)]


def f_pln_05(live: "LivePlan", low: int, high: int, tick: int) -> bool:
    """Whether a bar from `low` to `high` leaves a plan as a replay of it would: it rises no
    higher than the best price of a plan with a trailing stop, and reaches no profit trigger
    still waiting (the skipping replay's condition, which the reference engine never needs)."""
    beyond = high if live.side is Side.BUY else low
    if live.plan.trailing is not None and live.side.better(beyond, live.best) != live.best:
        return False
    levels = [live.trigger_level(trigger, tick) for trigger in live.waiting_triggers()]
    return not any(
        level is not None and live.side.better(beyond, level) == beyond for level in levels
    )


# §23 Breakeven
def f_brk_01(side: Side, fill: int, offset_ticks: int, tick: int) -> int:
    """Breakeven's level: the entry's fill price plus `offset_ticks` ticks in the position's
    favour, below it for a negative offset."""
    return fill + side.sign() * offset_ticks * tick


def f_brk_02(live: "LivePlan", trigger: Trigger, tick: int) -> bool:
    """A profit trigger fires once a price marked reaches the fill plus its distance; an
    `after_target` trigger once that target has filled, never for a target not placed."""
    if isinstance(trigger, TargetTrigger):
        return trigger.target in live.filled_targets
    level = live.trigger_level(trigger, tick)
    return level is not None and live.side.better(live.best, level) == live.best


# §24 Trailing stops
def f_trl_01(live: "LivePlan", tick: int) -> int | None:
    """A working trailing stop's level: the best price less its distance, none for one by the
    column, which moves at decisions to its row's `trail_ref` (F-TRL-02)."""
    if live.distance is None:
        return None
    return live.side.opposite().moved(live.best, live.distance, tick)


def f_trl_02(trailing: TrailingPlan, row: Mapping[str, Any], tick: int) -> int | None:
    """The distance a decision's row gives a trailing stop by a feature, rounded down; none
    where the row leaves the feature out, or for a trailing stop in ticks or by the column."""
    if trailing.feature is None or trailing.multiple is None or row.get(trailing.feature) is None:
        return None
    return feature_ticks(trailing.multiple, feature_units(row, trailing.feature), tick, False)


def f_trl_03(side: Side, stop: int, level: int, step_ticks: int | None, tick: int) -> int:
    """With steps, the stop raised by the whole steps of `step_ticks` ticks that fit between where
    it stands and `level`; without, `level` itself."""
    if step_ticks is None:
        return level
    step = step_ticks * tick
    steps = side.sign() * (level - stop) // step
    return stop + side.sign() * max(steps, 0) * step


def f_trl_04(trailing: TrailingPlan, at_decision: bool) -> bool:
    """Whether a trailing stop moves now: `intrabar` at every price marked and at decisions,
    `bar_close` at decisions alone."""
    return at_decision or trailing.intrabar


@dataclass(slots=True)
class LivePlan:
    """An entry's plan once it has filled: the entry's side, fill price, and lots still open; its
    initial risk; its stop's id and its targets' numbers by id; the best price marked since the
    fill; the targets filled; whether its breakeven has fired and its trailing stop works; and
    the trailing stop's distance in ticks, none for one by the column."""

    plan: ExitPlan
    entry: int
    side: Side
    fill: int
    open_lots: int
    risk: int | None
    stop: int | None
    targets: dict[int, int]
    best: int
    distance: int | None
    breakeven_fired: bool = False
    trailing_active: bool = False
    filled_targets: set[int] = field(default_factory=set)

    def copied(self) -> "LivePlan":
        return replace(self, targets=dict(self.targets), filled_targets=set(self.filled_targets))

    def trigger_level(self, trigger: Trigger, tick: int) -> int | None:
        """The price a profit trigger fires at, rounded away from the fill (F-RND-01); none for
        one after a target, or in R without an initial risk."""
        if isinstance(trigger, TicksTrigger):
            return self.side.moved(self.fill, trigger.ticks, tick)
        if isinstance(trigger, RiskTrigger) and self.risk is not None:
            ticks = f_rnd_01(trigger.multiple * self.risk * tick, tick, True)
            return self.side.moved(self.fill, ticks, tick)
        return None

    def waiting_triggers(self) -> list[Trigger]:
        """The profit triggers that have not fired yet."""
        breakeven, trailing = self.plan.breakeven, self.plan.trailing
        waiting = []
        if breakeven is not None and not self.breakeven_fired:
            waiting.append(breakeven.trigger)
        if trailing is not None and trailing.activation is not None and not self.trailing_active:
            waiting.append(trailing.activation)
        return waiting

    def at_price(self, book: Book, price: int, tick: int) -> list[Move]:
        """A price marked (F-PLN-04): the best price follows it, waiting triggers may fire, and
        breakeven and an intrabar trailing stop may move the stop."""
        self.best = self.side.better(self.best, price)
        proposed: list[tuple[int, str]] = []
        breakeven, trailing = self.plan.breakeven, self.plan.trailing
        fires = breakeven is not None and not self.breakeven_fired
        if breakeven is not None and fires and f_brk_02(self, breakeven.trigger, tick):
            self.breakeven_fired = True
            level = f_brk_01(self.side, self.fill, breakeven.offset_ticks, tick)
            proposed.append((level, "F-BRK-01"))
        if trailing is not None and not self.trailing_active and trailing.activation is not None:
            self.trailing_active = f_brk_02(self, trailing.activation, tick)
        if trailing is not None and self.trailing_active and f_trl_04(trailing, False):
            level = f_trl_01(self, tick)
            if level is not None:
                proposed.append((level, "F-TRL-01"))
        return self._moved(book, proposed, price, tick)

    def at_decision(
        self, book: Book, row: Mapping[str, Any], mark: int | None, tick: int
    ) -> list[Move]:
        """A decision (F-PLN-04): a trailing stop by a feature takes the row's distance, and a
        working trailing stop moves from the best price so far, or to the row's `trail_ref`."""
        trailing = self.plan.trailing
        if trailing is None or mark is None:
            return []
        distance = f_trl_02(trailing, row, tick)
        if distance is not None:
            self.distance = distance
        if not (self.trailing_active and f_trl_04(trailing, True)):
            return []
        level = f_trl_01(self, tick) if trailing.ticks is not None else row.get("trail_ref")
        if level is None:
            return []
        if trailing.ticks is None and level % tick:
            raise ValueError(
                f"Expected trail_ref on the instrument's tick, got {level} on the signal row "
                f"closing at {instant_text(row['ts_close'])}."
            )
        return self._moved(book, [(level, "F-TRL-01")], mark, tick)

    def _moved(
        self, book: Book, proposed: list[tuple[int, str]], market: int, tick: int
    ) -> list[Move]:
        """The stop raised to the highest level proposed, in whole steps for the trailing stop's
        (F-TRL-03), as F-PLN-03 moves it; a stop triggered on TBBO stays (F-STP-02)."""
        stop = book.live_order(self.stop)
        if stop is None or stop.state is OrderState.TRIGGERED or not proposed:
            return []
        current, ceiling = stop.level(), self.side.opposite().moved(market, 1, tick)
        steps = None if self.plan.trailing is None else self.plan.trailing.step_ticks
        levels = [
            (f_trl_03(self.side, current, self._capped(level, ceiling), steps, tick), rule)
            if rule == "F-TRL-01"
            else (level, rule)
            for level, rule in proposed
        ]
        level, rule = max(levels, key=lambda proposal: self.side.sign() * proposal[0])
        moved = f_pln_03(self.side, current, level, market, tick)
        if moved is None:
            return []
        stop.price = moved
        return [Move(stop.id, current, moved, rule)]

    def _capped(self, level: int, ceiling: int) -> int:
        return min(level, ceiling) if self.side is Side.BUY else max(level, ceiling)


def place_exit_plan(
    book: Book, entry: WorkingOrder, fill: int, market: int, ts: int, index: int, tick: int
) -> list[WorkingOrder]:
    """An entry's plan, placed when it fills at `fill` with the market at `market` (F-PLN-01,
    F-OCO-02): its stop for all its lots, raised at once by a trailing stop working from the fill
    (F-PLN-04), then its targets, each with its share of the lots; a target of no lots is not
    placed. The legs work from the fill, without latency."""
    plan = entry.plan
    if plan is None:
        return []
    side, trailing = entry.side, plan.trailing
    stop = None if plan.stop is None else stop_level(plan.stop.price, side, fill, tick)
    risk = None if stop is None else f_rnd_02(side, fill, stop, tick)
    if stop is not None and trailing is not None:
        stop = _raised_at_the_fill(trailing, side, stop, market, tick)
    legs: list[WorkingOrder] = []
    if plan.stop is not None and stop is not None:
        stop_id = plan.stop.order_id or book.new_id()
        legs.append(
            _leg(entry, stop_id, OrderKind.STOP, stop, entry.lots, OrderRole.STOP, ts, index)
        )
    shares = f_pln_01(entry.lots, [target.fraction for target in plan.targets])
    targets: dict[int, int] = {}
    for number, (target, share) in enumerate(zip(plan.targets, shares, strict=True), start=1):
        if share == 0:
            continue
        level = _target_level(target.price, side, fill, risk, tick)
        target_id = target.order_id or book.new_id()
        role = TARGET_ROLES[number - 1]
        legs.append(_leg(entry, target_id, OrderKind.LIMIT, level, share, role, ts, index))
        targets[target_id] = number
    if not legs:
        return []
    book.orders.extend(legs)
    active = trailing is not None and trailing.activation is None
    book.plans[entry.id] = LivePlan(
        plan=plan,
        entry=entry.id,
        side=side,
        fill=fill,
        open_lots=entry.lots,
        risk=risk,
        stop=legs[0].id if plan.stop is not None else None,
        targets=targets,
        best=market,
        distance=None if trailing is None else trailing.ticks,
        trailing_active=active,
    )
    return legs


def _raised_at_the_fill(
    trailing: TrailingPlan, side: Side, stop: int, market: int, tick: int
) -> int:
    """A stop's first level, raised at once by an intrabar trailing stop that works from the
    fill, as it would at a price marked (F-PLN-04, F-TRL-03)."""
    if trailing.activation is not None or not trailing.intrabar or trailing.ticks is None:
        return stop
    level = side.opposite().moved(market, trailing.ticks, tick)
    return side.better(stop, f_trl_03(side, stop, level, trailing.step_ticks, tick))


def stop_level(price: LegPrice, side: Side, fill: int, tick: int) -> int:
    """A stop below a long's fill: in ticks, a percentage of the fill price rounded down to the
    tick (F-RND-01), or at a price."""
    if isinstance(price, AtPrice):
        return price.price
    if isinstance(price, PercentAway):
        ticks = f_rnd_01(abs(fill) * price.percent / 100, tick, False)
        return side.opposite().moved(fill, ticks, tick)
    if isinstance(price, TicksAway):
        return side.opposite().moved(fill, price.ticks, tick)
    raise ValueError(f"Expected a stop in ticks, in percent, or at a price, got {price}.")


def _target_level(price: LegPrice, side: Side, fill: int, risk: int | None, tick: int) -> int:
    """A target above a long's fill: in ticks, an R multiple of the initial risk rounded up
    (F-RND-01, F-RND-02), or at a price."""
    if isinstance(price, AtPrice):
        return price.price
    if isinstance(price, TicksAway):
        return side.moved(fill, price.ticks, tick)
    if isinstance(price, RiskMultiple) and risk is not None:
        return side.moved(fill, f_rnd_01(price.multiple * risk * tick, tick, True), tick)
    raise ValueError(f"Expected a target in ticks, in R beside a stop, or at a price, got {price}.")


def _leg(
    entry: WorkingOrder,
    order_id: int,
    kind: OrderKind,
    price: int,
    lots: int,
    role: OrderRole,
    ts: int,
    index: int,
) -> WorkingOrder:
    """A leg of `entry`'s plan, against its side, active at its fill (F-OCO-02)."""
    return WorkingOrder(
        id=order_id,
        side=entry.side.opposite(),
        kind=kind,
        price=price,
        lots=lots,
        role=role,
        placed_at=ts,
        activation=ts,
        seen_after=index,
        leg_of=entry.id,
    )
