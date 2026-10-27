"""Step 2.6, Done means 1 and 3 on the scenarios: every scenario of `fixtures/scenarios/` on
ticks runs through the Rust engine, by `fefat-cli run`, to the fills it expects and to the fills
and the event log of the reference engine. Each test prints the scenario's tape, orders, and
expected fills beside both engines' fills (`pytest -rA` shows them). The scenarios on bars run
from step 2.7, which replays bars."""

from pathlib import Path

import pytest

from fefat.market.fidelity import TickFidelity
from fefat.reference.rust_run import (
    CaseComparison,
    RustEngine,
    compare_engines,
    default_binary,
    engine_cases,
    explained,
)
from fefat.reference.scenarios import load_scenarios

ROOT = Path(__file__).resolve().parents[2]
SCENARIOS = load_scenarios(ROOT / "fixtures" / "scenarios")
ON_TICKS = [scenario for scenario in SCENARIOS if isinstance(scenario.fidelity, TickFidelity)]


@pytest.fixture(scope="module")
def comparisons(tmp_path_factory: pytest.TempPathFactory) -> dict[str, CaseComparison]:
    """Every scenario on ticks through both engines, the Rust engine's as one batch."""
    cases = engine_cases(ON_TICKS, tmp_path_factory.mktemp("cache"))
    ran = compare_engines(RustEngine(default_binary()), cases)
    return {comparison.case.scenario.id: comparison for comparison in ran}


@pytest.mark.parametrize("scenario_id", [scenario.id for scenario in ON_TICKS])
def test_the_rust_engine_fills_each_tick_scenario_as_expected_and_as_the_reference(
    comparisons: dict[str, CaseComparison], scenario_id: str
) -> None:
    comparison = comparisons[scenario_id]
    print(explained(comparison))
    expected = [
        (fill.order, fill.ts, fill.price, fill.rule, tuple(sorted(fill.flags)))
        for fill in comparison.case.scenario.expected.fills
    ]

    rust = [
        (fill.order, fill.ts, fill.price, fill.rule, fill.flags) for fill in comparison.rust.fills
    ]

    assert rust == expected
    assert comparison.differences() == ()


def test_the_scenarios_on_ticks_are_those_of_trades_and_tbbo() -> None:
    on_ticks = sorted(scenario.id for scenario in ON_TICKS)

    assert len(on_ticks) == 28, f"Expected the 28 scenarios on ticks of step 2.6, got {on_ticks}"


def test_a_scenario_on_bars_waits_for_step_2_7(tmp_path: Path) -> None:
    on_bars = next(scenario for scenario in SCENARIOS if scenario not in ON_TICKS)

    with pytest.raises(ValueError, match=r"bar fidelities arrive in step 2\.7"):
        RustEngine(default_binary()).run(engine_cases([on_bars], tmp_path))
