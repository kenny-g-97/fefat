"""Done means 1 of step 3.4: each of the twenty-five clean features passes its validation, every
cut comparing values of each of its outputs (`clean_features`)."""

import pytest

import fefat as ff
from clean_features import CLEAN, Clean
from generated_minutes import FEBRUARY_WINDOW

SEED = 3


def test_the_suite_holds_twenty_five_clean_features() -> None:
    names = {clean.spec.definition.name for clean in CLEAN}

    assert len(CLEAN) == len(names) == 25


@pytest.mark.parametrize("clean", CLEAN, ids=lambda clean: clean.spec.definition.name)
def test_a_clean_feature_without_a_leak_passes(clean: Clean) -> None:
    report = ff.features.validate(
        clean.spec, "ES", "1m", *FEBRUARY_WINDOW, reads=clean.reads, seed=SEED
    )

    assert report.passed, report.summary()
    assert min(count for cut in report.cuts for count in cut.compared.values()) > 0
    assert report.lint == ()
