"""Why a run's fills on trade prints differ from its fills on 1-minute bars (step 2.16,
`02-engine-and-data.md` §8, D-67, D-69). The trades of a run on prints and of its run on the
1-minute bars of the same prints, bars equal to the prints' own, are matched by the decision that
entered them and their side, as `fefat.backtest.fidelity` matches a rerun's, and each fill that
differs gets a class with a third run: the reference engine's replay of the same prints with
each print stamped at a decision's instant moved one nanosecond after it, where the 1-minute
bars put it (`restamped`).

A fill or a trade of one run alone that the restamped replay makes otherwise than the prints is
`bar_boundary`: the prints of a decision's second alone moved it, directly or through an earlier
trade of the day. A fill the restamped replay makes as the prints do differs between those prints
and their 1-minute bars, and a class names where FEFAT's path through a bar parts from the prints,
held to what the trades show: `bar_path`, `entry_bar_path`, or `stop_through`; a trade of one run
alone that the replay makes as the prints do, made while the other run held a position, is a
`cascade` of such a difference; anything else is `unknown`. A fill on prints and a fill on a bar
are alike at one price inside the bar's minute, the bar's fills being stamped at its close
(F-BAR-06). The restamped replay is read at its own instants, at which it held its positions, a
fill of it on a moved print one nanosecond after that print's stamp being the prints' own fill;
`classify(restamped, restamped, minutes, tick)` compares the replay with the bars alone.

Prices are int64 in 1e-9 units and instants int64 nanoseconds UTC (ADR-0019). The trades of a few
sessions are a few hundred rows, so they are read as plain Python objects."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

import polars as pl

from fefat.reference.orders import OrderKind, OrderRole, PositionSide
from fefat.reference.units import instant_text

MINUTE = 60_000_000_000
"""One minute in nanoseconds, the bars' timeframe."""
RESTAMP = 1
"""How far after a decision's instant the restamped replay moves a print stamped at it, in
nanoseconds."""


class FidelityClass(StrEnum):
    """How a fill on prints compares with the same order's fill on 1-minute bars: alike, or
    apart for the reason its class names; the tick check's report documents each with its rules."""

    MATCH = "match"
    """Alike on prints and on bars: a fill, or a trade whose two fills are."""

    BAR_BOUNDARY = "bar_boundary"
    """Moved by the prints stamped in a decision's second: on prints they come before the decision
    (F-CLK-02), on bars they open the bar that starts at it (F-ACT-02)."""

    BAR_PATH = "bar_path"
    """A bar held through reached both legs: the bar's path filled the stop, the adverse extreme
    first, flagged ambiguous (F-BAR-02, F-BAR-04, F-BAR-05); the prints reached the target first."""

    ENTRY_BAR_PATH = "entry_bar_path"
    """The rest of a limit or stop entry's bar: the bar's path after the fill (F-BAR-03, F-BAR-04)
    and the prints after it part, one filling a leg in the entry's minute where the other carries
    the position out of it."""

    STOP_THROUGH = "stop_through"
    """A stop triggered by a print past its level fills at that print on prints (F-STP-03) and at
    its level on the bar's path (F-STP-04)."""

    CASCADE = "cascade"
    """A trade of one run alone, made as the restamped replay makes it, while the other run still
    held a position at its decision after an earlier difference of the bar's path that day."""

    UNKNOWN = "unknown"
    """A difference nothing above explains; the tick check fails with one."""


MATCH = FidelityClass.MATCH

TRADE_COLUMNS = pl.Schema(
    {
        "entry_decision": pl.Int64,
        "side": pl.String,
        "entry_kind": pl.String,
        "entry_ts": pl.Int64,
        "entry_price": pl.Int64,
        "entry_level": pl.Int64,
        "exit_ts": pl.Int64,
        "exit_price": pl.Int64,
        "exit_reason": pl.String,
        "exit_ambiguous": pl.Boolean,
        "stop_price": pl.Int64,
        "target_price": pl.Int64,
    }
)
"""One run's trades as the classes read them: the decision that entered, `long` or `short`, the
entry's kind (`market`, `limit`, `stop`), its fill and a limit's or a stop's level, the exit's
fill, its reason as the run writes it (`stop`, `target_1`, `flat_by`) and whether the bar that
filled it was ambiguous (F-BAR-05), and the bracket's levels."""
CLASSIFIED_COLUMNS = pl.Schema(
    {
        "entry_decision": pl.Int64,
        "side": pl.String,
        "entry_kind": pl.String,
        "in_ticks": pl.Boolean,
        "in_minutes": pl.Boolean,
        "entry_outcome": pl.String,
        "exit_outcome": pl.String,
        "outcome": pl.String,
        "entry_ticks": pl.Int64,
        "exit_ticks": pl.Int64,
        "note": pl.String,
    }
)
"""One row per trade of either run: the outcome of its entry fill and of its exit fill, each a
`FidelityClass`, the trade's (`unknown` when either fill is, else the entry's when it differs,
else the exit's), the fills on prints less those on bars in ticks, and a note without prices."""


class _Leg(StrEnum):
    ENTRY = "entry"
    EXIT = "exit"


@dataclass(frozen=True)
class _Fill:
    ts: int
    price: int
    role: OrderRole

    def alike_on_a_bar(self, on_a_bar: "_Fill") -> bool:
        """Whether this fill on prints is the fill on a bar: one price and role, inside the
        minute of the bar that closes at the bar fill's instant."""
        same = (self.price, self.role) == (on_a_bar.price, on_a_bar.role)
        return same and _inside_the_bar(self.ts, on_a_bar.ts)

    def on_the_same_print(self, restamped: "_Fill") -> bool:
        """Whether the restamped replay's fill is this fill on prints: one price and role, on
        the same print, at its stamp or moved `RESTAMP` after it."""
        same = (self.price, self.role) == (restamped.price, restamped.role)
        return same and 0 <= restamped.ts - self.ts <= RESTAMP


def _inside_the_bar(instant: int, bar_close: int) -> bool:
    """Whether an instant lies in the 1-minute bar closing at `bar_close` (F-BAR-06)."""
    return bar_close - MINUTE <= instant < bar_close


def _past(price: int, level: int, *, upward: bool) -> bool:
    """Whether a price lies beyond a level: above it upward, below it downward."""
    return price > level if upward else price < level


@dataclass(frozen=True)
class _Trade:
    entry_decision: int
    side: PositionSide
    kind: OrderKind
    entry: _Fill
    entry_level: int | None
    exit: _Fill
    exit_ambiguous: bool
    stop: int
    target: int

    @classmethod
    def of_row(cls, row: Mapping[str, object]) -> "_Trade":
        def integer(name: str) -> int:
            value = row[name]
            if not isinstance(value, int):
                raise ValueError(f"Expected an integer {name}, got {value!r} in {dict(row)}.")
            return value

        level = row["entry_level"]
        exit_role = OrderRole(str(row["exit_reason"]))
        return cls(
            entry_decision=integer("entry_decision"),
            side=PositionSide(str(row["side"])),
            kind=OrderKind(str(row["entry_kind"])),
            entry=_Fill(integer("entry_ts"), integer("entry_price"), OrderRole.ENTRY),
            entry_level=level if isinstance(level, int) else None,
            exit=_Fill(integer("exit_ts"), integer("exit_price"), exit_role),
            exit_ambiguous=bool(row["exit_ambiguous"]),
            stop=integer("stop_price"),
            target=integer("target_price"),
        )

    @property
    def long(self) -> bool:
        return self.side is PositionSide.LONG

    def fill(self, leg: _Leg) -> _Fill:
        return self.entry if leg is _Leg.ENTRY else self.exit

    def filled_as(self, restamped: "_Trade | None") -> bool:
        """Whether the restamped replay filled this trade's entry and exit on the same prints:
        the levels and the bar's flags are not fills, and the replay gives neither."""
        if restamped is None:
            return False
        entered = self.entry.on_the_same_print(restamped.entry)
        return entered and self.exit.on_the_same_print(restamped.exit)

    def holds_at(self, decision: int) -> bool:
        """Whether the position was open at a decision: entered by then and left after it, the
        fills at the decision's own instant coming before it (F-CLK-02, F-BAR-06)."""
        return self.entry.ts <= decision < self.exit.ts


type _Key = tuple[int, str]


def classify(
    ticks: pl.DataFrame, restamped: pl.DataFrame, minutes: pl.DataFrame, tick: int
) -> pl.DataFrame:
    """The trades of the run on prints, of the restamped replay, and of the run on 1-minute
    bars, each with the columns of `TRADE_COLUMNS`, matched and classified (module docstring),
    one row of `CLASSIFIED_COLUMNS` per trade of the run on prints or on bars; `tick` is the
    instrument's in 1e-9 units."""
    runs = _Runs(_trades_by_key(ticks), _trades_by_key(restamped), _trades_by_key(minutes))
    keys = sorted(set(runs.ticks) | set(runs.minutes))
    return pl.DataFrame([runs.classified(key, tick) for key in keys], schema=CLASSIFIED_COLUMNS)


def _trades_by_key(trades: pl.DataFrame) -> dict[_Key, _Trade]:
    if dict(trades.schema) != dict(TRADE_COLUMNS):
        raise ValueError(
            f"Expected the columns of TRADE_COLUMNS, {dict(TRADE_COLUMNS)}, got "
            f"{dict(trades.schema)}."
        )
    keyed: dict[_Key, _Trade] = {}
    for row in trades.iter_rows(named=True):
        trade = _Trade.of_row(row)
        key = (trade.entry_decision, str(trade.side))
        if key in keyed:
            raise ValueError(
                f"Expected one trade per decision and side, got two at "
                f"{instant_text(key[0])} {key[1]}."
            )
        keyed[key] = trade
    return keyed


@dataclass(frozen=True)
class _Runs:
    """The trades of the three runs by their decision and side."""

    ticks: dict[_Key, _Trade]
    restamped: dict[_Key, _Trade]
    minutes: dict[_Key, _Trade]

    def classified(self, key: _Key, tick: int) -> dict[str, object]:
        on_prints, on_bars = self.ticks.get(key), self.minutes.get(key)
        restamped = self.restamped.get(key)
        if on_prints is not None and on_bars is not None:
            return _pair(on_prints, restamped, on_bars, tick)
        if on_prints is not None:
            return self._on_prints_alone(on_prints, restamped)
        if on_bars is None:
            raise ValueError(f"Expected a trade at {instant_text(key[0])} {key[1]}, got none.")
        return self._on_bars_alone(on_bars, restamped)

    def _on_prints_alone(self, trade: _Trade, restamped: _Trade | None) -> dict[str, object]:
        """A trade on prints alone: a `bar_boundary` when the restamped replay does not make it
        as the prints do; else a cascade when the run on bars held a position at its decision."""
        made = trade.filled_as(restamped)
        held = _held(self.minutes, trade.entry_decision)
        replay = "makes it as the prints do" if made else "does not make it"
        note = (
            f"a trade on prints alone; the restamped replay {replay}, and the 1-minute run is "
            f"{_state(held)} at its decision"
        )
        return _alone_row(trade, _alone_outcome(moved=not made, held=held), note, on_prints=True)

    def _on_bars_alone(self, trade: _Trade, restamped: _Trade | None) -> dict[str, object]:
        """A trade on bars alone: a `bar_boundary` when the restamped replay makes it; else a
        cascade when the run on prints held a position at its decision."""
        made = restamped is not None
        held = _held(self.ticks, trade.entry_decision)
        replay = "makes it" if made else "does not make it either"
        note = (
            f"a trade on 1-minute bars alone; the restamped replay {replay}, and the run on "
            f"prints is {_state(held)} at its decision"
        )
        return _alone_row(trade, _alone_outcome(moved=made, held=held), note, on_prints=False)


def _held(trades: dict[_Key, _Trade], decision: int) -> bool:
    return any(trade.holds_at(decision) for trade in trades.values())


def _state(held: bool) -> str:
    return "in a position" if held else "flat"


def _alone_outcome(*, moved: bool, held: bool) -> FidelityClass:
    """The decision second when the restamped replay settles the trade otherwise than its run,
    a cascade when it does not and the other run held a position, else unknown."""
    if moved:
        return FidelityClass.BAR_BOUNDARY
    return FidelityClass.CASCADE if held else FidelityClass.UNKNOWN


def _alone_row(
    trade: _Trade, outcome: FidelityClass, note: str, *, on_prints: bool
) -> dict[str, object]:
    return {
        "entry_decision": trade.entry_decision,
        "side": str(trade.side),
        "entry_kind": str(trade.kind),
        "in_ticks": on_prints,
        "in_minutes": not on_prints,
        "entry_outcome": str(outcome),
        "exit_outcome": str(outcome),
        "outcome": str(outcome),
        "entry_ticks": None,
        "exit_ticks": None,
        "note": note,
    }


def _pair(
    on_prints: _Trade, restamped: _Trade | None, on_bars: _Trade, tick: int
) -> dict[str, object]:
    entry = _fill_outcome(on_prints, restamped, on_bars, _Leg.ENTRY)
    exit = _fill_outcome(on_prints, restamped, on_bars, _Leg.EXIT)
    reasons = f"{on_prints.exit.role} against {on_bars.exit.role}"
    return {
        "entry_decision": on_prints.entry_decision,
        "side": str(on_prints.side),
        "entry_kind": str(on_prints.kind),
        "in_ticks": True,
        "in_minutes": True,
        "entry_outcome": str(entry),
        "exit_outcome": str(exit),
        "outcome": str(_trade_outcome(entry, exit)),
        "entry_ticks": _ticks(on_prints.entry.price - on_bars.entry.price, tick),
        "exit_ticks": _ticks(on_prints.exit.price - on_bars.exit.price, tick),
        "note": f"entry {entry}; exit {reasons}: {exit}",
    }


def _fill_outcome(
    on_prints: _Trade, restamped: _Trade | None, on_bars: _Trade, leg: _Leg
) -> FidelityClass:
    """`match` when the fill on prints is the bar's; `bar_boundary` when the restamped replay
    fills it otherwise than the prints; else the class of the restamped fill against the bar's."""
    if on_prints.fill(leg).alike_on_a_bar(on_bars.fill(leg)):
        return FidelityClass.MATCH
    if restamped is None or not on_prints.fill(leg).on_the_same_print(restamped.fill(leg)):
        return FidelityClass.BAR_BOUNDARY
    apart = _entry_apart if leg is _Leg.ENTRY else _exit_apart
    return apart(restamped, on_bars)


def _entry_apart(on_prints: _Trade, on_bars: _Trade) -> FidelityClass:
    """An entry on prints apart from the bar's: a stop entry the bar's path fills at its level and
    the prints at the print past it that triggered it, in the same minute."""
    level = on_bars.entry_level
    through = (
        on_bars.kind is OrderKind.STOP
        and level is not None
        and on_bars.entry.price == level
        and _inside_the_bar(on_prints.entry.ts, on_bars.entry.ts)
        and _past(on_prints.entry.price, level, upward=on_bars.long)
    )
    return FidelityClass.STOP_THROUGH if through else FidelityClass.UNKNOWN


def _exit_apart(on_prints: _Trade, on_bars: _Trade) -> FidelityClass:
    """An exit on prints apart from the bar's, both trades entered alike: a stop through a
    print, the rest of a resting entry's bar, or both legs in one ambiguous bar."""
    printed, barred = on_prints.exit, on_bars.exit
    same_bar = _inside_the_bar(printed.ts, barred.ts)
    if _stopped_through(on_prints, on_bars, same_bar=same_bar):
        return FidelityClass.STOP_THROUGH
    if _in_the_entry_bar(on_prints, on_bars):
        return FidelityClass.ENTRY_BAR_PATH
    both_legs = barred.role is OrderRole.STOP and printed.role is OrderRole.TARGET_1
    if same_bar and both_legs and on_bars.exit_ambiguous:
        return FidelityClass.BAR_PATH
    return FidelityClass.UNKNOWN


def _stopped_through(on_prints: _Trade, on_bars: _Trade, *, same_bar: bool) -> bool:
    """The stop leg filled at its level on the bar's path and past it on the prints."""
    stops = on_prints.exit.role is on_bars.exit.role is OrderRole.STOP
    at_level = on_bars.exit.price == on_bars.stop
    beyond = _past(on_prints.exit.price, on_bars.stop, upward=not on_bars.long)
    return stops and same_bar and at_level and beyond


def _in_the_entry_bar(on_prints: _Trade, on_bars: _Trade) -> bool:
    """A limit or stop entry filled in one minute by both, one of whose exits falls in it."""
    entry_bar = on_bars.entry.ts
    resting = on_bars.kind is not OrderKind.MARKET
    entered_alike = _inside_the_bar(on_prints.entry.ts, entry_bar)
    left_there = on_bars.exit.ts == entry_bar or _inside_the_bar(on_prints.exit.ts, entry_bar)
    return resting and entered_alike and left_there


def _trade_outcome(entry: FidelityClass, exit: FidelityClass) -> FidelityClass:
    """`unknown` when either fill is; otherwise the entry's class, or the exit's when the entry
    matched."""
    if FidelityClass.UNKNOWN in (entry, exit):
        return FidelityClass.UNKNOWN
    return entry if entry is not FidelityClass.MATCH else exit


def _ticks(difference: int, tick: int) -> int:
    if difference % tick:
        raise ValueError(f"Expected a difference of whole ticks of {tick}, got {difference}.")
    return difference // tick
