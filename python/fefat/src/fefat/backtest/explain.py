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
snapshots the run's record pins, and its fee table and calendar against those the run's config
gave the engine. Bars and trade prints replay; an episode on TBBO or on two
fidelities, a trade of trade prints across a roll, and a trade entered by reversing a position
are refused (`BACKLOG.md`)."""

import os
import warnings
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

import polars as pl

from fefat.backtest.record import DatasetRecord, RollRecord, RunRecord
from fefat.config import resolve_paths
from fefat.market.api import load, roll_calendar
from fefat.market.calendar import SessionTable
from fefat.market.coverage import session_datasets
from fefat.market.fees import TABLES
from fefat.market.fidelity import TickFidelity, fidelity_in_words, parse_fidelity
from fefat.market.layout import Dataset, Partition, PartitionRequest
from fefat.market.saved_instruments import instrument_table
from fefat.market.schema import Timeframe, parse_schema_name
from fefat.market.snapshot import FileDigest, Snapshot
from fefat.market.store import Store
from fefat.reference.costs import RunFees
from fefat.reference.engine import ReferenceEngine
from fefat.reference.hours import CalendarHours
from fefat.reference.rolls import RollRow, rolls_within, tape_across_rolls
from fefat.reference.run_documents import fees_document, hours_document
from fefat.reference.rust_batch import FillView
from fefat.reference.rust_run import fill_text
from fefat.reference.strategy import Decision, decisions_of
from fefat.reference.tape import BarRecord, FundingRate, Record, stored_bars, tape_of_trades
from fefat.reference.template import TemplateStrategy
from fefat.reference.timeline import RunResult
from fefat.reference.units import instant_text, instrument_parameters, money_text, price_text
from fefat.strategy.spec import StrategySpec

if TYPE_CHECKING:
    from fefat.backtest.runs import Run

type Trade = dict[str, Any]


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


@dataclass(frozen=True)
class _Episode:
    """What the reference replays of a trade: its records, the rolls they cross, the front they
    start on, the signal frame the template reads, the decisions, the cash at the first, and the
    funding paid while it is open."""

    tape: tuple[Record, ...]
    rolls: tuple[RollRow, ...]
    contract: str
    frame: pl.DataFrame
    decisions: tuple[Decision, ...]
    cash: int
    funding: tuple[FundingRate, ...]


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
    snapshots = pinned_snapshots(store, record)
    root = record.instrument.root
    sessions = instrument_table(paths.data_dir).sessions_of(root, paths.cache_dir)
    fees = _the_runs_fees_and_calendar(run, sessions)
    episode = _episode(run, trade, fidelity, exit_date, store, snapshots)
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


def pinned_snapshots(store: Store, record: RunRecord) -> dict[str, Snapshot]:
    """A snapshot of each dataset the run read, by schema, refused unless it is the one the
    run's record pins, and refused when the store holds trades or bars of the run's provider in
    its dates that the run did not read: the data changed since the run otherwise.
    `fidelity_check` reruns a saved run on the data this guards too."""
    snapshots = {}
    for dataset in record.datasets:
        snapshot = store.snapshot(_request(dataset))
        if snapshot.sha256 != dataset.snapshot:
            raise ValueError(
                f"Expected the store's {dataset.schema_name} of {dataset.root} as the run read "
                f"it, snapshot {dataset.snapshot[:12]}, got {snapshot.sha256[:12]}: the data "
                "changed since the run, so run it again first."
            )
        snapshots[dataset.schema_name] = snapshot
    _require_no_dataset_since(store, record)
    return snapshots


def _require_no_dataset_since(store: Store, record: RunRecord) -> None:
    """Refuse a dataset of trades, TBBO, or bars of the run's provider and root with partitions
    in the run's dates that its record does not name, an import since the run, which the engine
    cache a rerun builds would read."""
    first = min(dataset.first for dataset in record.datasets)
    last = max(dataset.last for dataset in record.datasets)
    named = {dataset.schema_name for dataset in record.datasets}
    provider, root = record.config.provider, record.instrument.root
    for dataset in session_datasets(store):
        if (dataset.provider, dataset.root) != (provider, root):
            continue
        request = PartitionRequest(dataset=dataset, start=first, end=last)
        listed = store.list_partitions(dataset)
        if str(dataset.schema_name) not in named and any(
            request.selects(file.partition) for file in listed
        ):
            raise ValueError(
                f"Expected the store's data of {root} as the run read it, got "
                f"{dataset.schema_name} of {root} from {provider} in the run's dates, which it "
                "did not read: it was imported since the run, so run it again first."
            )


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


def _request(dataset: DatasetRecord) -> PartitionRequest:
    named = Dataset(
        provider=dataset.provider,
        schema_name=parse_schema_name(dataset.schema_name),
        root=dataset.root,
    )
    return PartitionRequest(dataset=named, start=dataset.first, end=dataset.last)


def _episode(
    run: "Run",
    trade: Trade,
    fidelity: TickFidelity | Timeframe,
    exit_date: date,
    store: Store,
    snapshots: dict[str, Snapshot],
) -> _Episode:
    """The records, rolls, signal rows, decisions, cash, and funding of the trade's episode."""
    entered, left = trade["entry_decision"], trade["exit_ts"]
    decided = run.signals.filter(pl.col("ts_close") == entered).row(0, named=True)
    account = run.equity(str(run.record.strategy.spec["timeframe"]))
    flat = account.filter(pl.col("ts") == entered).row(0, named=True)
    if flat["position"] != 0:
        raise ValueError(
            f"Expected trade {trade['entry_order']} entered from flat, got it entered by "
            f"reversing a position of {flat['position']} lots, which a replay from flat cannot "
            "give (BACKLOG.md)."
        )
    first = decided["trade_date"]
    if isinstance(fidelity, Timeframe):
        tape, rolls, contract = _bars(run.record, fidelity, (first, exit_date), (entered, left))
    else:
        snapshot = snapshots[str(TickFidelity.TRADES)]
        prints = _prints(trade, decided, (first, exit_date), run.record.rolls, (store, snapshot))
        tape, rolls, contract = _cut(prints, entered, left), (), decided["contract"]
    frame = run.signals.filter(pl.col("ts_close") >= entered, pl.col("trade_date") <= exit_date)
    return _Episode(
        tape=tape,
        rolls=rolls,
        contract=contract,
        frame=frame,
        decisions=decisions_of(frame.filter(pl.col("ts_close") <= left)),
        cash=flat["cash"],
        funding=_funding(run.record, tape[0].starts_at(), left),
    )


def _bars(
    record: RunRecord,
    timeframe: Timeframe,
    dates: tuple[date, date],
    instants: tuple[int, int],
) -> tuple[tuple[Record, ...], tuple[RollRow, ...], str]:
    """The episode's stored bars of `timeframe`, which the engine replayed, not bars `load`
    would build from finer data, spliced as `load` splices them, or of the run's one contract
    unspliced (`RunConfig.contract`), and cut to the episode; the rolls they cross, none on one
    contract; and the front of the first. `load`'s warnings are the run's record's."""
    root, provider = record.instrument.root, record.config.provider
    contract = record.config.contract
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        frame = load(
            root if contract is None else contract,
            str(timeframe),
            *dates,
            fidelity=timeframe,
            provider=provider,
        ).collect()
    if contract is not None:
        return _cut(stored_bars(frame), *instants), (), contract
    calendar = roll_calendar(root, provider=provider)
    bars, _ = tape_across_rolls(frame, calendar)
    tape = _cut(bars, *instants)
    first = frame.filter(pl.col("ts_close") == tape[0].available_at())
    return tape, rolls_within(calendar, tape), first.get_column("contract").item()


def _prints(
    trade: Trade,
    decided: dict[str, Any],
    dates: tuple[date, date],
    rolls: Sequence[RollRecord],
    pinned: tuple[Store, Snapshot],
) -> tuple[Record, ...]:
    """The trade prints of the episode's contract from the run's snapshot, from the last one at
    or before the entry's decision to the exit, cut before they become records: refused for an
    episode that crosses one of the run's rolls, which transfers or, under flatten, closes the
    trade (F-ROL-02, F-ROL-04), since the replay of prints takes one contract's."""
    contract = trade["entry_contract"]
    crossed = [roll for roll in rolls if dates[0] < roll.trade_date <= dates[1]]
    if crossed or {decided["contract"], trade["exit_contract"]} != {contract}:
        across = (
            f"crosses the roll of {crossed[0].trade_date} to {crossed[0].contract}"
            if crossed
            else f"runs from {decided['contract']} to {trade['exit_contract']}"
        )
        raise ValueError(
            f"Expected trade {trade['entry_order']} of trade prints within one front, got an "
            f"episode that {across}: a replay of prints across a roll waits (BACKLOG.md)."
        )
    store, snapshot = pinned
    held = [digest for digest in snapshot.partitions if _holds(digest, contract, dates)]
    frame = pl.concat([store.read_pinned_partition(snapshot, digest) for digest in held])
    entered, left = trade["entry_decision"], trade["exit_ts"]
    before = frame.filter(pl.col("ts_recv") <= entered).get_column("ts_recv").max()
    start = before if isinstance(before, int) else entered
    return tape_of_trades(frame.filter(pl.col("ts_recv").is_between(start, left)))


def _holds(digest: FileDigest, contract: str, dates: tuple[date, date]) -> bool:
    """Whether the pinned partition holds `contract`'s prints on one of `dates`' trade dates."""
    partition = Partition.from_relative_path(PurePosixPath(digest.path))
    key = partition.key
    return partition.contract == contract and isinstance(key, date) and dates[0] <= key <= dates[1]


def _cut(records: Sequence[Record], entered: int, left: int) -> tuple[Record, ...]:
    """The records from the last one available at or before the decision at `entered`, whose
    price the decision reads, to the last available by `left`, the fill that left the trade
    flat."""
    before = [record for record in records if record.available_at() <= entered]
    during = [record for record in records if entered < record.available_at() <= left]
    return (*before[-1:], *during)


def _funding(record: RunRecord, first: int, last: int) -> tuple[FundingRate, ...]:
    """The funding rates the run paid from `first` to `last`, as its config gave the engine,
    each read back through the reference's own model, which refuses a malformed one, and
    written for it in fixed notation, since `str` writes a rate of zero as `0E-9`."""
    rates = (
        FundingRate.model_validate(
            {"ts": instant_text(rate["ts"]), "rate": format(Decimal(rate["rate"]).scaleb(-9), "f")}
        )
        for rate in record.engine_config["funding"]
    )
    return tuple(rate for rate in rates if first <= rate.ts <= last)


def _replayed(
    record: RunRecord,
    episode: _Episode,
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
