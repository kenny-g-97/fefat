"""Done means 1 of step 3.4: each of the twenty-five planted features fails its validation, flagged
by the checks it names (`planted_leaks`)."""

import pytest

import fefat as ff
from fefat.features import ValidationReport
from generated_minutes import FEBRUARY_WINDOW
from planted_leaks import PLANTED, Check, Planted

SEED = 3


def flagged_by(report: ValidationReport) -> set[Check]:
    """The checks of the report that flag its feature."""
    found = set()
    if report.failing_cuts():
        found.add(Check.CUTS)
    if not report.start_check.passed:
        found.add(Check.START)
    if any(finding.rule.looks_ahead for finding in report.lint):
        found.add(Check.LINT)
    return found


def test_the_suite_plants_twenty_five_leaks() -> None:
    names = {planted.spec.definition.name for planted in PLANTED}

    assert len(PLANTED) == len(names) == 25


@pytest.mark.parametrize("planted", PLANTED, ids=lambda planted: planted.spec.definition.name)
def test_a_planted_leak_is_flagged(planted: Planted) -> None:
    report = ff.features.validate(planted.spec, "ES", "1m", *FEBRUARY_WINDOW, seed=SEED)

    assert not report.passed, report.summary()
    assert planted.caught_by <= flagged_by(report), report.summary()
