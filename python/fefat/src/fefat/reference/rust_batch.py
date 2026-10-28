"""The batch `fefat-cli run` reads and writes (steps 2.6 and 2.7), a development tool of the
repository until the Python bindings of step 2.10: cases, each a scenario, the hours its market
trades in, and how the Rust engine replays it, as `run.json` and the Arrow files of their records
and signal rows; and the outputs read back as each case's fills, event log, and ledger at its end,
in the reference engine's terms. The formats are those `engine/crates/fefat-cli/src/run/` reads
and writes. A case's records carry the trade date of the session they fall in, or of the last
one opened before them (`SessionTable.assign_trade_dates_or_previous`, as `load` dates them),
and, for an instrument without a calendar, the UTC day they start on. A case that skips also
carries the coarser bars its records make, in buckets of the UTC clock, so that the Rust engine
descends from them (`02` §4)."""

import io
import itertools
import json
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, NamedTuple

import polars as pl

from fefat.market.calendar import SessionTable
from fefat.market.fidelity import TickFidelity
from fefat.market.schema import Timeframe, TimeUnit
from fefat.reference.event_log import LogEntry
from fefat.reference.hours import AlwaysOpen, CalendarHours
from fefat.reference.ledger import Fill
from fefat.reference.orders import Order, PricedOrder
from fefat.reference.scenario_runner import held_lots
from fefat.reference.scenarios import AnyScenario, TemplateScenario
from fefat.reference.settings import RunSettings
from fefat.reference.tape import BarRecord, Record, TbboRecord
from fefat.reference.time_rules import with_time_rules
from fefat.reference.units import (
    CAPITAL,
    PRICE_DECIMALS,
    InstrumentParameters,
    instrument_parameters,
    lots_of,
)
from fefat.strategy import exits as rules
from fefat.strategy.spec import StrategySpec

NANOSECONDS_PER_DAY = 86_400 * 1_000_000_000
_SIGNALS = ("ts_close", "long_entry", "short_entry", "long_exit", "short_exit")
_OPTIONAL_SIGNALS = (
    "entry_price",
    "stop_price",
    "target_price",
    "trail_ref",
    "size_mult",
    "wake",
)
_TIME_COLUMNS = ("flat_by", "in_window", "session_end", "week_end")
_FLAGS = ("ambiguous", "size_exceeded")
_SECOND = Timeframe(count=1, unit=TimeUnit.SECOND)
_MINUTE = Timeframe(count=1, unit=TimeUnit.MINUTE)
_FIVE_MINUTES = Timeframe(count=5, unit=TimeUnit.MINUTE)


class Replay(StrEnum):
    """How the Rust engine replays a case: every record in turn, or skipping the blocks of
    records that no order can act on, by the coarser bars above them (`02` §4)."""

    FULL = "full"
    SKIPPING = "skipping"


@dataclass(frozen=True, slots=True)
class EngineCase:
    """A scenario as both engines run it: with the hours its market trades in, for an instrument
    of the table its session table, which a template's flat-by and the records' trade dates read,
    and how the Rust engine replays it."""

    scenario: AnyScenario
    hours: AlwaysOpen | CalendarHours
    sessions: SessionTable | None = None
    replay: Replay = Replay.FULL

    def coarser_levels(self) -> tuple[Timeframe, ...]:
        """The bar levels a skipping case adds above its tape, from which the Rust engine
        descends: seconds and minutes above ticks, minutes above seconds, and five minutes above
        minutes; none for a full replay or coarser bars."""
        if self.replay is Replay.FULL:
            return ()
        fidelity = self.scenario.fidelity
        if isinstance(fidelity, TickFidelity):
            return (_SECOND, _MINUTE)
        if fidelity == _SECOND:
            return (_MINUTE,)
        if fidelity == _MINUTE:
            return (_FIVE_MINUTES,)
        return ()


class FillView(NamedTuple):
    """What the engines compare of a fill (F-TAG-01), but its fee, which costs bring in step 2.9:
    the order, when, at what price, the rule that priced it, its flags, its liquidity, its
    slippage in ticks, its lots, side, and role, its fidelity, and what its value moved the cash
    by (F-FEE-03)."""

    order: int
    ts: int
    price: int
    rule: str
    flags: tuple[str, ...]
    liquidity: str
    slippage_ticks: int
    lots: int
    side: str
    role: str
    fidelity: str
    cash: int

    @classmethod
    def of(cls, fill: Fill) -> "FillView":
        """The reference engine's fill."""
        return cls(
            fill.order,
            fill.ts,
            fill.price,
            fill.rule,
            tuple(sorted(str(flag) for flag in fill.flags)),
            str(fill.liquidity),
            fill.slippage_ticks,
            fill.lots,
            str(fill.side),
            str(fill.role),
            str(fill.fidelity),
            fill.cash,
        )

    @classmethod
    def of_row(cls, row: dict[str, Any]) -> "FillView":
        """A row of `fills.arrow`."""
        flags = tuple(sorted(flag for flag in _FLAGS if row[flag]))
        return cls(
            row["order"],
            row["ts"],
            row["price"],
            row["rule"],
            flags,
            row["liquidity"],
            row["slippage_ticks"],
            row["lots"],
            row["side"],
            row["role"],
            row["fidelity"],
            row["cash"],
        )


class LogView(NamedTuple):
    """What the engines compare of an entry of the event log: when, what, of which order, and
    under which rule; the words of its text may differ."""

    ts: int
    kind: str
    order: int | None
    rule: str | None

    @classmethod
    def of(cls, entry: LogEntry) -> "LogView":
        """The reference engine's entry."""
        return cls(entry.ts, str(entry.kind), entry.order, entry.rule)


@dataclass(frozen=True, slots=True)
class RustOutcome:
    """A case's outputs from `fefat-cli run`: its fills, its event log, its ledger at its end,
    the lots held, positive long, and the cash in micro-units, and the fills it flagged
    ambiguous, which the run counts (F-BAR-05)."""

    fills: tuple[FillView, ...]
    log: tuple[LogView, ...]
    position: int
    cash: int
    ambiguous_fills: int


def write_batch(cases: Sequence[EngineCase], folder: Path) -> None:
    """The batch of `cases` in `folder`: `run.json`, and the Arrow files of their records, a file
    per level, and of their signal rows, each row tagged with its case's place in `run.json`."""
    folder.mkdir(parents=True)
    manifest = {"cases": [_case_document(case) for case in cases]}
    (folder / "run.json").write_text(json.dumps(manifest), encoding="utf-8")
    for level, frame in _tapes(cases).items():
        frame.write_ipc(folder / f"{level}.arrow", compression="uncompressed")
    signals = _signal_rows(cases)
    if signals is not None:
        signals.write_ipc(folder / "signals.arrow", compression="uncompressed")


def read_outcomes(folder: Path, cases: int) -> list[RustOutcome]:
    """Each case's fills, event log, and ledger from the outputs of `fefat-cli run`."""
    fills, log, ledgers = (_read(folder / f"{name}.arrow") for name in ("fills", "log", "ledger"))
    outcomes = []
    for case in range(cases):
        of_case = pl.col("case") == case
        rows = fills.filter(of_case).iter_rows(named=True)
        entries = log.filter(of_case).iter_rows(named=True)
        ledger = ledgers.filter(of_case).row(0, named=True)
        outcomes.append(
            RustOutcome(
                fills=tuple(FillView.of_row(row) for row in rows),
                log=tuple(
                    LogView(entry["ts"], entry["kind"], entry["order"], entry["rule"])
                    for entry in entries
                ),
                position=ledger["position"],
                cash=ledger["cash"],
                ambiguous_fills=ledger["ambiguous_fills"],
            )
        )
    return outcomes


@dataclass(frozen=True, slots=True)
class CacheCase:
    """A template run over an engine cache's contract folder (step 2.5), open around the clock,
    as `fefat-cli run` reads one: the timed runs of step 2.7 on a generated year. `signals` is a
    signal frame of the template's columns at raw prices."""

    id: str
    folder: Path
    fidelity: TickFidelity | Timeframe
    instrument: InstrumentParameters
    settings: RunSettings
    strategy: StrategySpec
    signals: pl.DataFrame
    replay: Replay


def write_cache_batch(cases: Sequence[CacheCase], folder: Path) -> None:
    """The batch of `cases` in `folder`: `run.json`, and their signal rows in `signals.arrow`,
    each row tagged with its case's place in `run.json`."""
    folder.mkdir(parents=True)
    documents = [_cache_case_document(case) for case in cases]
    (folder / "run.json").write_text(json.dumps({"cases": documents}), encoding="utf-8")
    frames = [
        _template_rows(number, case.strategy, case.signals, None)
        for number, case in enumerate(cases)
    ]
    signals = pl.concat(frames, how="diagonal")
    signals.write_ipc(folder / "signals.arrow", compression="uncompressed")


def _cache_case_document(case: CacheCase) -> dict[str, object]:
    return {
        "id": case.id,
        "fidelity": str(case.fidelity),
        "replay": str(case.replay),
        "contract": case.folder.name,
        "instrument": _instrument_document(case.instrument),
        "settings": _settings_document(case.settings),
        "hours": {"kind": "always"},
        "capital": CAPITAL,
        "position": None,
        "market_data": {"kind": "cache", "folder": str(case.folder)},
        "decisions": {"kind": "template", "strategy": case.strategy.document()},
    }


def _case_document(case: EngineCase) -> dict[str, object]:
    scenario = case.scenario
    parameters = instrument_parameters(scenario.instrument)
    levels = [str(scenario.fidelity), *(str(level) for level in case.coarser_levels())]
    return {
        "id": scenario.id,
        "fidelity": str(scenario.fidelity),
        "replay": str(case.replay),
        "contract": scenario.id,
        "instrument": _instrument_document(parameters),
        "settings": _settings_document(scenario.settings),
        "hours": _hours_document(case.hours),
        "capital": CAPITAL,
        "position": _position_document(scenario),
        "market_data": {"kind": "tape", "levels": levels},
        "decisions": _decisions_document(scenario, parameters),
    }


def _instrument_document(parameters: InstrumentParameters) -> dict[str, object]:
    return {
        "tick_size": parameters.tick,
        "money_per_point": parameters.money_per_point,
        "lot_step": int(parameters.lot_step.scaleb(PRICE_DECIMALS)),
    }


def _settings_document(settings: RunSettings) -> dict[str, object]:
    return {
        "latency_ms": settings.latency_ms,
        "slippage_ticks": {
            "market": settings.slippage_ticks.market,
            "stop": settings.slippage_ticks.stop,
        },
        "limit_fill": str(settings.limit_fill),
    }


def _hours_document(hours: AlwaysOpen | CalendarHours) -> dict[str, object]:
    if isinstance(hours, AlwaysOpen):
        return {"kind": "always"}
    sessions = [
        {
            "open": session.open,
            "close": session.close,
            "halts": [{"start": halt.start, "end": halt.end} for halt in session.halts],
        }
        for session in hours.sessions()
    ]
    return {"kind": "sessions", "sessions": sessions}


def _position_document(scenario: AnyScenario) -> dict[str, object] | None:
    if scenario.position is None:
        return None
    lots = abs(held_lots(scenario))
    return {"side": str(scenario.position.side), "lots": lots, "price": scenario.position.price}


def _decisions_document(
    scenario: AnyScenario, parameters: InstrumentParameters
) -> dict[str, object]:
    if isinstance(scenario, TemplateScenario):
        return {"kind": "template", "strategy": scenario.strategy.document()}
    groups: dict[str, int] = {}
    for order in scenario.orders:
        if order.oco is not None:
            groups.setdefault(order.oco, len(groups) + 1)
    orders = [_order_document(order, groups, parameters) for order in scenario.orders]
    return {"kind": "orders", "orders": orders}


def _order_document(
    order: Order, groups: dict[str, int], parameters: InstrumentParameters
) -> dict[str, object]:
    bracket = order.bracket
    legs = None
    if bracket is not None:
        legs = {
            "stop": {"id": bracket.stop.id, "price": bracket.stop.price},
            "target": {"id": bracket.target.id, "price": bracket.target.price},
        }
    return {
        "id": order.id,
        "placed_at": order.placed_at,
        "side": str(order.side),
        "kind": order.kind,
        "price": order.price if isinstance(order, PricedOrder) else None,
        "lots": lots_of(order.quantity, parameters.lot_step),
        "oco": None if order.oco is None else groups[order.oco],
        "bracket": legs,
    }


def _tapes(cases: Sequence[EngineCase]) -> dict[str, pl.DataFrame]:
    """Each level's records of every case, its tape and the coarser bars a skipping case adds,
    in the columns of the engine cache, with the case and the trade date."""
    columns: dict[str, dict[str, list[int]]] = {}
    for number, case in enumerate(cases):
        levels = [(case.scenario.fidelity, case.scenario.tape)]
        tape: Sequence[Record] = case.scenario.tape
        levels += [(level, coarser_bars(tape, level)) for level in case.coarser_levels()]
        for level, records in levels:
            table = columns.setdefault(str(level), {})
            dates = _trade_dates(records, case.sessions)
            for record, trade_date in zip(records, dates, strict=True):
                for name, value in _record_values(number, trade_date, record).items():
                    table.setdefault(name, []).append(value)
    return {
        level: pl.DataFrame(table, schema=dict.fromkeys(table, pl.Int64))
        for level, table in columns.items()
    }


def coarser_bars(records: Sequence[Record], timeframe: Timeframe) -> tuple[BarRecord, ...]:
    """The bars of `timeframe` that `records`, ticks or finer bars, make: one for each bucket of
    the UTC clock that holds a record, by the instant the record starts at, with the bucket's
    first and last prices, its extremes, and its volume (`02` §1.4). Every built-in session opens
    on a whole hour, so these buckets fall where a session's own do."""
    length = timeframe.nominal_nanoseconds()
    bars = []
    for bucket, held in itertools.groupby(records, key=lambda record: record.starts_at() // length):
        prices = [_ohlcv(record) for record in held]
        bars.append(
            BarRecord.model_construct(
                ts_open=bucket * length,
                ts_close=(bucket + 1) * length,
                open=prices[0][0],
                high=max(high for _, high, _, _, _ in prices),
                low=min(low for _, _, low, _, _ in prices),
                close=prices[-1][3],
                volume=sum(volume for *_, volume in prices),
            )
        )
    return tuple(bars)


def _ohlcv(record: Record) -> tuple[int, int, int, int, int]:
    """A record's open, high, low, close, and volume: a tick's price for the four."""
    if isinstance(record, BarRecord):
        return (record.open, record.high, record.low, record.close, record.volume)
    return (record.price, record.price, record.price, record.price, record.size)


def _trade_dates(records: Sequence[Record], sessions: SessionTable | None) -> list[int]:
    """Each record's trade date in days since 1970-01-01: that of the session it falls in, or of
    the last one opened before it, by the instant it starts at; the UTC day without a session
    table."""
    starts = [record.starts_at() for record in records]
    if sessions is None:
        return [start // NANOSECONDS_PER_DAY for start in starts]
    frame = pl.DataFrame(
        {"ts": starts, "order": range(len(starts))}, schema_overrides={"ts": pl.Int64}
    )
    dated = sessions.assign_trade_dates_or_previous(frame, "ts").sort("order")
    return dated.get_column("trade_date").cast(pl.Int32).cast(pl.Int64).to_list()


def _record_values(case: int, trade_date: int, record: Record) -> dict[str, int]:
    common = {"case": case, "trade_date": trade_date}
    if isinstance(record, BarRecord):
        bar = record.model_dump(include={"ts_open", "ts_close", "open", "high", "low", "close"})
        return {**common, **bar, "volume": record.volume}
    values = {**common, "ts_recv": record.ts, "price": record.price, "size": record.size}
    if isinstance(record, TbboRecord):
        quote = {"bid": record.bid, "ask": record.ask, "bid_size": record.bid_size}
        values |= {**quote, "ask_size": record.ask_size}
    return values


def _signal_rows(cases: Sequence[EngineCase]) -> pl.DataFrame | None:
    """The signal rows of the template cases, each tagged with its case: the four signals, the
    optional columns the template reads, absent ones null (D-53), the features its exit plan
    names, and with a flat-by time the instant of each row's trade date's flat-by time."""
    frames = []
    for number, case in enumerate(cases):
        scenario = case.scenario
        if not isinstance(scenario, TemplateScenario):
            continue
        frame = scenario.signal_frame()
        frames.append(_template_rows(number, scenario.strategy, frame, case.sessions))
    return pl.concat(frames, how="diagonal") if frames else None


def _template_rows(
    number: int, strategy: StrategySpec, frame: pl.DataFrame, sessions: SessionTable | None
) -> pl.DataFrame:
    """The rows of one template case, tagged with its number: the four signals, the optional
    columns the template reads, absent ones null (D-53), the columns of its time rules, as the
    reference's template works them out (`with_time_rules`), and the features its exit plan
    names."""
    timed = with_time_rules(strategy, frame.sort("ts_close"), sessions)
    kept = [*_SIGNALS, *(name for name in _OPTIONAL_SIGNALS if name in frame.columns)]
    times = [name for name in _TIME_COLUMNS if name in timed.columns]
    features = _feature_columns(strategy, frame)
    case = pl.lit(number, dtype=pl.Int64).alias("case")
    days = [pl.col("trade_date").cast(pl.Int32).cast(pl.Int64)] if "trade_date" in frame else []
    blackout, flags = strategy.execution.limits.blackout, []
    if blackout is not None and blackout in frame.columns:
        flags.append(pl.col(blackout).cast(pl.Boolean).alias("blackout"))
    return timed.select(case, *days, *kept, *times, *features, *flags)


def _feature_columns(strategy: StrategySpec, frame: pl.DataFrame) -> list[pl.Expr]:
    """The features the exit plan's rules name, as float64 columns under the names of their
    rules, which `fefat-cli run` reads: `stop_feature`, `target_feature_1` to `target_feature_3`,
    and `trail_feature`. A feature the frame lacks stays out, and the Rust template refuses an
    entry that needs it, as the reference's does."""
    execution = strategy.execution
    named: dict[str, str] = {}
    if isinstance(execution.stop, rules.AtrStop):
        named["stop_feature"] = execution.stop.feature
    for number, target in enumerate(execution.targets, start=1):
        if isinstance(target.price, rules.AtrTarget):
            named[f"target_feature_{number}"] = target.price.feature
    trailing = execution.trailing
    if trailing is not None and isinstance(trailing.by, rules.AtrTrail):
        named["trail_feature"] = trailing.by.feature
    return [
        pl.col(feature).cast(pl.Float64).alias(column)
        for column, feature in named.items()
        if feature in frame.columns
    ]


def _read(path: Path) -> pl.DataFrame:
    """An Arrow file read from its bytes, so that no map keeps the temporary folder open on
    Windows."""
    return pl.read_ipc(io.BytesIO(path.read_bytes()))
