"""The Rust engine through `fefat-cli run` (steps 2.6 and 2.7), a development tool of the
repository until the Python bindings of step 2.10: cases, each a scenario of `fixtures/scenarios/`
or one Hypothesis draws (`fefat.reference.generated_cases`), run as one batch in one process
(`fefat.reference.rust_batch`), in full or skipping, and through the reference engine, and
compared value for value (D-10, ADR-0008): each fill with its fee and contract, the event log,
the position and cash each case ends with, its count of ambiguous fills, and its cost lines.

    engine = RustEngine(default_binary())
    cases = engine_cases(scenarios, cache_folder, Replay.SKIPPING)
    for comparison in compare_engines(engine, cases):
        print(comparison.case.scenario.id, comparison.differences())
"""

import json
import os
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import partial
from itertools import zip_longest
from pathlib import Path

from fefat.reference.hours import AlwaysOpen, CalendarHours
from fefat.reference.ledger import FillFlag
from fefat.reference.orders import Order, PricedOrder
from fefat.reference.run_documents import rate_units
from fefat.reference.rust_batch import (
    CacheCase,
    CostView,
    EngineCase,
    FillView,
    LogView,
    Replay,
    RustOutcome,
    read_outcomes,
    write_batch,
    write_cache_batch,
)
from fefat.reference.scenario_runner import (
    opening_cash,
    run_scenario,
    scenario_hours,
    session_tables,
)
from fefat.reference.scenarios import AnyScenario, TemplateScenario
from fefat.reference.signal_rows import SignalRow
from fefat.reference.tape import BarRecord, Record, TbboRecord
from fefat.reference.timeline import RunResult
from fefat.reference.units import instant_text, price_text
from fefat.strategy.signal_frame import PRICE_COLUMNS

BATCH_TIMEOUT_SECONDS = 120
"""How long a batch may run, where ten cases take a few milliseconds: a hang fails its example,
which Hypothesis then shrinks and prints, instead of stalling the test run."""
CACHE_TIMEOUT_SECONDS = 1_800
"""How long a run over an engine cache may take: a generated year replayed in full takes seconds
on this PC."""


def engine_cases(
    scenarios: Sequence[AnyScenario], cache_folder: Path, replay: Replay = Replay.FULL
) -> list[EngineCase]:
    """Each scenario with the hours `run_scenarios` gives it, each calendar's sessions built once
    in `cache_folder`, for the Rust engine to replay as `replay` says."""
    tables = session_tables(scenarios, cache_folder)
    return [
        EngineCase(scenario, scenario_hours(scenario, sessions), sessions, replay)
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
        return self._batch(partial(write_batch, cases), len(cases))

    def run_on_caches(self, cases: Sequence[CacheCase]) -> list[RustOutcome]:
        """`cases`, templates over engine caches, as one batch in one process."""
        return self._batch(partial(write_cache_batch, cases), len(cases), CACHE_TIMEOUT_SECONDS)

    def _batch(
        self,
        write: Callable[[Path], None],
        cases: int,
        timeout_seconds: int = BATCH_TIMEOUT_SECONDS,
    ) -> list[RustOutcome]:
        with tempfile.TemporaryDirectory(prefix="fefat-cli-run-") as folder:
            batch, outputs = Path(folder) / "input", Path(folder) / "output"
            write(batch)
            command = [str(self.binary), "run", str(batch), str(outputs)]
            completed = subprocess.run(
                command, capture_output=True, text=True, check=False, timeout=timeout_seconds
            )
            if completed.returncode != 0:
                raise RuntimeError(
                    f"Expected fefat-cli run to pass, got exit code {completed.returncode}: "
                    f"{completed.stderr.strip()}"
                )
            return read_outcomes(outputs, cases)


@dataclass(frozen=True, slots=True, eq=False)
class CaseComparison:
    """A case's run through both engines."""

    case: EngineCase
    reference: RunResult
    rust: RustOutcome

    def reference_fills(self) -> tuple[FillView, ...]:
        return tuple(FillView.of(fill) for fill in self.reference.fills)

    def differences(self) -> tuple[str, ...]:
        """How the Rust engine's fills, event log, ledger at its end, count of ambiguous fills,
        and cost lines differ from the reference engine's: nothing when they agree."""
        found = []
        if self.reference_fills() != self.rust.fills:
            reference, rust = _listed(self.reference_fills()), _listed(self.rust.fills)
            found.append(f"the reference fills {reference}; Rust fills {rust}")
        reference_log = tuple(LogView.of(entry) for entry in self.reference.log.entries)
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
        flagged = sum(FillFlag.AMBIGUOUS in fill.flags for fill in self.reference.fills)
        if flagged != self.rust.ambiguous_fills:
            found.append(
                f"the reference counts {flagged} ambiguous fills, Rust {self.rust.ambiguous_fills}"
            )
        for reason in ("fee", "funding"):
            expected = _reference_costs(self.case.scenario, self.reference, reason)
            paid = tuple(line for line in self.rust.costs if line.reason == reason)
            if expected != paid:
                found.append(f"the reference's {reason} lines are {expected}, Rust's {paid}")
        return tuple(found)


def compare_engines(engine: RustEngine, cases: Sequence[EngineCase]) -> list[CaseComparison]:
    """`cases` through the Rust engine, as one batch, and through the reference engine."""
    outcomes = engine.run(cases)
    return [
        CaseComparison(case, run_scenario(case.scenario, case.hours, case.sessions).result, rust)
        for case, rust in zip(cases, outcomes, strict=True)
    ]


def _reference_cash(scenario: AnyScenario, result: RunResult) -> int:
    """The capital, moved by the opening position's value at its price, by each fill's value less
    its fee, and by each funding payment, each floored once as the ledger books them
    (F-FEE-03)."""
    fills = sum(fill.cash - fill.fee for fill in result.fills)
    return opening_cash(scenario) + fills + sum(payment.amount for payment in result.funding)


def _reference_costs(scenario: AnyScenario, result: RunResult, reason: str) -> tuple[CostView, ...]:
    """The reference's cost lines of `reason`: each fill's fee where the scenario has fees, in
    the order of the fills, or each funding payment, what the trader paid at its rate."""
    if reason == "fee":
        if scenario.fees is None:
            return ()
        return tuple(CostView(fill.ts, "fee", fill.order, None, fill.fee) for fill in result.fills)
    rates = {rate.ts: rate_units(rate.rate) for rate in scenario.funding}
    return tuple(
        CostView(paid.ts, "funding", None, rates[paid.ts], -paid.amount) for paid in result.funding
    )


def explained(comparison: CaseComparison) -> str:
    """A case as a scenario file writes it, its tape, orders, and settings, then the fills it
    expects, if it is a scenario of `fixtures/scenarios/`, and those of each engine."""
    scenario = comparison.case.scenario
    settings = scenario.settings
    ticks = settings.slippage_ticks
    lines = [
        f"{scenario.id}: {scenario.fidelity}, replayed {comparison.case.replay}, latency "
        f"{settings.latency_ms} ms, slippage ticks {ticks.market} market and {ticks.stop} stop, "
        f"limits filled {settings.limit_fill}, rolls {settings.roll_handling}"
    ]
    if scenario.fees is not None:
        lines.append(f"fees: {scenario.fees.model_dump_json()}")
    for roll in scenario.rolls:
        lines.append(
            f"roll: {roll.rolled_from} to {roll.contract} at {instant_text(roll.session_open)}, "
            f"a gap of {price_text(roll.gap)} ({roll.reason})"
        )
    lines += [f"funding: {rate.rate} at {instant_text(rate.ts)}" for rate in scenario.funding]
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
        span = f'ts_open: "{instant_text(record.ts_open)}", ts_close: "{instant_text(record.ts_close)}"'
        named = zip(("open", "high", "low", "close"), record.prices(), strict=True)
        prices = ", ".join(f'{name}: "{price_text(price)}"' for name, price in named)
        return f"{{{span}, {prices}, volume: {record.volume}}}"
    text = (
        f'ts: "{instant_text(record.ts)}", price: "{price_text(record.price)}", size: {record.size}'
    )
    if isinstance(record, TbboRecord):
        quote = f'bid: "{price_text(record.bid)}", ask: "{price_text(record.ask)}"'
        text += f", {quote}, bid_size: {record.bid_size}, ask_size: {record.ask_size}"
    return f"{{{text}}}"


def _decision_lines(scenario: AnyScenario) -> list[str]:
    if isinstance(scenario, TemplateScenario):
        rows = [f"  {_signal_text(row)}" for row in scenario.signals]
        return [f"strategy: {json.dumps(scenario.strategy.document())}", "signals:", *rows]
    return ["orders:", *(f"  {_order_text(order)}" for order in scenario.orders)]


def _signal_text(row: SignalRow) -> str:
    """The row's columns that differ from their defaults, its instant and prices as text."""
    shown = row.model_dump(mode="json", exclude_defaults=True)
    prices = {name: price_text(shown[name]) for name in PRICE_COLUMNS if name in shown}
    return str({**shown, "ts_close": instant_text(row.ts_close), **prices})


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
