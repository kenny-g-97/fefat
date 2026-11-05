"""The features notebook (step 3.8, Done means 3) runs top to bottom, as Run All does, on ES's
generated 1-minute bars from 2026-01-02 to 04-30, which roll inside its window: a feature of its
own passes the leak detector, three features compute through the cache, the analytics print their
reports on two of them and a flag, every report with the trials counter, which ends at three
features and twenty horizons, and no line holds a price of the bars."""

import re
from pathlib import Path

import polars as pl
import pytest

import fefat as ff
from fefat.market.engine_units import price_text
from generated_minutes import SPRING, write_minutes
from notebook_runs import run_notebook

NOTEBOOK = Path(__file__).resolve().parents[2] / "notebooks" / "03-features.ipynb"
NUMBER = re.compile(r"(?<![\w.])\d+(?:\.\d+)?(?![\w.])")
"""A number standing alone in a line, as a price would be printed."""


def test_the_notebook_judges_two_features_and_shows_the_trials(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    write_minutes(SPRING)
    monkeypatch.setenv("MPLBACKEND", "Agg")

    cells = run_notebook(NOTEBOOK)

    printed = capsys.readouterr().out.splitlines()
    trials = [line for line in printed if line.startswith("Trials so far:")]
    assert printed[0] == "ES 5-minute bars from 2026-01-29 to 2026-04-30"
    assert "The leak detector on ES's 5-minute bars from 2026-04-16: PASSED" in printed
    assert any(
        re.fullmatch(r"first call \d+\.\d\d s, second call \d+\.\d\d s", line) for line in printed
    )
    assert "the second read the same values: True" in printed
    assert [line.split(";")[0] for line in trials] == [
        "Trials so far: 1 feature and 3 horizons examined, 3 feature-horizon pairs",
        "Trials so far: 1 feature and 3 horizons examined, 3 feature-horizon pairs",
        "Trials so far: 2 features and 3 horizons examined, 6 feature-horizon pairs",
        "Trials so far: 2 features and 3 horizons examined, 6 feature-horizon pairs",
        "Trials so far: 3 features and 20 horizons examined, 26 feature-horizon pairs",
        "Trials so far: 3 features and 20 horizons examined, 26 feature-horizon pairs",
    ]
    assert printed[-1] == trials[-1]
    assert cells["quantiles"].frame.height == 15
    assert not printed_prices(printed)


def printed_prices(printed: list[str]) -> set[str]:
    """The prices of the window's 5-minute bars, as text or in 1e-9 units, that a line prints."""
    bars = ff.market.load("ES", "5m", "2026-01-29", "2026-04-30").collect()
    units = pl.concat([bars.get_column(price) for price in ("open", "high", "low", "close")])
    prices = {price_text(price) for price in units} | {str(price) for price in units}
    return prices & {number for line in printed for number in NUMBER.findall(line)}
