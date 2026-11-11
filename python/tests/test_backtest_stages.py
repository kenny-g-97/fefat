"""A run's stages told as it reaches them (step 5.3): `ff.backtest.run` tells a callable its data
loaded, its features and signals computed, its engine running, and its artifacts written, which
the app's backtest job passes on as its progress; a run found saved tells only the stages it went
through."""

import polars as pl

import fefat as ff
from fefat.backtest import RunStage
from notebook_runs import breakout, store_with

WINDOW = ("2026-03-05", "2026-03-09")


def test_a_new_run_tells_its_four_stages_in_order() -> None:
    store_with("ohlcv-1m")
    told: list[RunStage] = []

    ff.backtest.run(breakout(), *WINDOW, progress=told.append)

    assert told == [
        RunStage.DATA_LOADED,
        RunStage.FEATURES_COMPUTED,
        RunStage.ENGINE_RUNNING,
        RunStage.ARTIFACTS_WRITTEN,
    ]


def test_a_run_its_request_finds_saved_tells_no_stage() -> None:
    store_with("ohlcv-1m")
    ff.backtest.run(breakout(), *WINDOW)
    told: list[RunStage] = []

    ff.backtest.run(breakout(), *WINDOW, progress=told.append)

    assert told == []


def test_a_run_its_key_finds_saved_tells_the_stages_it_went_through() -> None:
    # An expression that calls Python keys no request, so the run loads its bars and evaluates
    # its signals before its key finds the folder saved (`fefat.backtest.requests`).
    store_with("ohlcv-1m")
    strategy = breakout().model_copy(
        update={"short_exit": pl.col("close").map_batches(lambda closes: closes < 0)}
    )
    ff.backtest.run(strategy, *WINDOW)
    told: list[RunStage] = []

    ff.backtest.run(strategy, *WINDOW, progress=told.append)

    assert told == [RunStage.DATA_LOADED, RunStage.FEATURES_COMPUTED]
