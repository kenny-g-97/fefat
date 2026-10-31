"""Matching FEFAT's trades with another engine's and classifying every difference (step 2.14,
Done means 2). Trades are matched on the decision that entered them and their side, as
`fefat.backtest.fidelity` matches a rerun's; a pair is compared on its entry's price (and bar,
unless the entry is a market order, whose stamp is a convention of its own) and on its exit's
reason, price, and bar. Each class has a predicate that checks the 1-minute bars support its
explanation; a difference no predicate explains is `unknown`. The trades of one month are a
few hundred rows, so the predicates read them as plain Python objects.

Prices are int64 in 1e-9 units and instants int64 nanoseconds UTC, as FEFAT's artifacts hold
them; the other engine's side converts to the same."""

from bisect import bisect_left, bisect_right
from collections import Counter
from dataclasses import dataclass
from enum import StrEnum

import polars as pl

from fefat_xcheck.conventions import EngineConventions, Extreme, LimitGap, MarketFill
from fefat_xcheck.entry_bar import EntryBar, fefat_exit, other_exit

MATCH = "match"
"""A fill, or a trade, the other engine made alike."""


class DifferenceClass(StrEnum):
    """Why a fill differs. The report documents each with the rules behind it."""

    BAR_BOUNDARY = "bar_boundary"
    """A market order decided at a 5-minute close: the other engine fills it at that close,
    FEFAT at the next 1-minute bar's open (F-MKT-03, F-ACT-02)."""

    BAR_PATH = "bar_path"
    """One bar reached both legs of the bracket: FEFAT visits the adverse extreme first and fills
    the stop (F-BAR-02, flagged ambiguous by F-BAR-05); the other engine's path visits the
    target's extreme first."""

    ENTRY_BAR_PATH = "entry_bar_path"
    """After an entry inside a bar, the two engines visit the bar's remaining extremes in
    different orders (F-BAR-03, F-BAR-04 against the other engine's fixed or adaptive order), so
    one fills a leg on the rest of the bar where the other carries the position out of it, or
    they fill different legs."""

    LEG_RELEASED_THROUGH = "leg_released_through"
    """The tick an entry fills on releases its legs, and that tick is already past a leg's level:
    NautilusTrader fills the leg at the tick's price, the bar's extreme; FEFAT works the leg on
    the rest of the path and fills it at its level (F-OCO-02, F-STP-04, F-LMT-03)."""

    GAP_LIMIT_CLAMPED = "gap_limit_clamped"
    """A bar opened past a resting limit's price in its favour and never came back to it: FEFAT
    fills the limit at its price (F-LMT-03, never clamped into the bar's range, F-SLP-01);
    NinjaTrader 8 fills it at that price clamped into the bar, its high for a buy, its low for a
    sell (the builder's spec, H4)."""

    CASCADE = "cascade"
    """A trade one engine made while the other still held a position, after an earlier
    difference on the same trade date left them in different states."""

    UNKNOWN = "unknown"
    """No predicate explains it: the report must not pass with one."""


TRADE_COLUMNS = pl.Schema(
    {
        "entry_decision": pl.Int64,
        "side": pl.String,
        "entry_kind": pl.String,
        "entry_ts": pl.Int64,
        "entry_price": pl.Int64,
        "exit_ts": pl.Int64,
        "exit_price": pl.Int64,
        "exit_reason": pl.String,
        "stop_price": pl.Int64,
        "target_price": pl.Int64,
        "gross_pnl": pl.Float64,
    }
)
"""One engine's trades as the comparison reads them: the decision that entered, `long` or
`short`, the entry's kind (`market`, `limit`, `stop`), the entry's and the exit's fills, the exit
reason (`stop`, `target`, `flat_by`), the bracket's levels, and the gross profit and loss in the
instrument's currency."""
CLASSIFIED_COLUMNS = pl.Schema(
    {
        "entry_decision": pl.Int64,
        "side": pl.String,
        "entry_kind": pl.String,
        "in_fefat": pl.Boolean,
        "in_other": pl.Boolean,
        "entry_outcome": pl.String,
        "exit_outcome": pl.String,
        "outcome": pl.String,
        "entry_ticks": pl.Int64,
        "exit_ticks": pl.Int64,
        "note": pl.String,
    }
)
"""One row per trade of either engine: the outcome of its entry fill and of its exit fill, each
`match` or a class, the trade's outcome (the entry's unless it matched), FEFAT's fill prices
less the other engine's in ticks, and a note without prices."""
MARKET, FLAT_BY, STOP, TARGET = "market", "flat_by", "stop", "target"


@dataclass(frozen=True)
class Trade:
    entry_decision: int
    side: str
    entry_kind: str
    entry_ts: int
    entry_price: int
    exit_ts: int
    exit_price: int
    exit_reason: str
    stop_price: int
    target_price: int

    @property
    def long(self) -> bool:
        return self.side == "long"

    def holds_at(self, decision: int) -> bool:
        """Whether the position was still open at a later decision: its exit fills at a bar's
        close, before the decisions of that instant (F-CLK-02)."""
        return self.entry_decision < decision < self.exit_ts

    def level_of(self, reason: str) -> int | None:
        if reason == STOP:
            return self.stop_price
        if reason == TARGET:
            return self.target_price
        return None


@dataclass(frozen=True)
class Bar:
    ts_close: int
    open: int
    high: int
    low: int
    close: int

    def reaches(self, level: int) -> bool:
        return self.low <= level <= self.high


class Bars:
    """The 1-minute bars both engines filled on, looked up by close and after an instant."""

    def __init__(self, bars: pl.DataFrame) -> None:
        rows = bars.select("ts_close", "open", "high", "low", "close").sort("ts_close")
        self._bars = [Bar(*row) for row in rows.iter_rows()]
        self._closes = [bar.ts_close for bar in self._bars]

    def at(self, ts_close: int) -> Bar | None:
        """The bar closing at the instant, if one is stored."""
        index = bisect_left(self._closes, ts_close)
        if index < len(self._bars) and self._bars[index].ts_close == ts_close:
            return self._bars[index]
        return None

    def after(self, instant: int) -> Bar | None:
        """The first bar closing after the instant: the first an order decided then sees
        (F-ACT-02)."""
        index = bisect_right(self._closes, instant)
        return self._bars[index] if index < len(self._bars) else None


def classify(
    fefat: pl.DataFrame,
    other: pl.DataFrame,
    bars: pl.DataFrame,
    conventions: EngineConventions,
    tick: int,
) -> pl.DataFrame:
    """Match FEFAT's trades with the other engine's and give each pair, and each trade of one
    engine alone, its outcome, with the columns of `CLASSIFIED_COLUMNS`."""
    ours, theirs = _trades_by_key(fefat), _trades_by_key(other)
    lookup = Bars(bars)
    rows = []
    for key in sorted(set(ours) | set(theirs)):
        mine, its = ours.get(key), theirs.get(key)
        if mine is None or its is None:
            rows.append(_one_sided(key, mine, its, ours, theirs))
            continue
        rows.append(_pair(mine, its, lookup, conventions, tick))
    return pl.DataFrame(rows, schema=CLASSIFIED_COLUMNS)


def _trades_by_key(trades: pl.DataFrame) -> dict[tuple[int, str], Trade]:
    columns = [name for name in TRADE_COLUMNS if name != "gross_pnl"]
    keyed = {}
    for row in trades.select(columns).iter_rows():
        trade = Trade(*row)
        key = (trade.entry_decision, trade.side)
        if key in keyed:
            raise ValueError(f"Expected one trade per decision and side, got two at {key}.")
        keyed[key] = trade
    return keyed


def _one_sided(
    key: tuple[int, str],
    mine: Trade | None,
    its: Trade | None,
    ours: dict[tuple[int, str], Trade],
    theirs: dict[tuple[int, str], Trade],
) -> dict[str, object]:
    present = mine if mine is not None else its
    assert present is not None
    absent_engine = theirs if mine is not None else ours
    decision = key[0]
    held = any(trade.holds_at(decision) for trade in absent_engine.values())
    outcome = DifferenceClass.CASCADE if held else DifferenceClass.UNKNOWN
    whose = "FEFAT" if mine is not None else "the other engine"
    note = f"a trade of {whose} alone, the other engine " + (
        "still in a position at its decision" if held else "flat at its decision"
    )
    return {
        "entry_decision": decision,
        "side": present.side,
        "entry_kind": present.entry_kind,
        "in_fefat": mine is not None,
        "in_other": its is not None,
        "entry_outcome": str(outcome),
        "exit_outcome": str(outcome),
        "outcome": str(outcome),
        "entry_ticks": None,
        "exit_ticks": None,
        "note": note,
    }


def _pair(
    mine: Trade, its: Trade, lookup: Bars, conventions: EngineConventions, tick: int
) -> dict[str, object]:
    entry = _entry_outcome(mine, its, lookup, conventions)
    exit = _exit_outcome(mine, its, lookup, conventions)
    outcome = entry if entry != MATCH else exit
    return {
        "entry_decision": mine.entry_decision,
        "side": mine.side,
        "entry_kind": mine.entry_kind,
        "in_fefat": True,
        "in_other": True,
        "entry_outcome": entry,
        "exit_outcome": exit,
        "outcome": outcome,
        "entry_ticks": _ticks(mine.entry_price - its.entry_price, tick),
        "exit_ticks": _ticks(mine.exit_price - its.exit_price, tick),
        "note": f"entry {entry}; exit {mine.exit_reason} against {its.exit_reason}: {exit}",
    }


def _ticks(difference: int, tick: int) -> int:
    if difference % tick:
        raise ValueError(f"Expected a difference of whole ticks of {tick}, got {difference}.")
    return difference // tick


def _entry_outcome(mine: Trade, its: Trade, lookup: Bars, conventions: EngineConventions) -> str:
    same_bar = mine.entry_kind == MARKET or mine.entry_ts == its.entry_ts
    if mine.entry_price == its.entry_price and same_bar:
        return MATCH
    if mine.entry_kind == MARKET and _at_close_against_next_open(
        mine.entry_decision, its.entry_price, mine.entry_price, mine.entry_ts, lookup, conventions
    ):
        return str(DifferenceClass.BAR_BOUNDARY)
    return str(DifferenceClass.UNKNOWN)


def _at_close_against_next_open(
    decision: int,
    its_price: int,
    my_price: int,
    my_ts: int,
    lookup: Bars,
    conventions: EngineConventions,
) -> bool:
    """The other engine filled a market order at the decision bar's close and FEFAT at the next
    bar's open (F-MKT-03, F-ACT-02)."""
    if conventions.market_fill != MarketFill.AT_DECISION_CLOSE:
        return False
    decided_on, next_bar = lookup.at(decision), lookup.after(decision)
    if decided_on is None or next_bar is None:
        return False
    return (
        its_price == decided_on.close and my_price == next_bar.open and my_ts == next_bar.ts_close
    )


def _exit_outcome(mine: Trade, its: Trade, lookup: Bars, conventions: EngineConventions) -> str:
    same_reason = mine.exit_reason == its.exit_reason
    same_bar = mine.exit_ts == its.exit_ts
    if (
        same_reason
        and mine.exit_price == its.exit_price
        and (same_bar or mine.exit_reason == FLAT_BY)
    ):
        return MATCH
    if same_reason and mine.exit_reason == FLAT_BY:
        if _at_close_against_next_open(
            its.exit_ts, its.exit_price, mine.exit_price, mine.exit_ts, lookup, conventions
        ):
            return str(DifferenceClass.BAR_BOUNDARY)
        return str(DifferenceClass.UNKNOWN)
    if _other_path_reaches_its_leg_first(mine, its, lookup, conventions):
        return str(DifferenceClass.BAR_PATH)
    if _limit_passed_by_a_gap_clamped(mine, its, lookup, conventions):
        return str(DifferenceClass.GAP_LIMIT_CLAMPED)
    return _entry_bar_outcome(mine, its, lookup, conventions)


def _limit_passed_by_a_gap_clamped(
    mine: Trade, its: Trade, lookup: Bars, conventions: EngineConventions
) -> bool:
    """Both took the target, a limit, in one bar lying wholly past its price in its favour:
    FEFAT at the price, the other engine at the bar's nearest extreme."""
    if conventions.limit_gap != LimitGap.CLAMPED_INTO_THE_BAR:
        return False
    if mine.exit_reason != TARGET or its.exit_reason != TARGET or mine.exit_ts != its.exit_ts:
        return False
    bar = lookup.at(mine.exit_ts)
    if bar is None or mine.exit_price != mine.target_price:
        return False
    if mine.long:
        return bar.low > mine.target_price and its.exit_price == bar.low
    return bar.high < mine.target_price and its.exit_price == bar.high


def _other_path_reaches_its_leg_first(
    mine: Trade, its: Trade, lookup: Bars, conventions: EngineConventions
) -> bool:
    """Both exits fell in one bar that reached the stop and the target: FEFAT took the stop,
    adverse extreme first (F-BAR-02), and the other engine's order of extremes reaches the leg
    it took first."""
    if {mine.exit_reason, its.exit_reason} != {STOP, TARGET} or mine.exit_reason != STOP:
        return False
    bar = lookup.at(mine.exit_ts)
    if bar is None or its.exit_ts != mine.exit_ts:
        return False
    if not (bar.reaches(mine.stop_price) and bar.reaches(mine.target_price)):
        return False
    first = conventions.first_extreme(bar.open, bar.high, bar.low, mine.long)
    target_extreme = Extreme.HIGH if mine.long else Extreme.LOW
    return first == target_extreme


def _entry_bar_outcome(
    mine: Trade, its: Trade, lookup: Bars, conventions: EngineConventions
) -> str:
    """Both entries filled inside one bar: each engine's exit on the rest of that bar, or none,
    must be what its path gives (`fefat_xcheck.entry_bar`); the two paths differing explains
    the difference, as a leg filled at the releasing tick's price or as the order of the
    extremes."""
    bar = lookup.at(mine.entry_ts)
    if mine.entry_kind == MARKET or bar is None or mine.entry_ts != its.entry_ts:
        return str(DifferenceClass.UNKNOWN)
    entry_bar = EntryBar(
        bar.open,
        bar.high,
        bar.low,
        bar.close,
        mine.long,
        mine.entry_kind,
        mine.entry_price,
        mine.stop_price,
        mine.target_price,
    )
    expected_mine, expected_its = fefat_exit(entry_bar), other_exit(entry_bar, conventions)
    observed_mine, observed_its = _exit_in_the_entry_bar(mine), _exit_in_the_entry_bar(its)
    if expected_mine != observed_mine or expected_its != observed_its:
        return str(DifferenceClass.UNKNOWN)
    if expected_mine is None or expected_its is None or expected_mine[0] != expected_its[0]:
        return str(DifferenceClass.ENTRY_BAR_PATH)
    return str(DifferenceClass.LEG_RELEASED_THROUGH)


def _exit_in_the_entry_bar(trade: Trade) -> tuple[str, int] | None:
    if trade.exit_ts != trade.entry_ts:
        return None
    return trade.exit_reason, trade.exit_price


@dataclass(frozen=True)
class Summary:
    """One strategy's comparison in numbers: the trades of each engine, the pairs matched by
    decision and side, the pairs whose two fills matched, the fills of the pairs that matched
    (two a pair) and those equal, the trades by class (the first class among a pair's fills, or
    the lone trade's), the fills by class (a lone trade's two among them), and the trades left
    unknown."""

    fefat_trades: int
    other_trades: int
    matched: int
    exact: int
    fills_compared: int
    equal_fills: int
    trades_by_class: dict[str, int]
    fills_by_class: dict[str, int]
    unknown: int


def summarise(classified: pl.DataFrame) -> Summary:
    """The counts of one strategy's classified trades."""
    paired = classified.filter(pl.col("in_fefat") & pl.col("in_other"))
    differing = classified.filter(pl.col("outcome") != MATCH)
    fills: Counter[str] = Counter()
    equal = 0
    for entry, exit in classified.select("entry_outcome", "exit_outcome").iter_rows():
        fills.update(outcome for outcome in (entry, exit) if outcome != MATCH)
        equal += sum(outcome == MATCH for outcome in (entry, exit))
    return Summary(
        fefat_trades=int(classified["in_fefat"].sum()),
        other_trades=int(classified["in_other"].sum()),
        matched=paired.height,
        exact=paired.filter(pl.col("outcome") == MATCH).height,
        fills_compared=2 * paired.height,
        equal_fills=equal,
        trades_by_class=dict(sorted(Counter(differing["outcome"].to_list()).items())),
        fills_by_class=dict(sorted(fills.items())),
        unknown=differing.filter(pl.col("outcome") == str(DifferenceClass.UNKNOWN)).height,
    )
