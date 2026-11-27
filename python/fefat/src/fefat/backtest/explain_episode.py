"""The episode `Run.explain` replays (step 2.11, `fefat.backtest.explain`): one trade's
records, from the last one before the decision that placed its entry to the fill that left it
flat, the rolls they cross, the front they start on, the signal rows the template reads, the
decisions, the cash at the first, and the funding paid while it is open. It moved out of
`fefat.backtest.explain` at step 5.9, which grew it past the size of a module."""

import warnings
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

import polars as pl

from fefat.backtest.record import RollRecord, RunRecord
from fefat.market.api import load, roll_calendar
from fefat.market.calendar import SessionTable
from fefat.market.fidelity import TickFidelity
from fefat.market.layout import Partition
from fefat.market.schema import Timeframe
from fefat.market.snapshot import FileDigest, Snapshot
from fefat.market.store import Store
from fefat.reference.rolls import RollRow, rolls_within, tape_across_rolls
from fefat.reference.strategy import Decision, decisions_of
from fefat.reference.tape import FundingRate, Record, stored_bars, tape_of_trades
from fefat.reference.units import instant_text

if TYPE_CHECKING:
    from fefat.backtest.runs import Run

type Trade = dict[str, Any]
type _Records = tuple[tuple[Record, ...], tuple[RollRow, ...], str]
"""An episode's records, the rolls they cross, and the front of the first."""


@dataclass(frozen=True)
class Episode:
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


def episode_of(
    run: "Run",
    trade: Trade,
    priced: tuple[TickFidelity | Timeframe, date],
    pinned: tuple[Store, dict[str, Snapshot]],
    sessions: SessionTable,
) -> Episode:
    """The records, rolls, signal rows, decisions, cash, and funding of the trade's episode, on
    the fidelity its fills priced on, to the trade date of its exit, read from the store's data
    the run pinned, from the decision's trade date or the one before (`_marked`)."""
    fidelity, exit_date = priced
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
    if isinstance(fidelity, Timeframe):
        bars = fidelity

        def read(start: date) -> _Records:
            return _bars(run.record, bars, (start, exit_date), (entered, left))
    else:
        store, snapshots = pinned
        snapshot = snapshots[str(TickFidelity.TRADES)]

        def read(start: date) -> _Records:
            rolls = run.record.rolls
            prints = _prints(trade, decided, (start, exit_date), rolls, (store, snapshot))
            return _cut(prints, entered, left), (), decided["contract"]

    tape, rolls, contract = _marked(read, decided["trade_date"], sessions, entered)
    frame = run.signals.filter(pl.col("ts_close") >= entered, pl.col("trade_date") <= exit_date)
    return Episode(
        tape=tape,
        rolls=rolls,
        contract=contract,
        frame=frame,
        decisions=decisions_of(frame.filter(pl.col("ts_close") <= left)),
        cash=flat["cash"],
        funding=_funding(run.record, tape[0].starts_at(), left),
    )


def _marked(
    read: Callable[[date], "_Records"], first: date, sessions: SessionTable, entered: int
) -> "_Records":
    """The episode's records as `read` gives them from the decision's trade date `first`, where
    they start at a mark, a record available by the decision at `entered`, whose price it reads
    (F-MRK-01); else from the trade date before: a session whose first buckets hold no print or
    bar has no mark of its own by then, and the Rust engine marks it from the session before
    (step 5.9, from the Phase 2 exit's reviews)."""
    found = read(first)
    tape = found[0]
    if tape and tape[0].available_at() <= entered:
        return found
    return read(sessions.preceding(first).trade_date)


def _bars(
    record: RunRecord,
    timeframe: Timeframe,
    dates: tuple[date, date],
    instants: tuple[int, int],
) -> "_Records":
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
