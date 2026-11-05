"""The indicators of step 3.6 that need parameters, features to read, or more sessions than their
defaults find pass the leak detector on the February store (Done means 1): those since a flagged
bar on the 1-minute bars, whose quiet minutes flag a bar in every session; the distance from the
VWAP, with the VWAP and the ATR it reads; relative volume over five sessions, which the store's
week before the window holds; and the session's VWAP and opening range from the cash open, a
local time of each trade date's own day."""

import pytest

import fefat as ff
from fefat.features import FeatureSpec
from generated_minutes import FEBRUARY_WINDOW

SEED = 3


@pytest.mark.parametrize(
    ("spec", "reads", "timeframe"),
    [
        pytest.param(ff.indicators.bars_since("zero_volume", sessions=2), (), "1m", id="bars"),
        pytest.param(ff.indicators.vwap_since("zero_volume", sessions=2), (), "1m", id="vwap"),
        pytest.param(
            ff.indicators.distance_from_vwap("ES"),
            (ff.indicators.session_vwap(), ff.indicators.atr(14)),
            "5m",
            id="distance",
        ),
        pytest.param(ff.indicators.relative_volume(sessions=5), (), "5m", id="relative_volume"),
        pytest.param(ff.indicators.session_vwap(anchor="08:30"), (), "5m", id="vwap_from_08:30"),
        pytest.param(ff.indicators.opening_range(anchor="08:30"), (), "5m", id="range_from_08:30"),
    ],
)
def test_a_session_indicator_passes_the_leak_detector(
    spec: FeatureSpec, reads: tuple[FeatureSpec, ...], timeframe: str
) -> None:
    report = ff.features.validate(spec, "ES", timeframe, *FEBRUARY_WINDOW, reads=reads, seed=SEED)

    assert report.passed, report.summary()
    assert min(count for cut in report.cuts for count in cut.compared.values()) > 0
    assert report.lint == ()
