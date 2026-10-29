"""Step 2.2's reference engine on every fill scenario of `fixtures/scenarios/`: each fills as
its expected fills, marks, and funding say (Done means 1); the runner prints how the scenarios
cover the rules; and `engine.py` stays under 600 lines, every rule of
`docs/spec/fill-semantics.md` having one function, in the engine or beside it in the reference's
modules of money, exit plans, time rules, and the template (step 2.8), and of booking and rolls
(step 2.9), so that one fill can be followed from the tape to the log (Done means 2)."""

from pathlib import Path

import pytest

from fefat.reference.scenario_runner import ScenarioReport, main, run_scenarios
from fefat.reference.scenarios import load_scenarios, specified_rules

ROOT = Path(__file__).resolve().parents[2]
SCENARIOS = ROOT / "fixtures" / "scenarios"
SPECIFICATION = ROOT / "docs" / "spec" / "fill-semantics.md"
REFERENCE = ROOT / "python" / "fefat" / "src" / "fefat" / "reference"
ENGINE = REFERENCE / "engine.py"
RULE_MODULES = (
    ENGINE,
    REFERENCE / "booking.py",
    REFERENCE / "money.py",
    REFERENCE / "exit_plan.py",
    REFERENCE / "rolls.py",
    REFERENCE / "time_rules.py",
    *sorted((REFERENCE / "template").glob("*.py")),
)
"""The modules that hold the reference engine's rules, one function each."""
SCENARIO_IDS = sorted(path.stem for path in SCENARIOS.glob("*.yaml"))
RULES = specified_rules(SPECIFICATION.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def report(tmp_path_factory: pytest.TempPathFactory) -> ScenarioReport:
    """Every scenario run once through the reference engine, with a session cache of its own."""
    return run_scenarios(load_scenarios(SCENARIOS), tmp_path_factory.mktemp("cache"))


@pytest.mark.parametrize("scenario_id", SCENARIO_IDS)
def test_the_reference_engine_fills_each_scenario_as_it_expects(
    report: ScenarioReport, scenario_id: str
) -> None:
    assert report.outcome(scenario_id).differences == ()


@pytest.mark.parametrize(
    ("scenario_id", "order", "ticks"),
    [
        ("S-fill-012", 1, 19),  # a gap: 4995.00 - 4990.25 = 4.75, 19 ticks past the stop
        ("S-fill-009", 1, 1),  # a stop traded at its price: the one tick of F-SLP-01
        ("S-fill-001", 1, 0),  # TBBO: at the quote, no ticks
        ("S-fill-015", 1, 0),  # a limit at its price
        ("S-fill-011", 1, 4),  # a bar opening past the stop: 5006.00 - 5005.00 = 1.00
        ("S-fill-040", 2, 1),  # a bracket stop through the market: its entry's point, minus a tick
    ],
)
def test_each_fill_records_its_slippage_against_its_reference(
    report: ScenarioReport, scenario_id: str, order: int, ticks: int
) -> None:
    fills = [fill for fill in report.outcome(scenario_id).result.fills if fill.order == order]

    assert [fill.slippage_ticks for fill in fills] == [ticks]


def test_the_runner_runs_every_scenario_and_prints_the_rule_coverage(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["--folder", str(SCENARIOS), "--specification", str(SPECIFICATION)])

    printed = capsys.readouterr().out
    assert exit_code == 0
    assert len(SCENARIO_IDS) >= 30
    assert f"{len(SCENARIO_IDS)} of {len(SCENARIO_IDS)} fill scenarios pass" in printed
    coverage = {
        line.split()[0]: line.split()[1:] for line in printed.splitlines() if line[:2] == "F-"
    }
    assert list(coverage) == list(RULES)
    assert all(int(counts[0]) > 0 for counts in coverage.values())


def test_the_engine_is_under_600_lines_with_a_function_for_every_rule() -> None:
    sources = [module.read_text(encoding="utf-8") for module in RULE_MODULES]
    defined = {
        rule: sum(source.count(f"def {rule.lower().replace('-', '_')}(") for source in sources)
        for rule in RULES
    }

    assert len(ENGINE.read_text(encoding="utf-8").splitlines()) < 600
    assert {rule: count for rule, count in defined.items() if count != 1} == {}


def test_one_fill_can_be_followed_from_the_tape_to_the_log(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["--folder", str(SCENARIOS), "--log", "S-fill-012"])

    printed = capsys.readouterr().out
    assert exit_code == 0
    assert "tape" in printed
    assert "order 1: the trade at 4990.25 reached the stop at 4995 [F-STP-01]" in printed
    assert "order 1: sell 1 at 4990.25" in printed
    assert "[F-STP-03]" in printed
    assert "S-fill-012 passes" in printed
