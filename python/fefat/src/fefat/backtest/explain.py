"""A trade of a run explained event by event (step 2.11, `02` §5, D-10): `Run.explain(trade_id)`
replays the trade's episode through the reference engine (`fefat.reference`) on the run's own
records and prints every event the reference logs, each order placed, active, triggered, filled,
or cancelled, with the rule of `docs/spec/fill-semantics.md` behind it, then each fill with its
rule, liquidity, and slippage, and on bars the bar that reached a stop; it asserts that the
reference's fills are the Rust engine's.

    run.explain(trade_id=17)

A trade's id is its entry order, `entry_order` in the trades artifact. Its episode starts at the
decision that placed the entry, flat, with the cash the run held then, on the records from the
last one before that decision, which set the price the decision reads, to the fill that left the
trade flat. The template reads the signal frame from that decision to the end of the exit's trade
date, so that its time rules see whole sessions. The store's data is first checked against the
snapshots the run's record pins (`fefat.backtest.pinned_data`), and its fee table and calendar against those the run's config
gave the engine. Bars and trade prints replay; an episode on TBBO or on two
fidelities, a trade of trade prints across a roll, and a trade entered by reversing a position
are refused (`BACKLOG.md`)."""

import os
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

import polars as pl

from fefat.backtest.explain_episode import Episode, Trade, episode_of
from fefat.backtest.pinned_data import pinned_snapshots
from fefat.backtest.record import RunRecord
from fefat.config import resolve_paths
from fefat.market.calendar import SessionTable
from fefat.market.fees import TABLES
from fefat.market.fidelity import TickFidelity, fidelity_in_words, parse_fidelity
from fefat.market.saved_instruments import instrument_table
from fefat.market.schema import Timeframe
from fefat.market.store import Store
from fefat.reference.costs import RunFees
from fefat.reference.engine import ReferenceEngine
from fefat.reference.hours import CalendarHours
from fefat.reference.run_documents import fees_document, hours_document
from fefat.reference.rust_batch import FillView
from fefat.reference.rust_run import fill_text
from fefat.reference.tape import BarRecord, Record
from fefat.reference.template import TemplateStrategy
from fefat.reference.timeline import RunResult
from fefat.reference.units import instant_text, instrument_parameters, money_text, price_text
from fefat.strategy.spec import StrategySpec

if TYPE_CHECKING:
    from fefat.backtest.runs import Run


@dataclass(frozen=True, repr=False)
class Explanation:
    """A trade explained: its id, the lines printed, and the fills of its episode, the reference
    engine's and the Rust engine's alike."""

    trade_id: int
    lines: tuple[str, ...]
    fills: tuple[FillView, ...]

    def text(self) -> str:
        return "\n".join(self.lines)

    def __repr__(self) -> str:
        return f"Explanation of trade {self.trade_id}, {len(self.fills)} fills alike"


class EnginesDisagreementError(AssertionError):
    """The reference engine's fills of an episode are not the Rust engine's (D-10): both are
    its `reference` and `rust`, which its message leaves out, since they hold the trader's
    prices (D-21)."""

    def __init__(
        self, trade_id: int, reference: tuple[FillView, ...], rust: tuple[FillView, ...]
    ) -> None:
        apart = sum(ours != theirs for ours, theirs in zip(reference, rust, strict=False))
        apart += abs(len(reference) - len(rust))
        super().__init__(
            f"Expected the reference engine's fills of trade {trade_id} to be the Rust "
            f"engine's, got {apart} of {max(len(reference), len(rust))} apart: the error's "
            "`reference` and `rust` hold them, which `fill_text` writes out."
        )
        self.reference, self.rust = reference, rust


def explain(run: "Run", trade_id: int) -> Explanation:
    """Trade `trade_id` of `run` replayed through the reference engine (module docstring);
    `EnginesDisagreementError` when its fills are not the Rust engine's."""
    record = run.record
    trade = _trade(run.trades, trade_id)
    episode_fills = run.fills.filter(
        pl.col("order") >= trade_id, pl.col("ts").is_between(trade["entry_ts"], trade["exit_ts"])
    )
    exit_date = episode_fills.get_column("trade_date").max()
    if not isinstance(exit_date, date):
        raise ValueError(f"Expected the fills of trade {trade_id} among the run's, got none.")
    rust = _through_exit(
        (FillView.of_row(row) for row in episode_fills.iter_rows(named=True)), trade
    )
    fidelity = _fidelity(rust, trade_id)
    paths = resolve_paths(os.environ)
    store = Store(paths.data_dir)
    snapshots = pinned_snapshots(store, run)
    root = record.instrument.root
    sessions = instrument_table(paths.data_dir).sessions_of(root, paths.cache_dir)
    fees = _the_runs_fees_and_calendar(run, sessions)
    episode = episode_of(run, trade, fidelity, exit_date, store, snapshots)
    first_id = _first_order(run.orders, trade)
    replayed = _replayed(record, episode, (fidelity, fees), first_id, sessions)
    reference = _through_exit((FillView.of(fill) for fill in replayed.fills), trade)
    if reference != rust:
        raise EnginesDisagreementError(trade_id, reference, rust)
    lines = (
        _heading(trade, record),
        f"Replayed through the reference engine on {fidelity_in_words(fidelity)} records from "
        f"{instant_text(episode.tape[0].starts_at())}:",
        *replayed.log.lines(),
        "Fills, the reference engine's and the Rust engine's alike:",
        *_fill_lines(reference, episode.tape, run.orders),
    )
    return Explanation(trade_id, lines, rust)


def _first_order(orders: pl.DataFrame, trade: Trade) -> int:
    """The id the replay numbers its orders from: the first entry the trade's decision placed,
    which is the buy of a pair whose sell opened a short (F-ENT-01), else the entry itself; the
    stop and target of a trade closed inside the bar before can carry the same instant (F-BAR-06,
    F-OCO-02), so only entries count."""
    placed = orders.filter(
        pl.col("placed_at") == trade["entry_decision"],
        pl.col("role") == "entry",
        pl.col("id") <= trade["entry_order"],
    )
    first = placed.get_column("id").min()
    if not isinstance(first, int):
        raise ValueError(
            f"Expected the order of trade {trade['entry_order']} among the run's orders placed "
            f"at its decision, got none."
        )
    return first


def _trade(trades: pl.DataFrame, trade_id: int) -> Trade:
    """The trade whose entry order is `trade_id`."""
    found = trades.filter(pl.col("entry_order") == trade_id)
    if found.is_empty():
        ids = ", ".join(str(order) for order in trades.get_column("entry_order").head(10))
        raise ValueError(
            f"Expected the id of a trade of the run, its entry order, such as {ids or 'none'}, "
            f"got {trade_id}."
        )
    return found.row(0, named=True)


def _through_exit(fills: Iterable[FillView], trade: Trade) -> tuple[FillView, ...]:
    """The fills from the trade's entry to the one that left it flat, the last at its exit's
    instant with its exit's role, so that an entry reversing the position at that instant, the
    next trade's (F-ENT-04), is left out; all of them when none is, which the comparison shows."""
    listed = tuple(fills)
    exits = [
        index
        for index, fill in enumerate(listed)
        if fill.ts == trade["exit_ts"] and fill.role == trade["exit_reason"]
    ]
    return listed[: exits[-1] + 1] if exits else listed


def _fidelity(fills: Sequence[FillView], trade_id: int) -> TickFidelity | Timeframe:
    """The one fidelity the episode's fills priced on: trade prints or bars."""
    levels = sorted({fill.fidelity for fill in fills})
    if len(levels) != 1:
        raise ValueError(
            f"Expected the fills of trade {trade_id} on one fidelity, got {', '.join(levels)}: "
            "an episode across fidelity eras waits for the Phase 2 exit (BACKLOG.md)."
        )
    fidelity = parse_fidelity(levels[0])
    if fidelity is TickFidelity.TBBO:
        raise ValueError(
            f"Expected trade {trade_id} on trade prints or bars, got TBBO, whose records the "
            "reference engine reads from scenarios alone so far (BACKLOG.md)."
        )
    return fidelity


def _the_runs_fees_and_calendar(run: "Run", sessions: SessionTable) -> RunFees:
    """The fee table the run paid, refused by name, as the calendar is, unless today's is the
    one the run's config gave the engine: a fill's fee and a session's hours would differ."""
    record = run.record
    root, name = record.instrument.root, record.fee_table.name
    fees = RunFees.of_table(TABLES[name], root) if name in TABLES else None
    if fees is None or fees_document(fees) != record.engine_config["fees"]:
        raise ValueError(
            f"Expected the fee table {name} as the run paid it, got another: the fee table "
            f"{name} changed since the run, so run it again before explaining its trades."
        )
    first, last = run.signals.select(
        pl.col("ts_close").min().alias("first"), pl.col("ts_close").max().alias("last")
    ).row(0)
    hours = hours_document(CalendarHours.around(sessions, first, last))
    if hours != record.engine_config["hours"]:
        raise ValueError(
            f"Expected the calendar of {root} as the run traded it, got other sessions: the "
            f"calendar of {root} changed since the run, so run it again before explaining its "
            "trades."
        )
    return fees


def _replayed(
    record: RunRecord,
    episode: Episode,
    priced: tuple[TickFidelity | Timeframe, RunFees],
    first_id: int,
    sessions: SessionTable,
) -> RunResult:
    """The episode through the reference engine, on its fidelity and under the run's settings
    and fee table, from flat with the run's cash, its orders numbered from `first_id`."""
    fidelity, fees = priced
    instrument = instrument_parameters(record.instrument)
    tape = episode.tape
    hours = CalendarHours.around(sessions, tape[0].starts_at(), tape[-1].available_at())
    engine = ReferenceEngine(record.config.run_settings(), instrument, fidelity, hours, fees=fees)
    spec = StrategySpec.model_validate(record.strategy.spec)
    template = TemplateStrategy(spec, episode.frame, instrument, sessions)
    return engine.run(
        tape,
        episode.decisions,
        template.on_bar,
        episode.funding,
        cash=episode.cash,
        contract=episode.contract,
        rolls=episode.rolls,
        first_id=first_id,
    )


def _heading(trade: Trade, record: RunRecord) -> str:
    entry = f"{price_text(trade['entry_price'])} on {instant_text(trade['entry_ts'])}"
    out = f"out by {trade['exit_reason']} on {instant_text(trade['exit_ts'])}"
    pnl = f"{money_text(trade['pnl'])} {record.instrument.currency}"
    held = f"{trade['side']} {trade['lots']} {trade['entry_contract']}"
    return f"Trade {trade['entry_order']}: {held} at {entry}, {out}, {pnl}"


def _fill_lines(
    fills: Sequence[FillView], tape: Sequence[Record], orders: pl.DataFrame
) -> list[str]:
    """Each fill with its rule, liquidity, and slippage, and for a stop filled on a bar
    (F-STP-04) that bar, which reached the stop's level on its path or opened past it."""
    bars = {record.ts_close: record for record in tape if isinstance(record, BarRecord)}
    lines = []
    for fill in fills:
        lines.append(f"  {fill_text(fill)}")
        bar = bars.get(fill.ts)
        if bar is None or fill.rule != "F-STP-04":
            continue
        level = orders.filter(pl.col("id") == fill.order).item(0, "price")
        lines.append(f"    {_bar_text(bar)}, {_how_it_reached(bar, fill.side, level)}")
    return lines


def _bar_text(bar: BarRecord) -> str:
    prices = (bar.open, bar.high, bar.low, bar.close)
    open_, high, low, close = (price_text(price) for price in prices)
    span = f"from {instant_text(bar.ts_open)} to {instant_text(bar.ts_close)}"
    return f"the bar {span}, open {open_}, high {high}, low {low}, close {close}"


def _how_it_reached(bar: BarRecord, side: str, level: int) -> str:
    """Whether the bar opened past a stop of `side` at `level`, or reached it on its path."""
    past = bar.open < level if side == "sell" else bar.open > level
    return f"{'opened past' if past else 'reached'} the stop at {price_text(level)}"
