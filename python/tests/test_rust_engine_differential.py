"""Step 2.6, Done means 3 on generated tapes: the Rust engine, by `fefat-cli run`, fills 10,000
tapes that Hypothesis draws (`fefat.reference.generated_cases`) as the reference engine does,
fills and event log alike. Each example runs ten cases as one batch in one process. The seed is
fixed, so that every run draws the same tapes and a failure reproduces; Hypothesis shrinks a
failure to its smallest tape, which the assertion prints as a scenario would write it, beside
both engines' fills. The drawn cases must reach every rule that prices a fill on ticks, so that
agreement never means that nothing filled."""

import time
from collections import Counter

import pytest
from hypothesis import given, seed, settings
from hypothesis import strategies as st

from fefat.reference.generated_cases import drawn_cases
from fefat.reference.rust_batch import EngineCase
from fefat.reference.rust_run import RustEngine, compare_engines, default_binary, explained

DIFFERENTIAL_SEED = 20_261_026
"""The run's seed, recorded in the pull request."""
EXAMPLES = 1_000
CASES_PER_EXAMPLE = 10
TICK_RULES = frozenset({"F-MKT-01", "F-MKT-02", "F-STP-02", "F-STP-03", "F-STP-05", "F-LMT-03"})
"""The rules that price fills on trades and TBBO (F-TAG-01)."""


def test_the_rust_engine_fills_10000_generated_tapes_as_the_reference_does(
    capsys: pytest.CaptureFixture[str],
) -> None:
    engine = RustEngine(default_binary())
    cases_run: list[int] = []
    rules: Counter[str] = Counter()

    @seed(DIFFERENTIAL_SEED)
    @settings(max_examples=EXAMPLES, deadline=None, database=None, print_blob=True)
    @given(cases=st.lists(drawn_cases(), min_size=CASES_PER_EXAMPLE, max_size=CASES_PER_EXAMPLE))
    def the_engines_agree(cases: list[EngineCase]) -> None:
        comparisons = compare_engines(engine, cases)
        cases_run.append(len(comparisons))
        rules.update(fill.rule for comparison in comparisons for fill in comparison.rust.fills)
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
            f"\n{sum(cases_run)} generated tapes through both engines in {elapsed:.1f} s, "
            f"seed {DIFFERENTIAL_SEED}"
        )
        print(
            "fills by rule:", ", ".join(f"{rule} {count}" for rule, count in sorted(rules.items()))
        )
    assert sum(cases_run) >= EXAMPLES * CASES_PER_EXAMPLE
    assert rules.keys() >= TICK_RULES, f"Expected fills by every rule on ticks, got {rules}"
