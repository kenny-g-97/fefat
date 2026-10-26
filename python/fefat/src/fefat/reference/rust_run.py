"""The Rust engine through `fefat-cli run` (step 2.6), until the Python bindings of step 2.10:
cases, each a scenario of `fixtures/scenarios/` or one Hypothesis draws
(`fefat.reference.generated_cases`), are written as one batch into a temporary folder, run in one
process, and read back in the reference engine's terms, so that the two engines compare value for
value (D-10, ADR-0008):

    engine = RustEngine(default_binary())
    cases = engine_cases(scenarios, cache_folder)
    for comparison in compare_engines(engine, cases):
        print(comparison.case.scenario.id, comparison.differences())

The batch's `run.json` and Arrow files are those `engine/crates/fefat-cli/src/run/` reads; a
case's records carry the UTC day of their instant as their trade date, since nothing on ticks
reads a fill's trade date yet."""

import io
import json
import os
import subprocess
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import zip_longest
from pathlib import Path
from typing import Any, NamedTuple

import polars as pl

from fefat.market.calendar import SessionTable
from fefat.market.fidelity import TickFidelity
from fefat.reference.event_log import EventKind, LogEntry
from fefat.reference.hours import AlwaysOpen, CalendarHours
from fefat.reference.ledger import Fill
from fefat.reference.orders import Order, PricedOrder
from fefat.reference.scenario_runner import (
    held_lots,
    run_scenario,
    scenario_hours,
    session_tables,
)
from fefat.reference.scenarios import AnyScenario, TemplateScenario
from fefat.reference.tape import BarRecord, Record, TbboRecord
from fefat.reference.timeline import RunResult
from fefat.reference.units import (
    PRICE_DECIMALS,
    InstrumentParameters,
    instant_text,
    instrument_parameters,
    lots_of,
    price_text,
)

CAPITAL = 50_000_000_000
"""The run's capital in micro-units, 50,000 USD (D-51): the ledger's starting cash."""
NANOSECONDS_PER_DAY = 86_400 * 1_000_000_000
_SIGNALS = ("ts_close", "long_entry", "short_entry", "long_exit", "short_exit")
_OPTIONAL_SIGNALS = ("stop_price", "target_price", "size_mult", "wake")
_FLAGS = ("ambiguous", "size_exceeded")


@dataclass(frozen=True, slots=True)
class EngineCase:
    """A scenario as both engines run it: with the hours its market trades in and, for an
    instrument of the table, its session table, which a template's flat-by reads."""

    scenario: AnyScenario
    hours: AlwaysOpen | CalendarHours
    sessions: SessionTable | None = None


def engine_cases(scenarios: Sequence[AnyScenario], cache_folder: Path) -> list[EngineCase]:
    """Each scenario with the hours `run_scenarios` gives it, each calendar's sessions built once
    in `cache_folder`."""
    tables = session_tables(scenarios, cache_folder)
    return [
        EngineCase(scenario, scenario_hours(scenario, sessions), sessions)
        for scenario, sessions in zip(scenarios, tables, strict=True)
    ]


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

    def text(self) -> str:
        """Such as `order 1 at 4990.25 at 2026-03-06T14:30:01.25Z (F-STP-03, taker, 19 ticks)`."""
        flags = "".join(f", {flag}" for flag in self.flags)
        details = f"{self.rule}, {self.liquidity}, {self.slippage_ticks} ticks{flags}"
        at = f"{price_text(self.price)} at {instant_text(self.ts)}"
        return f"order {self.order} {self.side} {self.lots} at {at} ({details})"


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


@dataclass(frozen=True, slots=True, eq=False)
class RustOutcome:
    """A case's outputs from `fefat-cli run`: its fills, its event log, and its orders."""

    fills: tuple[FillView, ...]
    log: tuple[LogView, ...]
    orders: pl.DataFrame


@dataclass(frozen=True, slots=True, eq=False)
class CaseComparison:
    """A case's run through both engines."""

    case: EngineCase
    reference: RunResult
    rust: RustOutcome

    def reference_fills(self) -> tuple[FillView, ...]:
        return tuple(FillView.of(fill) for fill in self.reference.fills)

    def differences(self) -> tuple[str, ...]:
        """How the Rust engine's fills and event log differ from the reference engine's: nothing
        when they agree. Funding, which costs bring in step 2.9, is left out."""
        found = []
        if self.reference_fills() != self.rust.fills:
            reference, rust = _listed(self.reference_fills()), _listed(self.rust.fills)
            found.append(f"the reference fills {reference}; Rust fills {rust}")
        kept = (
            entry for entry in self.reference.log.entries if entry.kind is not EventKind.FUNDING
        )
        reference_log = tuple(LogView.of(entry) for entry in kept)
        if reference_log != self.rust.log:
            pairs = enumerate(zip_longest(reference_log, self.rust.log), start=1)
            number, (expected, got) = next(item for item in pairs if item[1][0] != item[1][1])
            found.append(
                f"the event logs differ at entry {number}: the reference {expected}, Rust {got}"
            )
        return tuple(found)


def default_binary() -> Path:
    """`FEFAT_CLI` when set, else the release build of `just build-engine` in the repository's
    `engine/target/`."""
    if "FEFAT_CLI" in os.environ:
        return Path(os.environ["FEFAT_CLI"])
    name = "fefat-cli.exe" if os.name == "nt" else "fefat-cli"
    return Path(__file__).resolve().parents[5] / "engine" / "target" / "release" / name


class RustEngine:
    """The Rust engine's batch runner, `fefat-cli run`, of the binary at `binary`."""

    def __init__(self, binary: Path) -> None:
        if not binary.is_file():
            raise ValueError(
                f"Expected the fefat-cli binary at {binary}, got none: run `just build-engine`, "
                "or set FEFAT_CLI to the binary."
            )
        self.binary = binary

    def run(self, cases: Sequence[EngineCase]) -> list[RustOutcome]:
        """`cases` as one batch in one process, each case's outcome in their order."""
        with tempfile.TemporaryDirectory(prefix="fefat-cli-run-") as folder:
            batch, outputs = Path(folder) / "input", Path(folder) / "output"
            write_batch(cases, batch)
            command = [str(self.binary), "run", str(batch), str(outputs)]
            completed = subprocess.run(command, capture_output=True, text=True, check=False)
            if completed.returncode != 0:
                raise RuntimeError(
                    f"Expected fefat-cli run to pass, got exit code {completed.returncode}: "
                    f"{completed.stderr.strip()}"
                )
            return read_outcomes(outputs, len(cases))


def compare_engines(engine: RustEngine, cases: Sequence[EngineCase]) -> list[CaseComparison]:
    """`cases` through the Rust engine, as one batch, and through the reference engine."""
    outcomes = engine.run(cases)
    return [
        CaseComparison(case, run_scenario(case.scenario, case.hours, case.sessions).result, rust)
        for case, rust in zip(cases, outcomes, strict=True)
    ]


def write_batch(cases: Sequence[EngineCase], folder: Path) -> None:
    """The batch of `cases` in `folder`: `run.json`, and the Arrow files of their records and
    signal rows, each row tagged with its case's place in `run.json`."""
    for case in cases:
        if not isinstance(case.scenario.fidelity, TickFidelity):
            raise ValueError(
                f"Expected cases on ticks, tbbo or trades, got {case.scenario.id} on "
                f"{case.scenario.fidelity}: bar fidelities arrive in step 2.7."
            )
    folder.mkdir(parents=True)
    manifest = {"cases": [_case_document(case) for case in cases]}
    (folder / "run.json").write_text(json.dumps(manifest), encoding="utf-8")
    for fidelity, frame in _tapes(cases).items():
        frame.write_ipc(folder / f"{fidelity}.arrow", compression="uncompressed")
    signals = _signal_rows(cases)
    if signals is not None:
        signals.write_ipc(folder / "signals.arrow", compression="uncompressed")


def read_outcomes(folder: Path, cases: int) -> list[RustOutcome]:
    """Each case's fills, event log, and orders from the outputs of `fefat-cli run`."""
    fills, log, orders = (_read(folder / f"{name}.arrow") for name in ("fills", "log", "orders"))
    outcomes = []
    for case in range(cases):
        of_case = pl.col("case") == case
        rows = fills.filter(of_case).iter_rows(named=True)
        entries = log.filter(of_case).iter_rows(named=True)
        outcomes.append(
            RustOutcome(
                fills=tuple(FillView.of_row(row) for row in rows),
                log=tuple(
                    LogView(entry["ts"], entry["kind"], entry["order"], entry["rule"])
                    for entry in entries
                ),
                orders=orders.filter(of_case).drop("case"),
            )
        )
    return outcomes


def explained(comparison: CaseComparison) -> str:
    """A case as a scenario file writes it, its tape, orders, and settings, then the fills it
    expects, if it is a scenario of `fixtures/scenarios/`, and those of each engine."""
    scenario = comparison.case.scenario
    settings = scenario.settings
    ticks = settings.slippage_ticks
    lines = [
        f"{scenario.id}: {scenario.fidelity}, latency {settings.latency_ms} ms, slippage ticks "
        f"{ticks.market} market and {ticks.stop} stop, limits filled {settings.limit_fill}"
    ]
    if scenario.position is not None:
        position = scenario.position
        lines.append(
            f"position: {position.side} {position.quantity} at {price_text(position.price)}"
        )
    lines += _hours_lines(comparison.case.hours, scenario.tape)
    lines += ["tape:", *(f"  {_record_text(record)}" for record in scenario.tape)]
    lines += _decision_lines(scenario)
    if scenario.expected.fills:
        expected = [
            f"order {fill.order} at {price_text(fill.price)} at {instant_text(fill.ts)} ({fill.rule})"
            for fill in scenario.expected.fills
        ]
        lines.append(f"expected fills: {'; '.join(expected)}")
    lines.append(f"reference fills: {_listed(comparison.reference_fills())}")
    lines.append(f"Rust fills: {_listed(comparison.rust.fills)}")
    return "\n".join(lines)


def _case_document(case: EngineCase) -> dict[str, object]:
    scenario = case.scenario
    parameters = instrument_parameters(scenario.instrument)
    settings = scenario.settings
    return {
        "id": scenario.id,
        "fidelity": str(scenario.fidelity),
        "contract": scenario.id,
        "instrument": {
            "tick_size": parameters.tick,
            "money_per_point": parameters.money_per_point,
            "lot_step": int(parameters.lot_step.scaleb(PRICE_DECIMALS)),
        },
        "settings": {
            "latency_ms": settings.latency_ms,
            "slippage_ticks": {
                "market": settings.slippage_ticks.market,
                "stop": settings.slippage_ticks.stop,
            },
            "limit_fill": str(settings.limit_fill),
        },
        "hours": _hours_document(case.hours),
        "capital": CAPITAL,
        "position": _position_document(scenario),
        "market_data": {"kind": "tape"},
        "decisions": _decisions_document(scenario, parameters),
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
    """Each fidelity's records of every case, in the columns of the engine cache, with the case
    and the trade date."""
    columns: dict[str, dict[str, list[int]]] = {}
    for number, case in enumerate(cases):
        fidelity = str(case.scenario.fidelity)
        for record in case.scenario.tape:
            table = columns.setdefault(fidelity, {})
            for name, value in _record_values(number, record).items():
                table.setdefault(name, []).append(value)
    return {
        fidelity: pl.DataFrame(table, schema=dict.fromkeys(table, pl.Int64))
        for fidelity, table in columns.items()
    }


def _record_values(case: int, record: Record) -> dict[str, int]:
    if isinstance(record, BarRecord):
        raise ValueError("Expected trades or TBBO records, got a bar: bars arrive in step 2.7.")
    # shortcut: the UTC day stands in for the trade date, which nothing on ticks reads; use the
    # session table's trade date when step 2.7 replays bars by trade date.
    values = {
        "case": case,
        "trade_date": record.ts // NANOSECONDS_PER_DAY,
        "ts_recv": record.ts,
        "price": record.price,
        "size": record.size,
    }
    if isinstance(record, TbboRecord):
        quote = {"bid": record.bid, "ask": record.ask, "bid_size": record.bid_size}
        values |= {**quote, "ask_size": record.ask_size}
    return values


def _signal_rows(cases: Sequence[EngineCase]) -> pl.DataFrame | None:
    """The signal rows of the template cases, each tagged with its case: the four signals and the
    optional columns the template reads, absent ones null (D-53)."""
    frames = []
    for number, case in enumerate(cases):
        if not isinstance(case.scenario, TemplateScenario):
            continue
        frame = case.scenario.signal_frame()
        kept = [*_SIGNALS, *(name for name in _OPTIONAL_SIGNALS if name in frame.columns)]
        frames.append(frame.select(pl.lit(number, dtype=pl.Int64).alias("case"), *kept))
    return pl.concat(frames, how="diagonal") if frames else None


def _read(path: Path) -> pl.DataFrame:
    """An Arrow file read from its bytes, so that no map keeps the temporary folder open on
    Windows."""
    return pl.read_ipc(io.BytesIO(path.read_bytes()))


def _listed(fills: Sequence[FillView]) -> str:
    return "; ".join(fill.text() for fill in fills) if fills else "none"


def _hours_lines(hours: AlwaysOpen | CalendarHours, tape: Sequence[Record]) -> list[str]:
    """The sessions the tape touches: from the one open at its first record to the one open at
    its last, the break between them included."""
    if isinstance(hours, AlwaysOpen):
        return []
    first, last = tape[0].starts_at(), tape[-1].available_at()
    touched = [
        f"{instant_text(session.open)} to {instant_text(session.close)}"
        for session in hours.sessions()
        if session.close >= first and session.open <= last
    ]
    return [f"sessions: {', '.join(touched)}"]


def _record_text(record: Record) -> str:
    if isinstance(record, BarRecord):
        return str(record.model_dump())
    text = (
        f'ts: "{instant_text(record.ts)}", price: "{price_text(record.price)}", size: {record.size}'
    )
    if isinstance(record, TbboRecord):
        quote = f'bid: "{price_text(record.bid)}", ask: "{price_text(record.ask)}"'
        text += f", {quote}, bid_size: {record.bid_size}, ask_size: {record.ask_size}"
    return f"{{{text}}}"


def _decision_lines(scenario: AnyScenario) -> list[str]:
    if isinstance(scenario, TemplateScenario):
        rows = [
            f"  {row.model_dump(mode='json', exclude_defaults=True)}" for row in scenario.signals
        ]
        return [f"strategy: {json.dumps(scenario.strategy.document())}", "signals:", *rows]
    return ["orders:", *(f"  {_order_text(order)}" for order in scenario.orders)]


def _order_text(order: Order) -> str:
    price = f', price: "{price_text(order.price)}"' if isinstance(order, PricedOrder) else ""
    oco = "" if order.oco is None else f", oco: {order.oco}"
    bracket = ""
    if order.bracket is not None:
        stop, target = order.bracket.stop, order.bracket.target
        bracket = (
            f', bracket: {{stop: {{id: {stop.id}, price: "{price_text(stop.price)}"}}, '
            f'target: {{id: {target.id}, price: "{price_text(target.price)}"}}}}'
        )
    placed = instant_text(order.placed_at)
    return (
        f'{{id: {order.id}, placed_at: "{placed}", side: {order.side}, kind: {order.kind}'
        f"{price}, quantity: {order.quantity}{oco}{bracket}}}"
    )
