"""Why a run's fills on trade prints differ from its fills on 1-minute bars (step 2.16,
`02-engine-and-data.md` §8, D-67). The trades of a run on prints and of its run on the 1-minute
bars of the same sessions are matched by the decision that entered them and their side, as
`fefat.backtest.fidelity` matches a rerun's, and each fill that differs gets a class from a third
run: the reference engine's replay of the same prints with each print stamped at a decision's
instant moved one nanosecond after it, where the 1-minute bars put it (`restamped`).

A fill the restamped replay fills otherwise than the prints is `bar_boundary`: the prints of a
decision's second alone moved it. A fill the restamped replay fills as the prints do differs
between those prints and the 1-minute bars of the same prints, and a class names where FEFAT's
path through a bar parts from the prints, held to what the trades show: `bar_path`,
`entry_bar_path`, or `stop_through`. A trade of one run alone, made while the other held a
position at its decision, is a `cascade`; any other difference is `unknown`. A fill on prints and
a fill on a bar are alike at one price inside the bar's minute, the bar's fills being stamped at
its close (F-BAR-06); the restamped replay's fills carry the instants of their prints.

Prices are int64 in 1e-9 units and instants int64 nanoseconds UTC (ADR-0019). The trades of a few
sessions are a few hundred rows, so they are read as plain Python objects."""

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

import polars as pl

from fefat.reference.orders import OrderKind, OrderRole, PositionSide
from fefat.reference.units import instant_text

MINUTE = 60_000_000_000
"""One minute in nanoseconds, the bars' timeframe."""
MATCH = "match"
"""A fill, or a trade, alike on prints and on bars."""


class FidelityClass(StrEnum):
    """Why a fill on prints differs from the same order's fill on 1-minute bars; the tick check's
    report documents each with the rules behind it."""

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
    """A trade of one run alone, made while the other still held a position at its decision after
    an earlier difference on the same trade date."""

    UNKNOWN = "unknown"
    """A difference nothing above explains; the tick check fails with one."""


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
"""One row per trade of either run: the outcome of its entry fill and of its exit fill, each
`match` or a class, the trade's (`unknown` when either fill is, else the entry's class, else the
exit's), the fills on prints less those on bars in ticks, and a note without prices."""


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
        return cls(
            entry_decision=integer("entry_decision"),
            side=PositionSide(str(row["side"])),
            kind=OrderKind(str(row["entry_kind"])),
            entry=_Fill(integer("entry_ts"), integer("entry_price"), OrderRole.ENTRY),
            entry_level=level if isinstance(level, int) else None,
            exit=_Fill(
                integer("exit_ts"), integer("exit_price"), OrderRole(str(row["exit_reason"]))
            ),
            exit_ambiguous=bool(row["exit_ambiguous"]),
            stop=integer("stop_price"),
            target=integer("target_price"),
        )

    @property
    def long(self) -> bool:
        return self.side is PositionSide.LONG

    def fill(self, leg: _Leg) -> _Fill:
        return self.entry if leg is _Leg.ENTRY else self.exit

    def filled_as(self, other: "_Trade | None") -> bool:
        """Whether another run filled this trade's entry and exit alike: the levels and the
        bar's flags are not fills, and the restamped replay gives neither."""
        return other is not None and (self.entry, self.exit) == (other.entry, other.exit)

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
        """A trade on prints alone: a cascade when the run on bars held a position at its
        decision, else a `bar_boundary` when the restamped replay does not make it as the prints
        do."""
        held = any(other.holds_at(trade.entry_decision) for other in self.minutes.values())
        made = trade.filled_as(restamped)
        outcome = _alone_outcome(held, moved=not made)
        replay = "makes it as the prints do" if made else "does not make it"
        state = "in a position" if held else f"flat; the restamped replay {replay}"
        note = f"a trade on prints alone, the 1-minute run {state} at its decision"
        return _alone_row(trade, outcome, note, on_prints=True)

    def _on_bars_alone(self, trade: _Trade, restamped: _Trade | None) -> dict[str, object]:
        """A trade on bars alone: a cascade when the run on prints held a position at its
        decision, else a `bar_boundary` when the restamped replay makes it."""
        held = any(other.holds_at(trade.entry_decision) for other in self.ticks.values())
        made = restamped is not None
        outcome = _alone_outcome(held, moved=made)
        replay = "makes it" if made else "does not make it either"
        state = "in a position" if held else f"flat; the restamped replay {replay}"
        note = f"a trade on 1-minute bars alone, the run on prints {state} at its decision"
        return _alone_row(trade, outcome, note, on_prints=False)


def _alone_outcome(held: bool, *, moved: bool) -> FidelityClass:
    if held:
        return FidelityClass.CASCADE
    return FidelityClass.BAR_BOUNDARY if moved else FidelityClass.UNKNOWN


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
        "entry_outcome": entry,
        "exit_outcome": exit,
        "outcome": _trade_outcome(entry, exit),
        "entry_ticks": _ticks(on_prints.entry.price - on_bars.entry.price, tick),
        "exit_ticks": _ticks(on_prints.exit.price - on_bars.exit.price, tick),
        "note": f"entry {entry}; exit {reasons}: {exit}",
    }


def _fill_outcome(on_prints: _Trade, restamped: _Trade | None, on_bars: _Trade, leg: _Leg) -> str:
    """`match` when the fill on prints is the bar's; `bar_boundary` when the restamped replay
    fills it otherwise than the prints; else the class of the restamped fill against the bar's."""
    if on_prints.fill(leg).alike_on_a_bar(on_bars.fill(leg)):
        return MATCH
    if restamped is None or restamped.fill(leg) != on_prints.fill(leg):
        return str(FidelityClass.BAR_BOUNDARY)
    apart = _entry_apart if leg is _Leg.ENTRY else _exit_apart
    return str(apart(restamped, on_bars))


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


def _trade_outcome(entry: str, exit: str) -> str:
    """`unknown` when either fill is; otherwise the entry's class, or the exit's when the entry
    matched."""
    if str(FidelityClass.UNKNOWN) in (entry, exit):
        return str(FidelityClass.UNKNOWN)
    return entry if entry != MATCH else exit


def _ticks(difference: int, tick: int) -> int:
    if difference % tick:
        raise ValueError(f"Expected a difference of whole ticks of {tick}, got {difference}.")
    return difference // tick


@dataclass(frozen=True)
class FidelitySummary:
    """One strategy's classified trades in numbers: each run's trades, the pairs matched by
    decision and side, the pairs whose two fills matched, those whose exits matched, the fills of
    the pairs (two a pair) and those equal, the differing trades by class, the differing fills by
    class, a pair's each and a lone trade's two, and the trades left unknown."""

    tick_trades: int
    minute_trades: int
    matched: int
    exact: int
    exits_alike: int
    fills_compared: int
    equal_fills: int
    trades_by_class: dict[str, int]
    fills_by_class: dict[str, int]
    unknown: int


def summarise(classified: pl.DataFrame) -> FidelitySummary:
    """The counts of one strategy's classified trades."""
    paired = classified.filter(pl.col("in_ticks") & pl.col("in_minutes"))
    alone = classified.filter(~(pl.col("in_ticks") & pl.col("in_minutes")))
    pair_fills = [*paired.get_column("entry_outcome"), *paired.get_column("exit_outcome")]
    fills = Counter(outcome for outcome in pair_fills if outcome != MATCH)
    for outcome in alone.get_column("outcome"):
        fills[outcome] += 2
    differing = classified.filter(pl.col("outcome") != MATCH).get_column("outcome")
    return FidelitySummary(
        tick_trades=int(classified["in_ticks"].sum()),
        minute_trades=int(classified["in_minutes"].sum()),
        matched=paired.height,
        exact=paired.filter(pl.col("outcome") == MATCH).height,
        exits_alike=paired.filter(pl.col("exit_outcome") == MATCH).height,
        fills_compared=len(pair_fills),
        equal_fills=pair_fills.count(MATCH),
        trades_by_class=dict(sorted(Counter(differing.to_list()).items())),
        fills_by_class=dict(sorted(fills.items())),
        unknown=int((differing == str(FidelityClass.UNKNOWN)).sum()),
    )
