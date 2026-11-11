"""A run of a saved strategy version (step 5.3, D-93): `version.strategy(**parameters)` builds the
strategy from the version's code, stamped with the version, which the run's record names; the
robustness summary counts the parameters the version declares, which the run's config carries, so
that its key covers them; and a version whose code now reads another version of a feature than it
pinned is refused."""

import dataclasses

import polars as pl
import pytest

import fefat as ff
import fefat.indicators
from notebook_runs import store_with
from strategy_code import ES_BREAKOUT, HYPOTHESIS, WITH_A_SLOT

WINDOW = ("2026-03-05", "2026-03-09")
"""The engine guide's breakout on ES, which the fixtures hold; it declares two parameters, and its
execution template sets three numbers."""
WITHOUT_PARAMETERS = (
    ES_BREAKOUT.replace("def strategy(lookback: int = 12, stop_atr: float = 1.5)", "def strategy()")
    .replace("rolling_max(lookback)", "rolling_max(12)")
    .replace("atr=stop_atr", "atr=1.5")
)


def test_a_run_of_a_saved_version_names_it_and_counts_its_declared_parameters() -> None:
    store_with("ohlcv-1m")
    version = ff.strategy.save("breakout", ES_BREAKOUT, hypothesis=HYPOTHESIS)

    run = ff.backtest.run(version.strategy(), *WINDOW)
    written = ff.backtest.run(ff.strategy.from_source(ES_BREAKOUT).with_defaults, *WINDOW)

    pin = run.record.strategy.saved_version
    assert pin is not None
    assert (pin.name, pin.version, pin.hash) == ("breakout", 1, version.hash)
    assert pin.parameters == {"lookback": 12, "stop_atr": 1.5}
    assert run.metrics.robustness.inputs.num_parameters == 2
    assert written.record.strategy.saved_version is None
    assert written.metrics.robustness.inputs.num_parameters == 3
    assert written.hash != run.hash
    assert written.signals.equals(run.signals)


def test_a_versions_parameters_are_bound_strictly() -> None:
    version = ff.strategy.save("breakout", ES_BREAKOUT, hypothesis=HYPOTHESIS)

    wider = version.strategy(stop_atr=2.0)

    assert wider.saved_version is not None
    assert wider.saved_version.parameters == {"lookback": 12, "stop_atr": 2.0}
    with pytest.raises(ValueError, match="Expected the strategy's parameters as its schema"):
        version.strategy(lookback="24")


def test_a_version_without_parameters_shares_the_run_of_its_strategy_written_in_a_notebook() -> (
    None
):
    store_with("ohlcv-1m")
    version = ff.strategy.save("breakout", WITHOUT_PARAMETERS, hypothesis=HYPOTHESIS)

    run = ff.backtest.run(version.strategy(), *WINDOW)
    written = ff.backtest.run(ff.strategy.from_source(WITHOUT_PARAMETERS).with_defaults, *WINDOW)

    assert written.hash == run.hash
    assert run.metrics.robustness.inputs.num_parameters == 3


def test_a_copy_that_changes_the_strategy_is_no_longer_its_version() -> None:
    strategy = ff.strategy.save("breakout", ES_BREAKOUT, hypothesis=HYPOTHESIS).strategy()

    changed = strategy.model_copy(update={"short_entry": pl.col("close") < pl.col("highest")})

    assert strategy.saved_version is not None
    assert strategy.model_copy().saved_version == strategy.saved_version
    assert changed.saved_version is None
    assert changed.declared_parameters is None


def test_a_version_whose_feature_changed_since_its_save_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An indicator of the SDK changed since the version was saved: its code now reads another
    # version of the feature than it pinned, whose values its runs would read.
    code = WITH_A_SLOT.format(feature="ff.indicators.rsi(14)", entry='pl.col("read") < 30')
    version = ff.strategy.save("oversold", code, hypothesis=HYPOTHESIS)
    changed = dataclasses.replace(fefat.indicators.rsi, hash="f" * 64)
    monkeypatch.setattr(fefat.indicators, "rsi", changed)

    with pytest.raises(ValueError, match="save the code again as a new version"):
        version.strategy()


def test_a_saved_versions_fidelity_check_reruns_its_config_with_its_count() -> None:
    # Step 5.3 (its engine accuracy review): the fidelity check reruns the run's days finer than
    # a minute from its config, which a saved version's count joins; the minute fixtures alone
    # hold none, so the check runs on prints here.
    store_with("trades", "ohlcv-1s", "ohlcv-1m")
    version = ff.strategy.save("breakout", ES_BREAKOUT, hypothesis=HYPOTHESIS)

    run = ff.backtest.run(version.strategy(), *WINDOW)

    assert run.record.engine_config["declared_parameters"] == 2
    assert run.metrics.fidelity_check is not None
    assert ff.backtest.fidelity_check(run) == run.metrics.fidelity_check
