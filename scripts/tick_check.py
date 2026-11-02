"""The tick engine checked on Interactive Brokers' prints (step 2.16, `02-engine-and-data.md` §8
items 2 and 4, D-67): `just tick-check` runs this on the store's `ibkr` sessions of MNQZ2026, the
ticks the builder pulls from TWS outside the repository and imports with the `ibkr-ticks`
profile, beside IBKR's own 1-minute bars of the same sessions, and writes
`docs/validation/ibkr-tick-check.md`.

1. Bars: `fefat data verify-bars` of each session, the bars rebuilt from the prints against
   IBKR's own, and IBKR's bars counted against the reference provider's of the same minutes.
2. Differential: step 2.14's three strategies (`scripts/xcheck.py`) under its compatibility
   profile, run by `ff.backtest.run` at fidelity `trades` on the contract unspliced and replayed
   through the Python reference engine on the same prints, every fill identical in the integer
   units of ADR-0019; the 1-minute runs replayed on the sessions' bars as well.
3. Fidelity: the run's fidelity check at one minute, each differing fill classed by
   `fefat.backtest.fidelity_classes` with the reference engine's replay of the prints whose
   stamps fall on a decision's instant moved one nanosecond after it, and how far apart the
   fills lie measured in ticks; none `unknown`, which needs each session on prints' bars to be
   its prints' own, as the bar check shows them.
4. Determinism: each run's key worked out again, its fills on two fresh engine runs and on fresh
   runs of its first sessions, and its prints replayed with those of each instant reversed.

The report holds counts, rates, timestamps, hashes, and tick differences alone: no price leaves
the store (D-21). The trades and classified tables it counts go under
`<FEFAT_HOME>/workspaces/default/tick-check/` for `notebooks/checks/2.16.ipynb`. A store without
the sessions says so and exits 0; a difference without a class leaves the report unwritten and
exits 1.

    uv run python scripts/tick_check.py    # as `just tick-check` runs it; needs your data
"""

import json
import os
import time
import warnings
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path, PurePosixPath
from typing import Any

import fefat_engine
import polars as pl

import fefat as ff
from fefat.backtest import FidelityCheck, Run, RunConfig
from fefat.backtest.explain import pinned_snapshots
from fefat.backtest.fidelity_classes import (
    MATCH,
    RESTAMP,
    TRADE_COLUMNS,
    classify,
)
from fefat.backtest.fidelity_summary import FidelitySummary, summarise
from fefat.backtest.metrics import FidelityEra
from fefat.backtest.run_inputs import RunInputs, run_inputs
from fefat.backtest.runs import run_key
from fefat.config import FefatPaths, resolve_paths
from fefat.market.api import load
from fefat.market.bars_check import ColumnDifference, ComparedBars, verify_bars
from fefat.market.calendar import SessionTable
from fefat.market.engine_cache_index import engine_cache_status
from fefat.market.engine_units import micro_units
from fefat.market.fees import TABLES
from fefat.market.fidelity import TickFidelity
from fefat.market.layout import Dataset, Partition, PartitionRequest
from fefat.market.saved_instruments import instrument_table
from fefat.market.schema import Timeframe, parse_schema_name
from fefat.market.store import Store
from fefat.reference.costs import RunFees
from fefat.reference.engine import ReferenceEngine
from fefat.reference.event_log import EventKind
from fefat.reference.hours import CalendarHours
from fefat.reference.ledger import Fill
from fefat.reference.orders import OrderKind, OrderRole, PositionSide, Side
from fefat.reference.rust_batch import FillView
from fefat.reference.strategy import decisions_of
from fefat.reference.tape import Record, stored_bars, tape_of_trades
from fefat.reference.template import TemplateStrategy
from fefat.reference.timeline import RunResult
from fefat.reference.units import instant_text, instrument_parameters
from fefat.strategy.spec import StrategySpec
from tick_check_report import report_text, unknown_count
from xcheck import (
    UNITS_PER_POINT,
    CrossCheckStrategy,
    EntryKind,
    compatibility_profile,
    signal_strategy,
)

REPOSITORY = Path(__file__).resolve().parents[1]
REPORT = REPOSITORY / "docs" / "validation" / "ibkr-tick-check.md"
WORK_FOLDER = "tick-check"
"""The folder under the workspace for the tables the notebook reads."""
ONE_MINUTE = Timeframe.parse("1m")
NANOSECONDS_PER_SECOND = 1_000_000_000
TRADE_FILLS = ["entry_decision", "side", "entry_ts", "entry_price", "exit_ts", "exit_price"]


@dataclass(frozen=True)
class TickCheck:
    """The sessions checked: one provider's prints and 1-minute bars of one contract, the
    provider whose bars of the same minutes they are counted against, and the strategies."""

    provider: str
    root: str
    contract: str
    reference_provider: str
    strategies: tuple[CrossCheckStrategy, ...]

    def dataset(self, schema: str, provider: str | None = None) -> Dataset:
        """The root's dataset of `schema` from the check's provider, or from `provider`."""
        return Dataset(
            provider=self.provider if provider is None else provider,
            schema_name=parse_schema_name(schema),
            root=self.root,
        )


MNQ_STRATEGIES = (
    CrossCheckStrategy("market", EntryKind.MARKET, 0, None, 40, 40),
    CrossCheckStrategy("limit", EntryKind.LIMIT, 2, 1, 40, 40),
    CrossCheckStrategy("stop", EntryKind.STOP, 2, 1, 40, 40),
)
"""Step 2.14's strategies with its MNQ bracket, 40 ticks from the signal close."""
CHECK = TickCheck(
    provider="ibkr",
    root="MNQ",
    contract="MNQZ2026",
    reference_provider="databento",
    strategies=MNQ_STRATEGIES,
)


@dataclass(frozen=True)
class StrategyRuns:
    """One strategy's runs on the sessions: on prints and on 1-minute bars."""

    definition: CrossCheckStrategy
    strategy: ff.SignalStrategy
    ticks: Run
    minutes: Run

    @property
    def name(self) -> str:
        return self.definition.name

    @property
    def kind(self) -> OrderKind:
        return OrderKind(str(self.definition.entry))


def sessions_in_the_store(store: Store, check: TickCheck) -> list[date]:
    """The trade dates of the contract's prints in the provider's trades dataset."""
    return sorted(
        file.partition.key
        for file in store.list_partitions(check.dataset("trades"))
        if file.partition.contract == check.contract and isinstance(file.partition.key, date)
    )


def profile(check: TickCheck, fidelity: TickFidelity | Timeframe) -> RunConfig:
    """Step 2.14's compatibility profile at `fidelity` on the check's contract."""
    return compatibility_profile(check.provider, check.contract, fidelity)


def backtest(
    check: TickCheck, strategy: ff.SignalStrategy, window: tuple[date, date], config: RunConfig
) -> Run:
    """`ff.backtest.run` of the window, refused unless every fill is on the contract with no
    roll; the default fee table's warnings are the run record's."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        run = ff.backtest.run(strategy, *window, config)
    contracts = run.fills["contract"].unique().to_list()
    if run.record.rolls or contracts not in ([], [check.contract]):
        raise ValueError(
            f"Expected every fill of {check.root} from {window[0]} to {window[1]} on "
            f"{check.contract} and no roll, got the contracts {contracts} and "
            f"{len(run.record.rolls)} rolls in run {run.id}."
        )
    return run


def strategy_runs(
    check: TickCheck, definition: CrossCheckStrategy, window: tuple[date, date], tick: int
) -> StrategyRuns:
    strategy = signal_strategy(check.root, definition, tick)
    return StrategyRuns(
        definition=definition,
        strategy=strategy,
        ticks=backtest(check, strategy, window, profile(check, TickFidelity.TRADES)),
        minutes=backtest(check, strategy, window, profile(check, ONE_MINUTE)),
    )


def era_of(run: Run, day: date) -> FidelityEra:
    """The fidelity era of the run that holds a trade date."""
    for era in run.record.fidelity_eras:
        if era.first <= day <= era.last:
            return era
    raise ValueError(f"Expected {day} in a fidelity era of run {run.id}, got none.")


def tick_sessions(run: Run, sessions: Sequence[date]) -> tuple[date, ...]:
    """The sessions the run filled on trade prints, which must open its window: the reference
    engine replays them from flat with the run's capital and its first order id."""
    days = tuple(day for day in sessions if era_of(run, day).fidelity == TickFidelity.TRADES)
    if not days or days != tuple(sessions[: len(days)]):
        raise ValueError(
            f"Expected the sessions on trade prints to open the window "
            f"{[str(day) for day in sessions]}, got {[str(day) for day in days]} in run "
            f"{run.id}."
        )
    return days


def pinned_prints(store: Store, run: Run, contract: str, days: Sequence[date]) -> pl.DataFrame:
    """The contract's prints of `days` from the trades snapshot the run's record pins, refused
    unless the store still holds them as the run read them (`fefat.backtest.explain`)."""
    snapshot = pinned_snapshots(store, run.record)[str(TickFidelity.TRADES)]
    held = []
    for digest in snapshot.partitions:
        partition = Partition.from_relative_path(PurePosixPath(digest.path))
        if partition.contract == contract and partition.key in days:
            held.append(store.read_pinned_partition(snapshot, digest))
    if not held:
        raise ValueError(
            f"Expected the prints of {contract} on {[str(day) for day in days]} in the trades "
            f"snapshot run {run.id} pins, got none."
        )
    return pl.concat(held)


def restamped(prints: pl.DataFrame, decisions: pl.Series) -> pl.DataFrame:
    """The prints with each one stamped at a decision's instant moved `RESTAMP`, a nanosecond,
    after it, where the 1-minute bars put it: after the decision, in the bar that opens there."""
    at_a_decision = pl.col("ts_recv").is_in(decisions.implode())
    moved = pl.when(at_a_decision).then(pl.col("ts_recv") + RESTAMP).otherwise(pl.col("ts_recv"))
    return prints.with_columns(moved.alias("ts_recv"))


def reversed_seconds(prints: pl.DataFrame) -> pl.DataFrame:
    """The prints with those received at one instant in the reverse of their stored order,
    which F-CLK-03 reads them in."""
    return prints.with_columns((pl.col("sequence").max() - pl.col("sequence")).alias("sequence"))


@dataclass(frozen=True)
class Replays:
    """The reference engine's replays of the runs: the contract, its calendar, the sessions on
    prints, and every session of the window."""

    check: TickCheck
    calendar: SessionTable
    on_prints: tuple[date, ...]
    sessions: tuple[date, ...]

    def replayed(
        self,
        run: Run,
        tape: Sequence[Record],
        fidelity: TickFidelity | Timeframe,
        days: Sequence[date],
    ) -> RunResult:
        """`run`'s strategy on `tape` through the reference engine from flat with the run's
        capital and its fee table, deciding on the run's own signal rows of `days`."""
        record = run.record
        signals = run.signals.filter(pl.col("trade_date").is_in(days))
        parameters = instrument_parameters(record.instrument)
        hours = CalendarHours.around(self.calendar, tape[0].starts_at(), tape[-1].available_at())
        fees = RunFees.of_table(TABLES[record.fee_table.name], record.instrument.root)
        settings = record.config.run_settings()
        engine = ReferenceEngine(settings, parameters, fidelity, hours, fees=fees)
        spec = StrategySpec.model_validate(record.strategy.spec)
        template = TemplateStrategy(spec, signals, parameters, self.calendar)
        return engine.run(
            tape,
            decisions_of(signals),
            template.on_bar,
            cash=micro_units(record.config.capital),
            contract=self.check.contract,
        )

    def bars(self) -> tuple[Record, ...]:
        """The window's stored 1-minute bars of the contract, which the runs on bars filled on."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            frame = load(
                self.check.contract,
                "1m",
                self.sessions[0],
                self.sessions[-1],
                fidelity=ONE_MINUTE,
                provider=self.check.provider,
            )
        return stored_bars(frame.collect())


def replay_all(
    runs: Sequence[StrategyRuns], replays: Replays, prints: pl.DataFrame, decisions: pl.Series
) -> tuple[dict[str, dict[str, RunResult]], dict[str, float]]:
    """Each strategy replayed through the reference engine on the stored prints, the restamped
    prints, the prints with each instant's reversed, and the 1-minute bars, one tape at a time
    since a tape of a million prints is large; with the seconds a replay took on each tape."""
    results: dict[str, dict[str, RunResult]] = {each.name: {} for each in runs}
    seconds: dict[str, float] = {}
    tapes = {
        "prints": prints,
        "restamped": restamped(prints, decisions),
        "reversed": reversed_seconds(prints),
    }
    on_prints = replays.on_prints
    for name, frame in tapes.items():
        tape = tape_of_trades(frame)
        started = time.perf_counter()
        for each in runs:
            replayed = replays.replayed(each.ticks, tape, TickFidelity.TRADES, on_prints)
            results[each.name][name] = replayed
        seconds[name] = (time.perf_counter() - started) / len(runs)
        del tape
    bars = replays.bars()
    for each in runs:
        replayed = replays.replayed(each.minutes, bars, ONE_MINUTE, replays.sessions)
        results[each.name]["bars"] = replayed
    return results, seconds


def require_identical(
    rust: Sequence[FillView], reference: Sequence[FillView], what: str, tick: int
) -> None:
    """Refuse fills the engines do not share (D-10), naming the first apart, the fields that
    differ, and how many ticks apart its prices are."""
    if tuple(rust) == tuple(reference):
        return
    pairs = list(zip(rust, reference, strict=False))
    index = next((at for at, (ours, theirs) in enumerate(pairs) if ours != theirs), len(pairs))
    detail = "one engine's fills end there"
    if index < len(pairs):
        ours, theirs = pairs[index]
        fields = [name for name in FillView._fields if getattr(ours, name) != getattr(theirs, name)]
        apart = (theirs.price - ours.price) / tick
        detail = (
            f"order {ours.order} at {instant_text(ours.ts)} against order {theirs.order} at "
            f"{instant_text(theirs.ts)}, {', '.join(fields)} apart, the reference {apart:+g} "
            "ticks from the Rust engine"
        )
    raise ValueError(
        f"Expected the reference engine's fills of {what} to be the Rust engine's, got "
        f"{len(reference)} against {len(rust)}, apart from fill {index}: {detail}."
    )


def rust_views(run: Run, days: Sequence[date]) -> tuple[FillView, ...]:
    fills = run.fills.filter(pl.col("trade_date").is_in(days))
    return tuple(FillView.of_row(row) for row in fills.iter_rows(named=True))


def reference_views(fills: Sequence[Fill]) -> tuple[FillView, ...]:
    return tuple(FillView.of(fill) for fill in fills)


def differential(
    runs: StrategyRuns, context: "Context", results: dict[str, RunResult]
) -> dict[str, Any]:
    """Item 2: the reference engine's fills against the Rust engine's, refused unless every one
    is identical: the run on prints' on the sessions on prints, and the run on bars' on every
    session. The run on prints fills the other sessions on their bars (D-58), as the run on bars
    does, so its fills there are held to those, order ids apart."""
    days, sessions, tick = context.days, context.sessions, context.tick
    what = f"{runs.name} on {days[0]} to {days[-1]}"
    rust, reference = rust_views(runs.ticks, days), reference_views(results["prints"].fills)
    require_identical(rust, reference, what, tick)
    on_bars, on_bars_too = (
        rust_views(runs.minutes, sessions),
        reference_views(results["bars"].fills),
    )
    every = f"{runs.name} on bars from {sessions[0]} to {sessions[-1]}"
    require_identical(on_bars, on_bars_too, every, tick)
    rest = [day for day in sessions if day not in days]
    ticks_on_bars = without_ids(rust_views(runs.ticks, rest))
    if ticks_on_bars != without_ids(rust_views(runs.minutes, rest)):
        raise ValueError(
            f"Expected the fills of {runs.name} on prints of {[str(day) for day in rest]}, "
            "filled on their bars, to be the run on bars' of those sessions, order ids apart, "
            f"got other fills in run {runs.ticks.id}."
        )
    return {
        "sessions": [str(day) for day in days],
        "prints": context.prints.height,
        "decisions": context.decisions.len(),
        "rust_fills": len(rust),
        "reference_fills": len(reference),
        "identical": identical(rust, reference),
        "bar_sessions": [str(day) for day in sessions],
        "minute_fills": len(on_bars),
        "reference_minute_fills": len(on_bars_too),
        "minute_identical": identical(on_bars, on_bars_too),
        "ticks_on_bars": {"sessions": [str(day) for day in rest], "fills": len(ticks_on_bars)},
    }


def identical(rust: Sequence[FillView], reference: Sequence[FillView]) -> int:
    """How many fills of the two engines, taken in order, are alike field by field."""
    return sum(ours == theirs for ours, theirs in zip(rust, reference, strict=False))


def without_ids(views: Sequence[FillView]) -> tuple[FillView, ...]:
    """The fills with their order ids left out, which number each run's own orders."""
    return tuple(view._replace(order=0) for view in views)


def run_trades(run: Run, days: Sequence[date], kind: OrderKind) -> pl.DataFrame:
    """A run's trades of `days` in the classifier's columns: the bracket's levels from the
    signal row of the entry's decision, a limit's or a stop's level from its order, and the one
    exit's fill with its bar's ambiguity (F-BAR-05)."""
    trades = run.trades.filter(pl.col("entry_trade_date").is_in(days))
    if trades.filter(pl.col("exits") != 1).height:
        raise ValueError(f"Expected one exit a trade in run {run.id}, got trades with more.")
    levels = run.signals.select(
        pl.col("ts_close").alias("entry_decision"), "stop_price", "target_price"
    )
    entries = run.orders.filter(pl.col("role") == str(OrderRole.ENTRY)).select(
        pl.col("id").alias("entry_order"), pl.col("price").alias("entry_level")
    )
    exits = run.fills.filter(pl.col("role") != str(OrderRole.ENTRY)).select(
        pl.col("ts").alias("exit_ts"),
        pl.col("role").alias("exit_reason"),
        pl.col("ambiguous").alias("exit_ambiguous"),
    )
    return (
        trades.join(levels, on="entry_decision", how="left")
        .join(entries, on="entry_order", how="left")
        .join(exits, on=["exit_ts", "exit_reason"], how="left")
        .select(
            "entry_decision",
            "side",
            pl.lit(str(kind)).alias("entry_kind"),
            "entry_ts",
            "entry_price",
            "entry_level",
            "exit_ts",
            pl.col("exit_price").round().cast(pl.Int64),
            "exit_reason",
            "exit_ambiguous",
            "stop_price",
            "target_price",
        )
        .cast(TRADE_COLUMNS)
        .sort("entry_decision")
    )


def replay_trades(result: RunResult, signals: pl.DataFrame, kind: OrderKind) -> pl.DataFrame:
    """The reference engine's trades in the classifier's columns, at the replay's own instants.
    It gives no levels: the runs on bars give them, reading the same marks."""
    placed = {line.order: line.ts for line in result.log.entries if line.kind is EventKind.PLACED}
    levels = {
        decision: (stop, target)
        for decision, stop, target in signals.select(
            "ts_close", "stop_price", "target_price"
        ).rows()
    }
    rows = []
    for entry, exit in entries_and_exits(result.fills):
        decision = placed[entry.order]
        stop, target = levels[decision]
        long = entry.side is Side.BUY
        rows.append(
            {
                "entry_decision": decision,
                "side": str(PositionSide.LONG if long else PositionSide.SHORT),
                "entry_kind": str(kind),
                "entry_ts": entry.ts,
                "entry_price": entry.price,
                "entry_level": None,
                "exit_ts": exit.ts,
                "exit_price": exit.price,
                "exit_reason": str(exit.role),
                "exit_ambiguous": False,
                "stop_price": stop,
                "target_price": target,
            }
        )
    return pl.DataFrame(rows, schema=TRADE_COLUMNS)


def entries_and_exits(fills: Sequence[Fill]) -> list[tuple[Fill, Fill]]:
    """The fills as trades of one entry and one exit each, as the strategies trade."""
    entries, exits = list(fills[::2]), list(fills[1::2])
    paired = len(entries) == len(exits)
    if (
        not paired
        or any(fill.role is not OrderRole.ENTRY for fill in entries)
        or any(fill.role is OrderRole.ENTRY for fill in exits)
    ):
        raise ValueError(
            f"Expected the reference engine's fills in pairs of an entry and an exit, got the "
            f"roles {[str(fill.role) for fill in fills[:12]]}."
        )
    return list(zip(entries, exits, strict=True))


def fidelity(
    runs: StrategyRuns,
    trades: tuple[pl.DataFrame, pl.DataFrame],
    results: dict[str, RunResult],
    tick: int,
) -> tuple[pl.DataFrame, pl.DataFrame, dict[str, Any]]:
    """Item 3: the trades on prints, the restamped replay's, and those on bars, `trades` holding
    the first and the last, classified and held to the run's own fidelity check at one minute;
    the restamped replay's against those on bars classified alone, the differences the decision
    second leaves, each of which needs a class of the bar's path or a cascade too; and how far
    apart the fills lie."""
    on_prints, on_bars = trades
    replayed = replay_trades(results["restamped"], runs.ticks.signals, runs.kind)
    classified = classify(on_prints, replayed, on_bars, tick)
    beside_bars = classify(replayed, replayed, on_bars, tick)
    summary, restamped_summary = summarise(classified), summarise(beside_bars)
    facts = {
        "check": reconciled(runs.ticks, classified, summary),
        **asdict(summary),
        "restamped": {
            "trades_apart": sum(restamped_summary.trades_by_class.values()),
            "trades_by_class": restamped_summary.trades_by_class,
            "unknown": restamped_summary.unknown,
        },
        "measured": measured(classified),
        "examples": examples(classified),
    }
    return classified, beside_bars, facts


def reconciled(run: Run, classified: pl.DataFrame, summary: FidelitySummary) -> dict[str, Any]:
    """The run's fidelity check at one minute (`fefat.backtest.fidelity`), refused unless its
    rerun is the 1-minute run of the tick sessions, pair for pair and tick for tick."""
    check = run.metrics.fidelity_check
    if not isinstance(check, FidelityCheck):
        raise ValueError(f"Expected the fidelity check of run {run.id}, got {check!r}.")
    rerun = check.at_one_minute
    theirs = {
        (_nanoseconds(moved.entry_decision), str(moved.side)): (
            -moved.entry_ticks,
            None if moved.exit_ticks is None else -moved.exit_ticks,
        )
        for moved in rerun.fill_prices
    }
    paired = classified.filter(pl.col("in_ticks") & pl.col("in_minutes"))
    columns = ("entry_decision", "side", "entry_ticks", "exit_ticks")
    ours = {
        (decision, side): (entry, exit)
        for decision, side, entry, exit in paired.select(columns).rows()
    }
    counts = (check.baseline.trades, rerun.outcome.trades)
    if theirs != ours or counts != (summary.tick_trades, summary.minute_trades):
        raise ValueError(
            f"Expected run {run.id}'s fidelity check at one minute to be the 1-minute run of its "
            f"tick sessions, got {len(theirs)} pairs and the trades {counts} against "
            f"{len(ours)} pairs and {(summary.tick_trades, summary.minute_trades)}."
        )
    return {
        "first": str(check.first),
        "last": str(check.last),
        "tick_trades": check.baseline.trades,
        "minute_trades": rerun.outcome.trades,
        "pairs": len(rerun.fill_prices),
        "moved": sum(ticks != (0, 0) for ticks in theirs.values()),
        "unmatched": rerun.unmatched_trades,
        "extra": rerun.extra_trades,
    }


def _nanoseconds(instant: datetime) -> int:
    return int(instant.timestamp()) * NANOSECONDS_PER_SECOND


def examples(classified: pl.DataFrame) -> list[dict[str, Any]]:
    """The first trade of each class, without prices."""
    differing = classified.filter(pl.col("outcome") != MATCH)
    firsts = differing.group_by("outcome", maintain_order=True).first().sort("outcome")
    return [
        {
            "outcome": row["outcome"],
            "decision": instant_text(row["entry_decision"]),
            "side": row["side"],
            "entry_ticks": row["entry_ticks"],
            "exit_ticks": row["exit_ticks"],
            "note": row["note"],
        }
        for row in firsts.iter_rows(named=True)
    ]


def measured(classified: pl.DataFrame) -> dict[str, Any]:
    """How far apart the differing fills of the matched pairs lie, by class, in ticks: how many,
    their mean, and the largest; and how many ticks more the pairs made on prints than on bars,
    a lot each, long and short alike."""
    paired = classified.filter(pl.col("in_ticks") & pl.col("in_minutes"))
    legs = [
        paired.select(
            pl.col(f"{leg}_outcome").alias("outcome"), pl.col(f"{leg}_ticks").abs().alias("ticks")
        )
        for leg in ("entry", "exit")
    ]
    apart = pl.concat(legs).filter(pl.col("outcome") != str(MATCH))
    by_class = (
        apart.group_by("outcome")
        .agg(
            pl.len().alias("fills"),
            pl.col("ticks").mean().alias("mean"),
            pl.col("ticks").max().alias("largest"),
        )
        .sort("outcome")
    )
    sign = pl.when(pl.col("side") == str(PositionSide.LONG)).then(1).otherwise(-1)
    net = paired.select((sign * (pl.col("exit_ticks") - pl.col("entry_ticks"))).sum()).item()
    return {"pairs": paired.height, "net_ticks": int(net), "by_class": by_class.to_dicts()}


def fresh_fills_hash(inputs: RunInputs, paths: FefatPaths) -> str:
    """The hash of a run's fills straight from the engine, never a saved run read back."""
    caches = [str(folder) for folder in inputs.cache_paths(paths)]
    replay = str(inputs.config.replay)
    outputs = fefat_engine.run_signal_backtest(
        inputs.spec_json(), inputs.signals, caches, inputs.config_json(), replay
    )
    return fefat_engine.table_hash(pl.DataFrame(outputs["fills"]))


def determinism(
    check: TickCheck,
    runs: StrategyRuns,
    window: tuple[date, date],
    sessions: Sequence[date],
    paths: FefatPaths,
) -> dict[str, Any]:
    """Item 4: the run's key worked out again from its inputs, its fills on two fresh engine
    runs and as saved, and fresh runs of its first sessions against its own fills of them,
    refused unless every one agrees."""
    config = profile(check, TickFidelity.TRADES)
    inputs = run_inputs(runs.strategy, *window, config, paths)
    key = run_key(inputs, fefat_engine.table_hash(inputs.signals))
    first, second = (fresh_fills_hash(inputs, paths) for _ in "ab")
    prefixes = []
    for through in sessions[:-1]:
        prefix = fresh_fills_hash(
            run_inputs(runs.strategy, window[0], through, config, paths), paths
        )
        whole = runs.ticks.fills.filter(pl.col("trade_date") <= through)
        prefixes.append(
            {"through": str(through), "equal": prefix == fefat_engine.table_hash(whole)}
        )
    determined = {
        "run_key": runs.ticks.hash,
        "key_again": key,
        "fills_hash": first,
        "second_fills_hash": second,
        "saved_fills_hash": fefat_engine.table_hash(runs.ticks.fills),
        "prefixes": prefixes,
    }
    require_deterministic(runs.name, determined)
    return determined


def require_deterministic(name: str, determined: dict[str, Any]) -> None:
    """Refuse a run whose key worked out again, second fresh run, saved fills, or runs of its
    first sessions are not its own (`02` §8 item 3)."""
    fills = determined["fills_hash"]
    checks = [
        ("its key worked out again", determined["key_again"] == determined["run_key"]),
        ("a second fresh run", determined["second_fills_hash"] == fills),
        ("its saved fills", determined["saved_fills_hash"] == fills),
        *(
            (f"its run through {prefix['through']}", prefix["equal"])
            for prefix in determined["prefixes"]
        ),
    ]
    apart = [what for what, alike in checks if not alike]
    if apart:
        raise ValueError(
            f"Expected the run of {name} to be the same on {', '.join(apart)}, got other "
            "hashes: the engine is not deterministic on these prints."
        )


def shared_seconds(
    runs: StrategyRuns,
    on_prints: pl.DataFrame,
    context: "Context",
    reversed_result: RunResult,
) -> dict[str, int]:
    """The run's fills on prints whose instant holds more than one print, and how its trades on
    prints, `on_prints`, and the reference engine's with each instant's prints reversed part:
    the run's that the reversed order makes otherwise and the reversed order's own (F-CLK-03)."""
    per_instant = context.prints.group_by("ts_recv").agg(pl.len().alias("prints"))
    fills = runs.ticks.fills.filter(pl.col("trade_date").is_in(context.days))
    counted = fills.join(per_instant, left_on="ts", right_on="ts_recv", how="left")
    columns = [*TRADE_FILLS, "exit_reason"]
    stored = on_prints.select(columns)
    reversed_trades = replay_trades(reversed_result, runs.ticks.signals, runs.kind).select(columns)
    return {
        "fills": fills.height,
        "fills_in_shared_seconds": counted.filter(pl.col("prints") > 1).height,
        "trades": stored.height,
        "trades_reversed_otherwise": stored.join(reversed_trades, on=columns, how="anti").height,
        "reversed_trades_of_its_own": reversed_trades.join(stored, on=columns, how="anti").height,
    }


def session_facts(
    store: Store, check: TickCheck, sessions: Sequence[date], run: Run, paths: FefatPaths
) -> list[dict[str, Any]]:
    """Each session: its prints, the level the run filled it on, and the reason the engine
    cache gives for leaving its prints out, where it does (D-56, D-58)."""
    left_out = {
        day.trade_date: {str(level): reason for level, reason in day.left_out.items()}
        for month in engine_cache_status(paths.cache_dir, check.root)
        if month.provider == check.provider and month.index.contract == check.contract
        for day in month.index.trade_dates
    }
    facts = []
    for day in sessions:
        partition = Partition(dataset=check.dataset("trades"), contract=check.contract, key=day)
        prints = store.scan_partition(partition).select(pl.len()).collect().item()
        facts.append(
            {
                "trade_date": str(day),
                "prints": prints,
                "fidelity": str(era_of(run, day).fidelity),
                "left_out": left_out.get(day, {}).get(str(TickFidelity.TRADES)),
            }
        )
    return facts


def bars_facts(store: Store, check: TickCheck, day: date, paths: FefatPaths) -> dict[str, Any]:
    """Item 1 of a session: the bars rebuilt from its prints against the provider's own, as
    `fefat data verify-bars` compares them, and the provider's bars against the reference
    provider's."""
    report = verify_bars(store, check.root, day, paths.cache_dir)
    found = [
        comparison
        for comparison in report.comparisons
        if isinstance(comparison, ComparedBars)
        and comparison.provider == check.provider
        and [str(schema) for schema in comparison.route] == ["trades", "ohlcv-1m"]
    ]
    if len(found) != 1:
        raise ValueError(
            f"Expected the {check.provider} bars of {check.root} on {day} rebuilt from its "
            f"prints, got: {report.summary().splitlines()[0]}"
        )
    (rebuilt,) = found
    columns = {
        difference.column if isinstance(difference, ColumnDifference) else "one side only"
        for difference in rebuilt.differences
    }
    return {
        "trade_date": str(day),
        "rebuilt": {
            "compared": rebuilt.bars_compared,
            "differences": len(rebuilt.differences),
            "columns": sorted(columns),
            "minutes": sorted({clock(difference.ts_open) for difference in rebuilt.differences}),
        },
        "reference": against_the_reference(store, check, day),
    }


def require_own_bars(bars: Sequence[dict[str, Any]], days: Sequence[date]) -> None:
    """Refuse the classes unless every session on prints has bars that are its prints' own, as
    the bar check rebuilds them: only then do the restamped replay and the run on bars read the
    same marks (F-ENT-02, F-MRK-01) and the same prints in each bar."""
    on_prints = {str(day) for day in days}
    for row in bars:
        rebuilt = row["rebuilt"]
        if row["trade_date"] in on_prints and rebuilt["differences"]:
            raise ValueError(
                f"Expected the 1-minute bars of {row['trade_date']}, a session on prints, to be "
                f"its prints' own, got {rebuilt['differences']} differences "
                f"({', '.join(rebuilt['columns'])} at {', '.join(rebuilt['minutes'])}): the "
                "classes hold the prints to their own bars."
            )


def clock(instant: int) -> str:
    """A UTC instant's time of day, such as 20:59Z."""
    return datetime.fromtimestamp(instant // NANOSECONDS_PER_SECOND, tz=UTC).strftime("%H:%MZ")


def against_the_reference(store: Store, check: TickCheck, day: date) -> dict[str, Any] | None:
    """The provider's 1-minute bars of the session against the reference provider's of the same
    minutes, those after the reference's last bar of it left out; None where the reference holds
    no bar of the contract that session."""
    if not reference_holds(store, check, day):
        return None
    ours = minute_bars(check, check.provider, day)
    theirs = minute_bars(check, check.reference_provider, day)
    last = last_close(theirs)
    joined = ours.join(theirs, on="ts_close", how="full", coalesce=True, suffix="_reference")
    joined = joined.filter(pl.col("ts_close") <= last)
    both = joined.filter(pl.col("volume").is_not_null() & pl.col("volume_reference").is_not_null())
    prices = ("open", "high", "low", "close")
    priced_apart = pl.any_horizontal(pl.col(name) != pl.col(f"{name}_reference") for name in prices)
    volume, reference_volume = (int(both[name].sum()) for name in ("volume", "volume_reference"))
    return {
        "provider": check.reference_provider,
        "both": both.height,
        "alone": joined.filter(pl.col("volume_reference").is_null()).height,
        "reference_alone": joined.filter(pl.col("volume").is_null()).height,
        "volume_differs": both.filter(pl.col("volume") != pl.col("volume_reference")).height,
        "price_differs": both.filter(priced_apart).height,
        "volume_share": volume / reference_volume if reference_volume else None,
        "ends": clock(last) if last < last_close(ours) else None,
    }


def reference_holds(store: Store, check: TickCheck, day: date) -> bool:
    """Whether the reference provider's 1-minute bars hold a bar of the contract on the trade
    date: a month partition can cover the date while its data ends before it."""
    dataset = check.dataset("ohlcv-1m", check.reference_provider)
    request = PartitionRequest(dataset=dataset, start=day, end=day)
    selected = any(request.selects(file.partition) for file in store.list_partitions(dataset))
    if not selected:
        return False
    rows = store.scan_contracts(request).filter(pl.col("contract") == check.contract)
    return rows.select(pl.len()).collect().item() > 0


def last_close(bars: pl.DataFrame) -> int:
    """The close of the last of the bars."""
    last = bars.get_column("ts_close").max()
    if not isinstance(last, int):
        raise ValueError(f"Expected the bars' last close in nanoseconds, got {last!r}.")
    return last


def minute_bars(check: TickCheck, provider: str, day: date) -> pl.DataFrame:
    """A provider's stored 1-minute bars of the contract on a trade date, its empty buckets left
    out."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        bars = load(check.contract, "1m", day, day, fidelity=ONE_MINUTE, provider=provider)
    return (
        bars.filter(~pl.col("zero_volume"))
        .select("ts_close", "open", "high", "low", "close", "volume")
        .collect()
    )


def decision_second(prints: pl.DataFrame, decisions: pl.Series) -> dict[str, int]:
    """How many decisions have prints stamped at their own instant, and how many prints."""
    stamped = prints.filter(pl.col("ts_recv").is_in(decisions.implode()))
    return {
        "decisions": decisions.len(),
        "with_prints": int(decisions.is_in(stamped.get_column("ts_recv").implode()).sum()),
        "prints": stamped.height,
        "of_prints": prints.height,
    }


@dataclass(frozen=True)
class Context:
    """What every strategy's items read: the check, the sessions of the window, the reference
    engine's replays of the tick sessions, their prints and decision instants, the instrument's
    tick, and FEFAT's folders."""

    check: TickCheck
    sessions: tuple[date, ...]
    replays: Replays
    prints: pl.DataFrame
    decisions: pl.Series
    tick: int
    paths: FefatPaths

    @property
    def window(self) -> tuple[date, date]:
        return self.sessions[0], self.sessions[-1]

    @property
    def days(self) -> tuple[date, ...]:
        """The sessions on prints."""
        return self.replays.on_prints


def strategy_facts(
    each: StrategyRuns, results: dict[str, RunResult], context: Context, work: Path
) -> dict[str, Any]:
    """Items 2 to 4 of one strategy, with its tables for the notebook written to `work`: the
    reference engine's fills first, which refuse the rest when they are not the Rust engine's."""
    days, tick = context.days, context.tick
    differential_facts = differential(each, context, results)
    trades = (run_trades(each.ticks, days, each.kind), run_trades(each.minutes, days, each.kind))
    classified, beside_bars, fidelity_facts = fidelity(each, trades, results, tick)
    classified.write_parquet(work / f"classified_{each.name}.parquet")
    beside_bars.write_parquet(work / f"classified_{each.name}_restamped.parquet")
    for name, table in zip(("ticks", "minutes"), trades, strict=True):
        table.write_parquet(work / f"trades_{each.name}_{name}.parquet")
    window, sessions = context.window, context.sessions
    determined = determinism(context.check, each, window, sessions, context.paths)
    determined["shared_seconds"] = shared_seconds(each, trades[0], context, results["reversed"])
    return {
        "name": each.name,
        "definition": each.definition.record(),
        "differential": differential_facts,
        "fidelity": fidelity_facts,
        "determinism": determined,
    }


def checked_facts(
    check: TickCheck, store: Store, paths: FefatPaths, sessions: list[date], work: Path
) -> dict[str, Any]:
    """Every item's facts, with the tables the notebook reads written to `work`."""
    window = (sessions[0], sessions[-1])
    tick = int(ff.instruments.get(check.root).tick_size * UNITS_PER_POINT)
    runs = [strategy_runs(check, definition, window, tick) for definition in check.strategies]
    first = runs[0].ticks
    days = tick_sessions(first, sessions)
    bars = [bars_facts(store, check, day, paths) for day in sessions]
    require_own_bars(bars, days)
    prints = pinned_prints(store, first, check.contract, days)
    decisions = first.signals.filter(pl.col("trade_date").is_in(days)).get_column("ts_close")
    table = instrument_table(paths.data_dir).sessions_of(check.root, paths.cache_dir)
    replays = Replays(check=check, calendar=table, on_prints=days, sessions=tuple(sessions))
    results, seconds = replay_all(runs, replays, prints, decisions)
    context = Context(check, tuple(sessions), replays, prints, decisions, tick, paths)
    strategies = [strategy_facts(each, results[each.name], context, work) for each in runs]
    return {
        **run_facts(check, first, window),
        "tick": tick,
        "tick_sessions": [str(day) for day in days],
        "sessions": session_facts(store, check, sessions, first, paths),
        "bars": bars,
        "decision_second": decision_second(prints, decisions),
        "replay_seconds": seconds,
        "strategies": strategies,
    }


def run_facts(check: TickCheck, run: Run, window: tuple[date, date]) -> dict[str, Any]:
    """What the runs share: the check, the versions, the window, the datasets with their
    snapshots, and the profile."""
    record = run.record
    return {
        "written": str(date.today()),
        "check": {
            "provider": check.provider,
            "root": check.root,
            "contract": check.contract,
            "reference_provider": check.reference_provider,
        },
        "versions": record.versions.model_dump(),
        "engine_version": ff.engine_info().version,
        "sdk_version": ff.__version__,
        "window": {"first": str(window[0]), "last": str(window[1])},
        "datasets": [
            {
                "dataset": f"{dataset.provider}/{dataset.schema_name}/root={dataset.root}",
                "first": str(dataset.first),
                "last": str(dataset.last),
                "sha256": dataset.snapshot,
            }
            for dataset in record.datasets
        ],
        "profile": {
            "latency_ms": record.config.latency_ms,
            "slippage_ticks": record.config.slippage_ticks.model_dump(),
            "limit_fill": str(record.config.limit_fill),
            "fee_table": record.fee_table.name,
        },
    }


def published(text: str, unknown: int, report: Path) -> int:
    """Write the report, unless a difference has no class: then say so and exit 1, the report
    left as it was."""
    if unknown:
        print(
            f"{unknown} differences without a class: the report is not written; the tables "
            f"classified_<strategy>.parquet and classified_<strategy>_restamped.parquet in the "
            f"workspace's {WORK_FOLDER} folder show them."
        )
        return 1
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(text, encoding="utf-8", newline="\n")
    print(f"Wrote {report}")
    return 0


def main() -> int:
    paths = resolve_paths(os.environ)
    store = Store(paths.data_dir)
    check = CHECK
    sessions = sessions_in_the_store(store, check)
    if not sessions:
        print(
            f"No {check.provider} trades of {check.contract} in the store: the tick check is "
            "skipped."
        )
        return 0
    print(f"Checking {check.contract} on {len(sessions)} {check.provider} sessions")
    work = paths.workspace_dir / WORK_FOLDER
    work.mkdir(parents=True, exist_ok=True)
    (work / "facts.json").unlink(missing_ok=True)
    facts = checked_facts(check, store, paths, sessions, work)
    (work / "facts.json").write_text(json.dumps(facts, indent=2) + "\n", encoding="utf-8")
    text = report_text(facts)
    (work / REPORT.name).write_text(text, encoding="utf-8", newline="\n")
    return published(text, unknown_count(facts), REPORT)


if __name__ == "__main__":
    raise SystemExit(main())
