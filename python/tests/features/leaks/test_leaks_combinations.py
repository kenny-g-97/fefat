"""Every kind of combination of step 3.7 passes the leak detector of step 3.4 as a hand-written
feature does (Done means 1), on ES's 5-minute bars of the February store, with no feature it reads
given beside it: its code, generated from its description, binds the parameters of each feature
it reads, and the lint finds nothing in it (D-12, D-74)."""

import pytest

import fefat as ff
from fefat.features import combine
from generated_minutes import FEBRUARY_WINDOW

SEED = 3
SMA = ff.indicators.sma(5)
RSI = ff.indicators.rsi(14)
COMBINATIONS = {
    "add": combine.add(SMA, 250_000_000),
    "subtract": combine.subtract("close", SMA),
    "multiply": combine.multiply(SMA, 2),
    "divide": combine.divide("close", SMA),
    "ratio_to": combine.ratio_to("close", SMA),
    "greater_than": combine.greater_than("close", SMA),
    "crosses_above": combine.crosses_above("close", SMA),
    "crosses_below": combine.crosses_below("close", SMA),
    "and": combine.and_(combine.greater_than("close", SMA), combine.greater_than("volume", 0)),
    "or": combine.or_(combine.greater_than("close", SMA), combine.greater_than(SMA, "open")),
    "not": combine.not_(combine.greater_than("close", SMA)),
    "rolling_mean": combine.rolling_mean(SMA, 3),
    "rolling_std": combine.rolling_std("close", 5),
    "rolling_min": combine.rolling_min("low", 5),
    "rolling_max": combine.rolling_max("high", 5),
    "rolling_rank": combine.rolling_rank("close", 5),
    "percent_rank": combine.percent_rank(SMA, 10),
    "z_score": combine.z_score("close", 20),
    "lag": combine.lag(SMA, 2),
    "at_timeframe": combine.at_timeframe(SMA, "15m"),
    "a_higher_timeframe_inside": combine.subtract("close", combine.at_timeframe(SMA, "1h")),
    "scaled_by_atr": combine.scaled_by_atr(combine.subtract("close", SMA), 14),
    "spread_across_instruments": combine.subtract(
        "close", combine.column("close", instrument="NQ")
    ),
    "rsi_stretch": RSI - combine.rolling_mean(RSI, 10),
}
"""A combination of each kind, reading SMA(5) where it reads a feature."""


@pytest.mark.parametrize("kind", list(COMBINATIONS))
def test_a_combination_of_each_kind_passes_the_leak_detector(kind: str) -> None:
    definition = combine.define(f"combined_{kind}", COMBINATIONS[kind])

    report = ff.features.validate(definition(), "ES", "5m", *FEBRUARY_WINDOW, seed=SEED)

    assert report.passed, report.summary()
    assert min(count for cut in report.cuts for count in cut.compared.values()) > 0
    assert report.lint == ()
