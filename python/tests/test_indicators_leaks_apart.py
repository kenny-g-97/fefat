"""The indicators of step 3.6 whose defaults the February store cannot hold pass the leak detector
on stores of their own (Done means 1): cumulative delta on the fixtures' ES prints, across the roll
at the open of 2026-03-09, and relative volume over its twenty sessions on a spring of generated
ES bars."""

import fefat as ff
from fefat.features import FeatureSpec
from generated_minutes import SPRING, write_minutes
from notebook_runs import store_with

SEED = 3


def passes(spec: FeatureSpec, window: tuple[str, str]) -> None:
    report = ff.features.validate(spec, "ES", "5m", *window, seed=SEED)

    assert report.passed, report.summary()
    assert min(count for cut in report.cuts for count in cut.compared.values()) > 0
    assert report.lint == ()


def test_cumulative_delta_passes_the_leak_detector_on_the_fixtures_prints() -> None:
    store_with("trades", "ohlcv-1m")

    passes(ff.indicators.cumulative_delta(), ("2026-03-06", "2026-03-09"))


def test_relative_volume_over_twenty_sessions_passes_the_leak_detector() -> None:
    write_minutes(SPRING)

    passes(ff.indicators.relative_volume(), ("2026-02-09", "2026-02-13"))
