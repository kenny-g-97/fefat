"""Every indicator of steps 3.5 and 3.6 passes the leak detector of step 3.4 with its defaults, on
ES's 5-minute bars of the February store: its values before each cut are the whole range's, every
cut compares values of each output, the start check agrees from the window's middle, which shows
the declared warm-up enough, and the lint finds nothing (D-12, D-74). Those whose defaults the
store cannot validate are validated apart, each for the reason `VALIDATED_APART` gives."""

from pathlib import Path

import pytest

import fefat as ff
from fefat.features import FeatureDef
from generated_minutes import FEBRUARY_WINDOW

SEED = 3
VALIDATED_APART = {
    "bars_since": "a flag to read: test_leaks_session_indicators",
    "vwap_since": "a flag to read: test_leaks_session_indicators",
    "distance_from_vwap": "an instrument and the features it reads: test_leaks_session_indicators",
    "relative_volume": "twenty sessions before the window: test_indicators_leaks_apart",
    "cumulative_delta": "the prints the store lacks: test_indicators_leaks_apart",
}
"""The indicators the run with defaults leaves out, each with what it needs and where it runs."""
DEFINITIONS = [
    definition
    for name in ff.indicators.__all__
    if isinstance(definition := getattr(ff.indicators, name), FeatureDef)
]
INDICATORS = [definition for definition in DEFINITIONS if definition.name not in VALIDATED_APART]


def test_the_indicators_validated_apart_are_validated_where_their_reasons_say() -> None:
    # The step review: an indicator left out here keeps its leak check only while the module
    # its reason names still validates it.
    tests = Path(__file__).resolve().parents[2]
    assert set(VALIDATED_APART) <= {definition.name for definition in DEFINITIONS}
    for name, reason in VALIDATED_APART.items():
        module = reason.rsplit(": ", 1)[1]
        (path,) = tests.rglob(f"{module}.py")
        assert f"ff.indicators.{name}(" in path.read_text(encoding="utf-8"), (name, module)


@pytest.mark.parametrize("indicator", INDICATORS, ids=lambda definition: definition.name)
def test_an_indicator_passes_the_leak_detector(indicator: FeatureDef) -> None:
    report = ff.features.validate(indicator(), "ES", "5m", *FEBRUARY_WINDOW, seed=SEED)

    assert report.passed, report.summary()
    assert min(count for cut in report.cuts for count in cut.compared.values()) > 0
    assert report.lint == ()
