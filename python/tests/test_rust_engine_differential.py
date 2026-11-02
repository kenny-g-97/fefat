"""Steps 2.6 and 2.7, Done means 3 and 1, on generated tapes: the Rust engine, by `fefat-cli run`,
fills 10,000 tapes of ticks and 10,000 tapes of bars that Hypothesis draws
(`fefat.reference.generated_cases`), in full or skipping, as the reference engine does: fills,
event log, ledger, and count of ambiguous fills alike. Each example runs ten cases as one batch
in one process. The seed is fixed, so that every run draws the same tapes and a failure
reproduces; Hypothesis shrinks a failure to its smallest tape, which the assertion prints as a
scenario would write it, beside both engines' fills. The drawn cases must reach every rule that
prices a fill on their tapes, flag ambiguous fills on bars alone, and replay both ways, so that
agreement never means that nothing filled. From step 2.9 the cases draw fee tables, funding, and
rolls, and the engines also agree on each fill's fee and contract and on the cost lines; the
cases must pay fees and rebates, under dated tables with their warning, pay funding, roll, and
fill below zero (Done means 1)."""

import time
from collections import Counter

import pytest
from hypothesis import given, seed, settings
from hypothesis import strategies as st

from fefat.reference.costs import DatedFees
from fefat.reference.generated_cases import DrawnTapes, drawn_cases
from fefat.reference.rust_batch import EngineCase, Replay
from fefat.reference.rust_run import (
    CaseComparison,
    RustEngine,
    compare_engines,
    default_binary,
    explained,
)
from fefat.reference.settings import RollHandling

pytestmark = pytest.mark.usefixtures("draws_of_the_seed_alone")

DIFFERENTIAL_SEED = 20_261_026
"""The run's seed, recorded in the pull request."""
EXAMPLES = 1_000
CASES_PER_EXAMPLE = 10
RULES = {
    DrawnTapes.TICKS: frozenset(
        {"F-MKT-01", "F-MKT-02", "F-STP-02", "F-STP-03", "F-STP-05", "F-LMT-03", "F-ROL-02"}
    ),
    DrawnTapes.BARS: frozenset({"F-MKT-03", "F-STP-04", "F-STP-05", "F-LMT-03", "F-ROL-02"}),
}
"""The rules that price fills on trades and TBBO, and on bars (F-TAG-01)."""
TICK_FIDELITIES = frozenset({"tbbo", "trades"})
COSTS = frozenset(
    {
        "fees",
        "rebates",
        "dated fee tables",
        "warnings",
        "funding",
        "roll legs",
        "flattening rolls",
        "fills below zero",
    }
)
"""What the drawn cases must pay and roll across (step 2.9)."""


def cost_coverage(comparison: CaseComparison) -> Counter[str]:
    """What a case paid and rolled across, which the drawn cases must reach (step 2.9): fees,
    rebates, dated fee tables, the warning of a first schedule taken before its date, funding,
    roll legs, and fills at prices below zero."""
    rust, scenario = comparison.rust, comparison.case.scenario
    reached: Counter[str] = Counter()
    reached["fees"] += any(line.reason == "fee" and line.amount > 0 for line in rust.costs)
    reached["rebates"] += any(line.reason == "fee" and line.amount < 0 for line in rust.costs)
    reached["dated fee tables"] += isinstance(scenario.fees, DatedFees)
    reached["warnings"] += any(entry.kind == "warning" for entry in rust.log)
    reached["funding"] += any(line.reason == "funding" for line in rust.costs)
    reached["roll legs"] += any(fill.rule == "F-ROL-02" for fill in rust.fills)
    reached["flattening rolls"] += scenario.settings.roll_handling is RollHandling.FLATTEN and any(
        fill.rule == "F-ROL-02" for fill in rust.fills
    )
    reached["fills below zero"] += any(fill.price < 0 for fill in rust.fills)
    reached["stops closing before a roll"] += any(  # S-fill-068: F-ROL-02 in F-STP-02's wait
        fill.rule == "F-STP-02"
        and fill.contract == roll.rolled_from
        and fill.ts >= roll.session_open
        for roll in scenario.rolls
        for fill in rust.fills
    )
    return reached


@pytest.mark.parametrize("tapes", list(DrawnTapes))
def test_the_rust_engine_fills_10000_generated_tapes_as_the_reference_does(
    tapes: DrawnTapes, capsys: pytest.CaptureFixture[str]
) -> None:
    engine = RustEngine(default_binary())
    cases_run: list[int] = []
    rules: Counter[tuple[str, DrawnTapes]] = Counter()
    replays: Counter[Replay] = Counter()
    ambiguous: list[int] = []
    costs: Counter[str] = Counter()

    @seed(DIFFERENTIAL_SEED)
    @settings(max_examples=EXAMPLES, deadline=None, database=None, print_blob=True)
    @given(
        cases=st.lists(drawn_cases(tapes), min_size=CASES_PER_EXAMPLE, max_size=CASES_PER_EXAMPLE)
    )
    def the_engines_agree(cases: list[EngineCase]) -> None:
        comparisons = compare_engines(engine, cases)
        cases_run.append(len(comparisons))
        for comparison in comparisons:
            fills = comparison.rust.fills
            rules.update(
                (
                    fill.rule,
                    DrawnTapes.TICKS if fill.fidelity in TICK_FIDELITIES else DrawnTapes.BARS,
                )
                for fill in fills
            )
            replays[comparison.case.replay] += 1
            ambiguous.append(comparison.rust.ambiguous_fills)
            costs.update(cost_coverage(comparison))
        found = [
            "\n".join([explained(comparison), *comparison.differences()])
            for comparison in comparisons
            if comparison.differences()
        ]
        if found:
            raise AssertionError(f"Seed {DIFFERENTIAL_SEED}:\n\n" + "\n\n".join(found))

    started = time.perf_counter()
    the_engines_agree()
    elapsed = time.perf_counter() - started

    with capsys.disabled():
        print(
            f"\n{sum(cases_run)} generated tapes on {tapes} through both engines in "
            f"{elapsed:.1f} s, seed {DIFFERENTIAL_SEED}"
        )
        listed = (f"{rule} {count}" for (rule, _), count in sorted(rules.items()))
        print("fills by rule:", ", ".join(listed))
        print(f"replays: {dict(replays)}; ambiguous fills: {sum(ambiguous)}")
        print("cases that paid or rolled:", dict(sorted(costs.items())))
    assert sum(cases_run) >= EXAMPLES * CASES_PER_EXAMPLE
    assert {data for _, data in rules} == {tapes}, f"Expected fills on {tapes}, got {rules}"
    reached = {rule for rule, _ in rules}
    assert reached >= RULES[tapes], f"Expected fills by every rule on {tapes}, got {rules}"
    assert set(replays) == set(Replay)
    assert (sum(ambiguous) > 0) == (tapes is DrawnTapes.BARS)
    reached_costs = {what for what, cases in costs.items() if cases > 0}
    assert reached_costs >= COSTS, f"Expected cases of every cost and roll, got {costs}"
    waited = costs["stops closing before a roll"]
    assert (waited > 0) == (tapes is DrawnTapes.TICKS), (
        f"Expected rolls in a TBBO stop's wait on ticks alone, got {waited}"
    )
