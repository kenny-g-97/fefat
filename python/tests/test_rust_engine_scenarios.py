"""Step 2.6's Done means 1 and 3 and step 2.7's Done means 1 on the scenarios: every scenario of
`fixtures/scenarios/`, on ticks and on bars of every timeframe, runs through the Rust engine, by
`fefat-cli run`, in full and skipping by the coarser bars its records make, to the fills it
expects and to the fills, event log, ledger, and count of ambiguous fills of the reference
engine. Each test prints the scenario's tape, orders, and expected fills beside both engines'
fills (`pytest -rA` shows them)."""

from pathlib import Path

import pytest

from fefat.reference.rust_batch import Replay
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


@pytest.fixture(scope="module")
def comparisons(
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[tuple[str, Replay], CaseComparison]:
    """Every scenario through both engines, the Rust engine's as one batch for each replay."""
    cache_folder, engine = tmp_path_factory.mktemp("cache"), RustEngine(default_binary())
    found = {}
    for replay in Replay:
        for comparison in compare_engines(engine, engine_cases(SCENARIOS, cache_folder, replay)):
            found[(comparison.case.scenario.id, replay)] = comparison
    return found


@pytest.mark.parametrize("replay", list(Replay))
@pytest.mark.parametrize("scenario_id", [scenario.id for scenario in SCENARIOS])
def test_the_rust_engine_fills_each_scenario_as_expected_and_as_the_reference(
    comparisons: dict[tuple[str, Replay], CaseComparison], scenario_id: str, replay: Replay
) -> None:
    comparison = comparisons[(scenario_id, replay)]
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


def test_the_scenarios_cover_ticks_and_bars_of_every_timeframe() -> None:
    fidelities = {str(scenario.fidelity) for scenario in SCENARIOS}

    assert fidelities == {"tbbo", "trades", "1s", "1m", "5m", "1d"}
