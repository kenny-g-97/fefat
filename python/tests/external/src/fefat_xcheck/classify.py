"""Matching FEFAT's trades with another engine's and classifying every difference (step 2.14,
Done means 2). Trades are matched on the decision that entered them and their side, as
`fefat.backtest.fidelity` matches a rerun's. Each engine's trade is held to the replay of its
own rules on the 1-minute bars (`fefat_xcheck.replay`): a pair whose two trades are both what
their rules give is explained by a class naming where the two sets of rules part, and a trade
the rules do not give is `unknown`. A market fill's stamp is a convention of its own, so a
market entry and a flat-by exit are compared by their prices; every other fill by its price and
its bar. The trades of one month are a few hundred rows, so the replay reads them as plain
Python objects.

Prices are int64 in 1e-9 units and instants int64 nanoseconds UTC, as FEFAT's artifacts hold
them; the other engine's side converts to the same."""

from collections import Counter
from dataclasses import dataclass
from enum import StrEnum

import polars as pl

from fefat_xcheck.conventions import FEFAT, LimitGap, MarketFill
from fefat_xcheck.replay import (
    Bars,
    EntryKind,
    ExitReason,
    Expected,
    Legs,
    Rules,
    Side,
    expected_trade,
)

MATCH = "match"
"""A fill, or a trade, the other engine made alike."""


class DifferenceClass(StrEnum):
    """Why a fill differs. The report documents each with the rules behind it."""

    BAR_BOUNDARY = "bar_boundary"
    """A market order decided at a 5-minute close: the other engine fills it at that close,
    FEFAT at the next 1-minute bar's open (F-MKT-03, F-ACT-02)."""

    BAR_PATH = "bar_path"
    """A bar held from its open, a later bar or a market entry's own bar, reached both legs of
    the bracket: FEFAT visits the adverse extreme first and fills the stop (F-BAR-02, F-BAR-04,
    flagged ambiguous by F-BAR-05); the other engine's path visits the target's extreme first."""

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
    """A trade one engine made, as its rules give it, while the other still held a position at
    its decision, after an earlier difference on the same trade date left them in different
    states."""

    UNKNOWN = "unknown"
    """A fill the engine's own rules do not give on the bars, or a difference no class names:
    the report must not pass with one."""


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
`match` or a class, the trade's outcome (`unknown` when either fill is, else the entry's class,
else the exit's), FEFAT's fill prices less the other engine's in ticks, and a note without
prices."""


@dataclass(frozen=True)
class Trade:
    entry_decision: int
    side: Side
    entry_kind: EntryKind
    entry_ts: int
    entry_price: int
    exit_ts: int
    exit_price: int
    exit_reason: ExitReason
    stop_price: int
    target_price: int

    @property
    def long(self) -> bool:
        return self.side == Side.LONG

    def holds_at(self, decision: int) -> bool:
        """Whether the position was still open at a later decision: its exit fills at a bar's
        close, before the decisions of that instant (F-CLK-02)."""
        return self.entry_decision < decision < self.exit_ts

    def as_rules_give(self, rules: Rules, bars: Bars) -> Expected | None:
        """What the rules give this trade's decision."""
        legs = Legs(self.long, self.stop_price, self.target_price)
        return expected_trade(self.entry_decision, self.side, self.entry_kind, legs, rules, bars)

    def entry_is(self, expected: Expected | None) -> bool:
        return (
            expected is not None
            and self.entry_price == expected.entry_price
            and self.entry_ts == expected.entry_ts
        )

    def exit_is(self, expected: Expected | None) -> bool:
        return (
            expected is not None
            and self.exit_reason == expected.exit_reason
            and self.exit_price == expected.exit_price
            and self.exit_ts == expected.exit_ts
        )


def classify(
    fefat: pl.DataFrame, other: pl.DataFrame, bars: pl.DataFrame, rules: Rules
) -> pl.DataFrame:
    """Match FEFAT's trades with the other engine's, hold each to its engine's replay, and give
    each pair, and each trade of one engine alone, its outcome, with the columns of
    `CLASSIFIED_COLUMNS`; `rules` are the other engine's, FEFAT's following from them."""
    ours, theirs = _trades_by_key(fefat), _trades_by_key(other)
    lookup = Bars.of_rows(bars.select("ts_close", "open", "high", "low", "close").rows())
    fefat_rules = Rules(FEFAT, rules.tick, rules.offset_ticks, rules.flat_by, rules.zone)
    rows = []
    for key in sorted(set(ours) | set(theirs)):
        mine, its = ours.get(key), theirs.get(key)
        if mine is None or its is None:
            rows.append(_one_sided(key, mine, its, ours, theirs, fefat_rules, rules, lookup))
            continue
        rows.append(_pair(mine, its, fefat_rules, rules, lookup))
    return pl.DataFrame(rows, schema=CLASSIFIED_COLUMNS)


def _trades_by_key(trades: pl.DataFrame) -> dict[tuple[int, str], Trade]:
    columns = [name for name in TRADE_COLUMNS if name != "gross_pnl"]
    keyed = {}
    for row in trades.select(columns).iter_rows(named=True):
        trade = Trade(
            **{
                **row,
                "side": Side(row["side"]),
                "entry_kind": EntryKind(row["entry_kind"]),
                "exit_reason": ExitReason(row["exit_reason"]),
            }
        )
        key = (trade.entry_decision, str(trade.side))
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
    fefat_rules: Rules,
    rules: Rules,
    lookup: Bars,
) -> dict[str, object]:
    """A trade of one engine alone: a cascade when its fills are what its rules give and the
    other engine still held a position at its decision; unknown otherwise."""
    present, own_rules = (mine, fefat_rules) if mine is not None else (its, rules)
    assert present is not None
    absent, absent_name = (theirs, "the other engine") if mine is not None else (ours, "FEFAT")
    held = any(trade.holds_at(key[0]) for trade in absent.values())
    expected = present.as_rules_give(own_rules, lookup)
    given = present.entry_is(expected) and present.exit_is(expected)
    outcome = DifferenceClass.CASCADE if held and given else DifferenceClass.UNKNOWN
    whose = "FEFAT" if mine is not None else "the other engine"
    state = "still in a position" if held else "flat"
    note = f"a trade of {whose} alone, {absent_name} {state} at its decision"
    if not given:
        note += "; its fills are not what its rules give"
    return {
        "entry_decision": key[0],
        "side": str(present.side),
        "entry_kind": str(present.entry_kind),
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
    mine: Trade, its: Trade, fefat_rules: Rules, rules: Rules, lookup: Bars
) -> dict[str, object]:
    expected_mine = mine.as_rules_give(fefat_rules, lookup)
    expected_its = its.as_rules_give(rules, lookup)
    entries_given = mine.entry_is(expected_mine) and its.entry_is(expected_its)
    exits_given = mine.exit_is(expected_mine) and its.exit_is(expected_its)
    entry = _entry_outcome(mine, its, rules) if entries_given else str(DifferenceClass.UNKNOWN)
    exit = (
        _exit_outcome(mine, its, rules, lookup)
        if entries_given and exits_given
        else str(DifferenceClass.UNKNOWN)
    )
    return {
        "entry_decision": mine.entry_decision,
        "side": str(mine.side),
        "entry_kind": str(mine.entry_kind),
        "in_fefat": True,
        "in_other": True,
        "entry_outcome": entry,
        "exit_outcome": exit,
        "outcome": _trade_outcome(entry, exit),
        "entry_ticks": _ticks(mine.entry_price - its.entry_price, rules.tick),
        "exit_ticks": _ticks(mine.exit_price - its.exit_price, rules.tick),
        "note": f"entry {entry}; exit {mine.exit_reason} against {its.exit_reason}: {exit}",
    }


def _trade_outcome(entry: str, exit: str) -> str:
    """A trade is unknown when either of its fills is; otherwise its entry's class, or its
    exit's when the entry matched."""
    if str(DifferenceClass.UNKNOWN) in (entry, exit):
        return str(DifferenceClass.UNKNOWN)
    return entry if entry != MATCH else exit


def _ticks(difference: int, tick: int) -> int:
    if difference % tick:
        raise ValueError(f"Expected a difference of whole ticks of {tick}, got {difference}.")
    return difference // tick


def _entry_outcome(mine: Trade, its: Trade, rules: Rules) -> str:
    """Both entries are what their rules give: alike, or a market order filled at the deciding
    bar's close by the other engine and at the next bar's open by FEFAT."""
    if mine.entry_price == its.entry_price:
        return MATCH
    by_convention = (
        mine.entry_kind == EntryKind.MARKET
        and rules.conventions.market_fill == MarketFill.AT_DECISION_CLOSE
    )
    return str(DifferenceClass.BAR_BOUNDARY if by_convention else DifferenceClass.UNKNOWN)


def _exit_outcome(mine: Trade, its: Trade, rules: Rules, lookup: Bars) -> str:
    """Both exits are what their rules give: alike, or apart where the two sets of rules part."""
    if mine.exit_reason == its.exit_reason == ExitReason.FLAT_BY:
        return MATCH if mine.exit_price == its.exit_price else str(DifferenceClass.BAR_BOUNDARY)
    same_reason, same_bar = mine.exit_reason == its.exit_reason, mine.exit_ts == its.exit_ts
    if same_reason and same_bar and mine.exit_price == its.exit_price:
        return MATCH
    resting_entry = mine.entry_kind != EntryKind.MARKET
    in_entry_bar = resting_entry and (mine.exit_ts == mine.entry_ts or its.exit_ts == its.entry_ts)
    if same_reason and same_bar:
        return str(_same_leg_apart(mine, rules, lookup, in_entry_bar))
    if in_entry_bar:
        return str(DifferenceClass.ENTRY_BAR_PATH)
    if same_bar:
        return str(DifferenceClass.BAR_PATH)
    return str(DifferenceClass.UNKNOWN)


def _same_leg_apart(mine: Trade, rules: Rules, lookup: Bars, in_entry_bar: bool) -> DifferenceClass:
    """The same leg in the same bar at different prices: released through on the entry's bar,
    or a limit clamped into a bar opening past it."""
    if in_entry_bar:
        return DifferenceClass.LEG_RELEASED_THROUGH
    clamps = rules.conventions.limit_gap == LimitGap.CLAMPED_INTO_THE_BAR
    if clamps and mine.exit_reason == ExitReason.TARGET and lookup.at(mine.exit_ts) is not None:
        return DifferenceClass.GAP_LIMIT_CLAMPED
    return DifferenceClass.UNKNOWN


@dataclass(frozen=True)
class Summary:
    """One strategy's comparison in numbers: the trades of each engine, the pairs matched by
    decision and side, the pairs whose two fills matched, the fills of the pairs that matched
    (two a pair) and those equal, the trades by class (the first class among a pair's fills, or
    the lone trade's), the pairs' fills by class, and the trades left unknown."""

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
    for entry, exit in paired.select("entry_outcome", "exit_outcome").iter_rows():
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
