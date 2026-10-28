"""The scenario runner (step 2.2): every fill scenario of `fixtures/scenarios/` through the
reference engine, an order scenario's orders placed at their decisions and a template
scenario's strategy run from its signal rows (step 2.3), its fills, marks, and funding compared
exactly with those it expects, and how the scenarios cover the rules of
`docs/spec/fill-semantics.md`. From the repository folder:

    uv run python -m fefat.reference.scenario_runner
    uv run python -m fefat.reference.scenario_runner --log S-fill-012

The second prints one scenario's tape, orders, and event log, to follow a fill from its tape
to the log.
"""

import argparse
import io
import math
import os
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

from fefat.config import resolve_paths
from fefat.market.calendar import SessionTable, sessions_of
from fefat.market.calendar_definition import Calendar
from fefat.reference.engine import ReferenceEngine
from fefat.reference.hours import AlwaysOpen, CalendarHours, TradingHours
from fefat.reference.orders import PositionSide
from fefat.reference.scenarios import (
    AnyScenario,
    Scenario,
    TemplateScenario,
    load_scenarios,
    specified_rules,
)
from fefat.reference.strategy import Decision, DecisionContext, OnBar, decisions_of
from fefat.reference.template import TemplateStrategy
from fefat.reference.timeline import RunResult
from fefat.reference.units import (
    CAPITAL,
    InlineInstrument,
    InstrumentParameters,
    instant_text,
    instrument_parameters,
    lots_of,
    money_text,
    price_text,
)

SCENARIOS = Path("fixtures") / "scenarios"
SPECIFICATION = Path("docs") / "spec" / "fill-semantics.md"


@dataclass(frozen=True, slots=True)
class ScenarioOutcome:
    """A scenario's run, and how its fills, marks, and funding differ from those it expects:
    nothing when it passes."""

    scenario: AnyScenario
    result: RunResult
    differences: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ScenarioReport:
    outcomes: tuple[ScenarioOutcome, ...]

    def outcome(self, scenario_id: str) -> ScenarioOutcome:
        found = [outcome for outcome in self.outcomes if outcome.scenario.id == scenario_id]
        if not found:
            raise ValueError(f"Expected a scenario {scenario_id} in the report, got none.")
        return found[0]

    def passed(self) -> int:
        return sum(1 for outcome in self.outcomes if not outcome.differences)


def run_scenario(
    scenario: AnyScenario, hours: TradingHours, sessions: SessionTable | None = None
) -> ScenarioOutcome:
    """`scenario` through the reference engine, open during `hours`: an order scenario's orders
    placed at their decisions, or a template scenario's strategy run from its signal rows on
    `sessions`, its instrument's session table."""
    parameters = instrument_parameters(scenario.instrument)
    engine = ReferenceEngine(scenario.settings, parameters, scenario.fidelity, hours, scenario.fees)
    if isinstance(scenario, TemplateScenario):
        decisions, on_bar = _template_decisions(scenario, parameters, sessions)
    else:
        decisions, on_bar = _order_decisions(scenario)
    held, cash = held_lots(scenario), opening_cash(scenario)
    result = engine.run(scenario.tape, decisions, on_bar, scenario.funding, held, cash)
    return ScenarioOutcome(scenario, result, differences(scenario, result))


def _order_decisions(scenario: Scenario) -> tuple[list[Decision], OnBar]:
    """A decision at each instant the scenario places orders, placing them there."""
    orders = scenario.orders
    instants = sorted({order.placed_at for order in orders})

    def place_its_orders(bar: object, context: DecisionContext) -> None:
        for order in orders:
            if order.placed_at == context.now:
                context.place(order)

    return [
        Decision(ts=instant, bar={"ts_close": instant}) for instant in instants
    ], place_its_orders


def _template_decisions(
    scenario: TemplateScenario, parameters: InstrumentParameters, sessions: SessionTable | None
) -> tuple[list[Decision], OnBar]:
    """A decision at each of the scenario's signal rows, taken by its strategy's template."""
    frame = scenario.signal_frame()
    template = TemplateStrategy(scenario.strategy, frame, parameters, sessions)
    return list(decisions_of(frame)), template.on_bar


def opening_cash(scenario: AnyScenario) -> int:
    """The cash a scenario starts with: the capital (D-51), moved by its opening position's value
    at its price, floored once, as the Rust ledger opens it (`Ledger::holding`)."""
    if scenario.position is None:
        return CAPITAL
    parameters = instrument_parameters(scenario.instrument)
    return CAPITAL + math.floor(-parameters.value(scenario.position.price, held_lots(scenario)))


def held_lots(scenario: AnyScenario) -> int:
    """The position a scenario holds when its tape starts, in lots, positive long."""
    if scenario.position is None:
        return 0
    lots = lots_of(scenario.position.quantity, scenario.instrument.lot_step)
    return lots if scenario.position.side is PositionSide.LONG else -lots


def run_scenarios(scenarios: Sequence[AnyScenario], cache_folder: Path) -> ScenarioReport:
    """Every scenario through the reference engine, each calendar's sessions built once."""
    outcomes = []
    for scenario, sessions in zip(scenarios, session_tables(scenarios, cache_folder), strict=True):
        outcomes.append(run_scenario(scenario, scenario_hours(scenario, sessions), sessions))
    return ScenarioReport(tuple(outcomes))


def session_tables(
    scenarios: Sequence[AnyScenario], cache_folder: Path
) -> list[SessionTable | None]:
    """Each scenario's session table, none for an inline instrument, which trades around the
    clock; each calendar's table is built once, in `cache_folder`."""
    tables: dict[str, SessionTable] = {}
    found: list[SessionTable | None] = []
    for scenario in scenarios:
        if isinstance(scenario.instrument, InlineInstrument):
            found.append(None)
            continue
        calendar: Calendar = scenario.instrument.session_calendar()
        if calendar.name not in tables:
            tables[calendar.name] = sessions_of(calendar, cache_folder)
        found.append(tables[calendar.name])
    return found


def scenario_hours(
    scenario: AnyScenario, sessions: SessionTable | None
) -> AlwaysOpen | CalendarHours:
    """When the market is open around the scenario's tape: always, without a session table."""
    if sessions is None:
        return AlwaysOpen()
    first, last = scenario.tape[0].starts_at(), scenario.tape[-1].available_at()
    return CalendarHours.around(sessions, first, last)


class FillSummary(NamedTuple):
    """What the runner compares of a fill: its order, time, price, rule, and flags, its fee in a
    scenario with fees, and its lots in a scenario that states its fills' quantities."""

    order: int
    ts: int
    price: int
    rule: str
    flags: tuple[str, ...]
    fee: int | None
    lots: int | None

    def text(self) -> str:
        flags = "".join(f", {flag}" for flag in self.flags)
        fee = "" if self.fee is None else f", fee {money_text(self.fee)}"
        lots = "" if self.lots is None else f" x {self.lots}"
        at = f"{price_text(self.price)}{lots} at {instant_text(self.ts)}"
        return f"order {self.order} at {at} ({self.rule}{flags}{fee})"


def differences(scenario: AnyScenario, result: RunResult) -> tuple[str, ...]:
    """How the run differs from what the scenario expects: each fill's order, time, price,
    rule, flags, fee where the scenario has fees, and lots where it states quantities, its
    fidelity tag (F-TAG-01), the marks, and the funding payments."""
    with_fees = scenario.fees is not None
    lot_step = scenario.instrument.lot_step
    with_lots = any(f.quantity is not None for f in scenario.expected.fills)
    expected = [
        FillSummary(
            f.order,
            f.ts,
            f.price,
            f.rule,
            tuple(sorted(f.flags)),
            f.fee,
            None if f.quantity is None else lots_of(f.quantity, lot_step),
        )
        for f in scenario.expected.fills
    ]
    got = [
        FillSummary(
            f.order,
            f.ts,
            f.price,
            f.rule,
            tuple(sorted(f.flags)),
            f.fee if with_fees else None,
            f.lots if with_lots else None,
        )
        for f in result.fills
    ]
    found = []
    if got != expected:
        found.append(f"expected the fills {_listed(expected)}, got {_listed(got)}")
    tags = sorted({str(fill.fidelity) for fill in result.fills} - {str(scenario.fidelity)})
    if tags:
        found.append(f"expected fills tagged {scenario.fidelity}, got {', '.join(tags)}")
    last_marks = {mark.ts: mark.price for mark in result.marks}
    for mark in scenario.expected.marks:
        got_mark = last_marks.get(mark.ts)
        if got_mark != mark.price:
            shown = "none" if got_mark is None else price_text(got_mark)
            at = instant_text(mark.ts)
            found.append(f"expected the mark {price_text(mark.price)} at {at}, got {shown}")
    paid = [(payment.ts, payment.amount) for payment in result.funding]
    owed = [(payment.ts, payment.amount) for payment in scenario.expected.funding]
    if paid != owed:
        found.append(f"expected the funding {_paid(owed)}, got {_paid(paid)}")
    return tuple(found)


def _listed(fills: list[FillSummary]) -> str:
    return "; ".join(fill.text() for fill in fills) if fills else "none"


def _paid(payments: list[tuple[int, int]]) -> str:
    listed = (f"{money_text(amount)} at {instant_text(ts)}" for ts, amount in payments)
    return "; ".join(listed) or "none"


def report_lines(report: ScenarioReport, rules: Sequence[str]) -> list[str]:
    """The pass count, each failing scenario's differences, and for each rule of the
    specification the scenarios that cite it and the fills the engine priced by it."""
    total = len(report.outcomes)
    lines = [f"{report.passed()} of {total} fill scenarios pass through the reference engine."]
    for outcome in report.outcomes:
        lines += [f"{outcome.scenario.id}: {difference}" for difference in outcome.differences]
    cited = Counter(rule for outcome in report.outcomes for rule in outcome.scenario.rules)
    priced = Counter(fill.rule for outcome in report.outcomes for fill in outcome.result.fills)
    lines += ["", f"{'Rule':<10}{'Scenarios':>10}{'Fills':>8}"]
    lines += [f"{rule:<10}{cited[rule]:>10}{priced[rule]:>8}" for rule in rules]
    uncited = [rule for rule in rules if cited[rule] == 0]
    lines.append(
        f"Rules no scenario cites: {', '.join(uncited)}." if uncited else "Every rule is cited."
    )
    return lines


def explained_lines(outcome: ScenarioOutcome, written: str) -> list[str]:
    """One scenario as its file writes it, its tape, orders, and arithmetic, then the engine's
    event log, and whether the scenario passes."""
    lines = ["the scenario, as written:", *(f"  {line}" for line in written.splitlines())]
    lines += ["the engine's event log:", *(f"  {line}" for line in outcome.result.log.lines())]
    verdict = "passes" if not outcome.differences else "fails: " + "; ".join(outcome.differences)
    return [*lines, f"{outcome.scenario.id} {verdict}"]


def main(argv: Sequence[str] | None = None) -> int:
    """Run the scenarios and print the report, or one scenario's log with `--log`; 0 when every
    scenario run passes."""
    parser = argparse.ArgumentParser(description="Run the fill scenarios through the engine.")
    parser.add_argument("--folder", type=Path, default=SCENARIOS)
    parser.add_argument("--specification", type=Path, default=SPECIFICATION)
    parser.add_argument("--log", metavar="SCENARIO", help="print one scenario's event log")
    arguments = parser.parse_args(argv)
    if not arguments.folder.is_dir():
        raise ValueError(
            f"Expected the fill scenarios in {arguments.folder}, got no such folder: run from "
            "the repository folder, or pass --folder."
        )
    scenarios = load_scenarios(arguments.folder)
    if arguments.log is not None:
        scenarios = tuple(scenario for scenario in scenarios if scenario.id == arguments.log)
    report = run_scenarios(scenarios, resolve_paths(os.environ).cache_dir)
    if arguments.log is not None:
        written = (arguments.folder / f"{arguments.log}.yaml").read_text(encoding="utf-8")
        lines = explained_lines(report.outcome(arguments.log), written)
    else:
        rules = specified_rules(arguments.specification.read_text(encoding="utf-8"))
        lines = report_lines(report, rules)
    print("\n".join(lines))
    return 0 if report.passed() == len(report.outcomes) else 1


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8")
    sys.exit(main())
