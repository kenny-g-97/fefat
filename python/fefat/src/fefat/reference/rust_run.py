"""The Rust engine through `fefat-cli run` (step 2.6), a development tool of the repository until
the Python bindings of step 2.10: cases, each a scenario of `fixtures/scenarios/` or one
Hypothesis draws (`fefat.reference.generated_cases`), run as one batch in one process
(`fefat.reference.rust_batch`) and through the reference engine, and compared value for value
(D-10, ADR-0008): each fill, the event log, and the position and cash each case ends with.

    engine = RustEngine(default_binary())
    cases = engine_cases(scenarios, cache_folder)
    for comparison in compare_engines(engine, cases):
        print(comparison.case.scenario.id, comparison.differences())
"""

import json
import math
import os
import subprocess
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import zip_longest
from pathlib import Path

from fefat.reference.event_log import EventKind
from fefat.reference.hours import AlwaysOpen, CalendarHours
from fefat.reference.orders import Order, PricedOrder
from fefat.reference.rust_batch import (
    CAPITAL,
    EngineCase,
    FillView,
    LogView,
    RustOutcome,
    read_outcomes,
    write_batch,
)
from fefat.reference.scenario_runner import (
    held_lots,
    run_scenario,
    scenario_hours,
    session_tables,
)
from fefat.reference.scenarios import AnyScenario, TemplateScenario
from fefat.reference.tape import BarRecord, Record, TbboRecord
from fefat.reference.timeline import RunResult
from fefat.reference.units import instant_text, instrument_parameters, price_text

BATCH_TIMEOUT_SECONDS = 120
"""How long a batch may run, where ten cases take a few milliseconds: a hang fails its example,
which Hypothesis then shrinks and prints, instead of stalling the test run."""


def engine_cases(scenarios: Sequence[AnyScenario], cache_folder: Path) -> list[EngineCase]:
    """Each scenario with the hours `run_scenarios` gives it, each calendar's sessions built once
    in `cache_folder`."""
    tables = session_tables(scenarios, cache_folder)
    return [
        EngineCase(scenario, scenario_hours(scenario, sessions), sessions)
        for scenario, sessions in zip(scenarios, tables, strict=True)
    ]


def default_binary() -> Path:
    """`FEFAT_CLI` when set, else the release build of `just build-engine` in the repository's
    `engine/target/`: this module runs from a checkout of the repository."""
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
            completed = subprocess.run(
                command, capture_output=True, text=True, check=False, timeout=BATCH_TIMEOUT_SECONDS
            )
            if completed.returncode != 0:
                raise RuntimeError(
                    f"Expected fefat-cli run to pass, got exit code {completed.returncode}: "
                    f"{completed.stderr.strip()}"
                )
            return read_outcomes(outputs, len(cases))


@dataclass(frozen=True, slots=True, eq=False)
class CaseComparison:
    """A case's run through both engines."""

    case: EngineCase
    reference: RunResult
    rust: RustOutcome

    def reference_fills(self) -> tuple[FillView, ...]:
        return tuple(FillView.of(fill) for fill in self.reference.fills)

    def differences(self) -> tuple[str, ...]:
        """How the Rust engine's fills, event log, and ledger at its end differ from the
        reference engine's: nothing when they agree. Fees and funding, which costs bring in
        step 2.9, are left out, so the reference's cash is its capital moved by the opening
        position's value and by its fills' values."""
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
        ledger = (self.reference.position, _reference_cash(self.case.scenario, self.reference))
        if ledger != (self.rust.position, self.rust.cash):
            got = (self.rust.position, self.rust.cash)
            found.append(f"the reference ends with position and cash {ledger}, Rust with {got}")
        return tuple(found)


def compare_engines(engine: RustEngine, cases: Sequence[EngineCase]) -> list[CaseComparison]:
    """`cases` through the Rust engine, as one batch, and through the reference engine."""
    outcomes = engine.run(cases)
    return [
        CaseComparison(case, run_scenario(case.scenario, case.hours, case.sessions).result, rust)
        for case, rust in zip(cases, outcomes, strict=True)
    ]


def _reference_cash(scenario: AnyScenario, result: RunResult) -> int:
    """The capital, moved by the opening position's value at its price and by each fill's value,
    each floored once as the ledger books them (F-FEE-03), fees left out."""
    opening = 0
    if scenario.position is not None:
        parameters = instrument_parameters(scenario.instrument)
        opening = math.floor(-parameters.value(scenario.position.price, held_lots(scenario)))
    return CAPITAL + opening + sum(fill.cash for fill in result.fills)


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


def _listed(fills: Sequence[FillView]) -> str:
    return "; ".join(_fill_text(fill) for fill in fills) if fills else "none"


def _fill_text(fill: FillView) -> str:
    """Such as `order 1 sell 1 at 4990.25 at 2026-03-06T14:30:01.25Z (F-STP-03, taker, 19 ticks)`."""
    flags = "".join(f", {flag}" for flag in fill.flags)
    details = f"{fill.rule}, {fill.liquidity}, {fill.slippage_ticks} ticks{flags}"
    at = f"{price_text(fill.price)} at {instant_text(fill.ts)}"
    return f"order {fill.order} {fill.side} {fill.lots} at {at} ({details})"


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
