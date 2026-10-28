"""Step 2.8, Done means 1, on generated templates: the Rust engine, by `fefat-cli run`, runs
10,000 full execution templates that Hypothesis draws (`fefat.reference.generated_templates`),
5,000 on ticks and 5,000 on bars, in full or skipping, as the reference engine does: fills, event
log, ledger, and count of ambiguous fills alike. Each example runs ten cases as one batch in one
process, under the seed of the other differential tests. The drawn cases must reach every exit
reason they can (all but flat-by, no overnight, and no weekend, which need a session calendar),
targets that close part of a position, stops moved by breakeven and by trailing, reduced stops,
expired entries, entries skipped for want of a mark or of lots, entries of every size, and each
entry limit keeping out an order that the same case without it places, so that agreement never
means that nothing happened."""

import time
from collections import Counter

import pytest
from hypothesis import given, seed, settings
from hypothesis import strategies as st

from fefat.reference.event_log import EventKind, EventLog
from fefat.reference.generated_cases import DrawnTapes
from fefat.reference.generated_templates import full_template_cases
from fefat.reference.rust_batch import EngineCase
from fefat.reference.rust_run import (
    CaseComparison,
    RustEngine,
    compare_engines,
    default_binary,
    explained,
)
from fefat.reference.scenario_runner import run_scenario
from fefat.reference.scenarios import TemplateScenario
from fefat.strategy.exits import Limits

DIFFERENTIAL_SEED = 20_261_026
"""The run's seed, recorded in the pull request, as the other differential tests'."""
EXAMPLES = 500
CASES_PER_EXAMPLE = 10
ROLES = frozenset(
    {
        "entry",
        "stop",
        "target_1",
        "target_2",
        "target_3",
        "max_bars",
        "max_minutes",
        "opposite_signal",
        "signal_exit",
    }
)
"""The roles fills of the drawn templates take: every exit reason without a session calendar."""
LOG_RULES = frozenset(
    {
        ("moved", "F-BRK-01"),
        ("moved", "F-TRL-01"),
        ("reduced", "F-PLN-02"),
        ("cancelled", "F-ENT-03"),
        ("skipped", "F-ENT-02"),
        ("skipped", "F-SIZ-04"),
    }
)
"""The log entries of the exit plans and the entries that the drawn templates must reach."""


def limit_of(scenario: TemplateScenario) -> str | None:
    """The entry limit a drawn template sets, one at most."""
    limits = scenario.strategy.execution.limits
    named = [field for field, value in limits if value not in (None, False)]
    return named[0] if named else None


def placed(log: EventLog) -> int:
    """The orders a run's decisions placed (F-ACT-01), its entries and its exits."""
    return sum(entry.kind is EventKind.PLACED and entry.rule == "F-ACT-01" for entry in log.entries)


def placed_without_the_limit(case: EngineCase) -> int:
    """The orders the reference engine places in `case` with its limit left out."""
    scenario = case.scenario
    if not isinstance(scenario, TemplateScenario):
        raise TypeError(f"Expected a template case, got {scenario!r}.")
    execution = scenario.strategy.execution.model_copy(update={"limits": Limits()})
    strategy = scenario.strategy.model_copy(update={"execution": execution})
    unlimited = scenario.model_copy(update={"strategy": strategy})
    return placed(run_scenario(unlimited, case.hours, case.sessions).result.log)


class Coverage:
    """What the drawn templates reached, counted from the Rust engine's outputs."""

    def __init__(self) -> None:
        self.cases = 0
        self.roles: Counter[str] = Counter()
        self.log: Counter[tuple[str, str | None]] = Counter()
        self.partial_targets = 0
        self.entries_by_size: Counter[str] = Counter()
        self.blocked: Counter[str] = Counter()

    def count(self, comparison: CaseComparison) -> None:
        scenario = comparison.case.scenario
        if not isinstance(scenario, TemplateScenario):
            raise TypeError(f"Expected a template case, got {scenario!r}.")
        fills = comparison.rust.fills
        self.cases += 1
        self.roles.update(fill.role for fill in fills)
        self.log.update((entry.kind, entry.rule) for entry in comparison.rust.log)
        entries = [fill for fill in fills if fill.role == "entry"]
        largest = max((fill.lots for fill in entries), default=0)
        targets = (fill for fill in fills if fill.role.startswith("target"))
        self.partial_targets += sum(fill.lots < largest for fill in targets)
        self.entries_by_size[scenario.strategy.execution.sizing.kind] += len(entries)
        limit = limit_of(scenario)
        limited = placed(comparison.reference.log)
        if limit is not None and placed_without_the_limit(comparison.case) > limited:
            self.blocked[limit] += 1


@pytest.mark.parametrize("tapes", list(DrawnTapes))
def test_the_rust_engine_runs_5000_generated_templates_as_the_reference_does(
    tapes: DrawnTapes, capsys: pytest.CaptureFixture[str]
) -> None:
    engine = RustEngine(default_binary())
    coverage = Coverage()

    @seed(DIFFERENTIAL_SEED)
    @settings(max_examples=EXAMPLES, deadline=None, database=None, print_blob=True)
    @given(
        cases=st.lists(
            full_template_cases(tapes), min_size=CASES_PER_EXAMPLE, max_size=CASES_PER_EXAMPLE
        )
    )
    def the_engines_agree(cases: list[EngineCase]) -> None:
        comparisons = compare_engines(engine, cases)
        found = [
            "\n".join([explained(comparison), *comparison.differences()])
            for comparison in comparisons
            if comparison.differences()
        ]
        if found:
            raise AssertionError(f"Seed {DIFFERENTIAL_SEED}:\n\n" + "\n\n".join(found))
        for comparison in comparisons:
            coverage.count(comparison)

    started = time.perf_counter()
    the_engines_agree()
    elapsed = time.perf_counter() - started

    with capsys.disabled():
        print(
            f"\n{coverage.cases} generated templates on {tapes} through both engines in "
            f"{elapsed:.1f} s, seed {DIFFERENTIAL_SEED}"
        )
        print("fills by role:", dict(sorted(coverage.roles.items())))
        print("log entries:", dict(sorted(coverage.log.items(), key=str)))
        print(f"targets closing part of a position: {coverage.partial_targets}")
        print("entries by size:", dict(coverage.entries_by_size))
        print("entries blocked by each limit:", dict(coverage.blocked))
    assert coverage.cases >= EXAMPLES * CASES_PER_EXAMPLE
    assert set(coverage.roles) >= ROLES, f"Expected fills of every role, got {coverage.roles}"
    assert set(coverage.log) >= LOG_RULES, f"Expected every log rule, got {coverage.log}"
    assert coverage.partial_targets > 0
    assert set(coverage.entries_by_size) == {"fixed", "notional", "risk_amount", "risk_percent"}
    assert min(coverage.entries_by_size.values()) > 0
    reached = set(coverage.blocked)
    assert reached >= set(Limits.model_fields), f"Expected every limit to block, got {reached}"
