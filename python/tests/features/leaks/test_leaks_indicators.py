"""Every indicator of step 3.5 passes the leak detector of step 3.4 with its defaults, on ES's
5-minute bars of the February store: its values before each cut are the whole range's, every cut
compares values of each output, the start check agrees from the window's middle, which shows the
declared warm-up enough, and the lint finds nothing (D-12, D-74)."""

import pytest

import fefat as ff
from fefat.features import FeatureDef
from generated_minutes import FEBRUARY_WINDOW

SEED = 3
INDICATORS = [
    definition
    for name in ff.indicators.__all__
    if isinstance(definition := getattr(ff.indicators, name), FeatureDef)
]


@pytest.mark.parametrize("indicator", INDICATORS, ids=lambda definition: definition.name)
def test_an_indicator_passes_the_leak_detector(indicator: FeatureDef) -> None:
    report = ff.features.validate(indicator(), "ES", "5m", *FEBRUARY_WINDOW, seed=SEED)

    assert report.passed, report.summary()
    assert min(count for cut in report.cuts for count in cut.compared.values()) > 0
    assert report.lint == ()
