"""The leak detector of step 3.4 (`02-engine-and-data.md` §6, ADR-0010, D-71): `validate` cuts every
input at instants, compares the values before each cut with the whole range's, moves the window's
start, and reads the source with the lint. Its report names the first failing cut and row of a
leak (Done means 2), cuts at every kind of instant the amendment lists, repeats with its seed,
fails a cut that compares no value, loads each grid once, and is kept beside the feature's
versions. The planted and clean suites are `python/tests/features/leaks/`."""

import os
from collections.abc import Iterator
from datetime import date
from typing import Any

import polars as pl
import pytest

import fefat as ff
from fefat.config import resolve_paths
from fefat.features import TimeframeInput, ValidationReport
from fefat.features.cuts import CutKind
from fefat.features.examples import rsi
from fefat.features.lint import LintRule
from fefat.market.api import SeriesSource
from fefat.reference.units import instant_nanoseconds
from generated_minutes import FEBRUARY_WINDOW, february_store

SEED = 3


@pytest.fixture(scope="module", autouse=True)
def fefat_folders_in_tmp_path(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    """The February store for the module, in place of the folders each test gets."""
    with february_store(tmp_path_factory.mktemp("validation")):
        yield


@ff.feature(outputs={"next_close": "price"})
def next_close(bars: pl.LazyFrame) -> pl.Expr:
    return pl.col("close").shift(-1)


@ff.feature(warmup=1, outputs={"previous_close": "price"})
def previous_close(bars: pl.LazyFrame) -> pl.Expr:
    return pl.col("close").shift(1)


@ff.feature(inputs=[rsi, TimeframeInput(timeframe="15m")], outputs={"rsi_15m": "ratio"})
def rsi_15m(bars: pl.LazyFrame) -> pl.Expr:
    return pl.col("rsi")


@ff.feature(outputs={"front": "other", "rolled": "flag", "offset": "price_distance"})
def roll_columns(bars: pl.LazyFrame) -> dict[str, pl.Expr]:
    return {
        "front": pl.col("contract").str.contains("M").cast(pl.Int8),
        "rolled": pl.col("roll_flag"),
        "offset": pl.col("adj_offset"),
    }


def test_a_report_names_the_first_failing_cut_and_row_of_a_planted_leak() -> None:
    # Done means 2: a look-ahead shift fails at the first cut, the close of the window's first
    # session, at its last row, whose value with the data after the cut is the next bar's close
    # and without it null; the summary says so, and the lint finds the shift on its line.
    report = ff.features.validate(next_close(), "ES", "1m", *FEBRUARY_WINDOW, seed=SEED)

    first = report.first_failure()
    assert first is not None
    assert first.instant == instant_nanoseconds("2026-02-11T22:00:00Z")
    assert CutKind.SESSION_CLOSE in first.kinds
    assert first.difference is not None
    bars = ff.market.load("ES", "1m", "2026-02-11", "2026-02-12").collect()
    at_the_close = bars.filter(pl.col("ts_close") > first.instant).item(0, "close")
    assert (first.difference.output, first.difference.ts_close) == ("next_close", first.instant)
    assert (first.difference.value, first.difference.against) == (at_the_close, None)
    assert report.failing_cuts() == report.cuts
    assert not report.passed
    summary = report.summary().splitlines()
    assert summary[0].endswith(f"seed {SEED}: FAILED")
    assert summary[1].startswith(
        f"cuts: {len(report.cuts)} of {len(report.cuts)} fail, the first at "
        "2026-02-11T22:00:00Z (session_close): next_close at 2026-02-11T22:00:00Z is "
        f"{at_the_close} with the data after the cut and None without it"
    )
    assert [finding.rule for finding in report.lint] == [LintRule.NEGATIVE_SHIFT]
    assert summary[-1] == f"lint: {report.lint[0]}"


def test_the_cuts_fall_at_every_kind_of_instant_and_repeat_with_their_seed() -> None:
    # The amendment: cuts at instants, a session's close, just after it, inside the break, over a
    # weekend, just before and at the next open, at a holiday's halt, at a roll's open and its
    # first bar, and inside and at the close of a higher timeframe's bar, every one after the
    # first session's close; random cuts from a seed the report records, so that a validation
    # repeats (D-11).
    report = ff.features.validate(rsi_15m(), "ES", "1m", *FEBRUARY_WINDOW, reads=[rsi(n=14)])
    again = ff.features.validate(
        rsi_15m(), "ES", "1m", *FEBRUARY_WINDOW, reads=[rsi(n=14)], seed=report.seed
    )
    other = ff.features.validate(
        rsi_15m(), "ES", "1m", *FEBRUARY_WINDOW, reads=[rsi(n=14)], seed=report.seed + 1
    )

    assert {kind for cut in report.cuts for kind in cut.kinds} == set(CutKind)
    assert min(cut.instant for cut in report.cuts) == instant_nanoseconds("2026-02-11T22:00:00Z")
    assert again.cuts == report.cuts
    assert other.cuts != report.cuts
    assert report.passed, report.summary()


def test_a_warmup_longer_than_the_data_before_a_cut_compares_nothing_and_fails() -> None:
    # The amendment: a spliced series' first session has no front, so the store's bars start on
    # 2026-02-03, whose 1,380 minutes hold fewer than the 1,500 bars RSI(60) needs: a window from
    # it compares no value at its close, and fails, while the cuts from the next close pass.
    report = ff.features.validate(rsi(n=60), "ES", "1m", "2026-02-03", "2026-02-06", seed=SEED)

    first = report.first_failure()
    assert first is not None
    assert first.instant == instant_nanoseconds("2026-02-03T22:00:00Z")
    assert (first.compared, first.difference) == ({"rsi": 0}, None)
    assert "no value of rsi to compare" in str(first)
    after = instant_nanoseconds("2026-02-04T22:00:00Z")
    assert all(cut.passed for cut in report.cuts if cut.instant >= after)
    assert not report.passed


def test_the_detector_loads_each_grid_once(monkeypatch: pytest.MonkeyPatch) -> None:
    # The amendment: the detector loads its inputs once and cuts what it loaded.
    loaded: list[Any] = []
    signal_bars = SeriesSource.signal_bars

    def counted(source: SeriesSource, *arguments: Any, **keywords: Any) -> pl.DataFrame:
        loaded.append(arguments[0])
        return signal_bars(source, *arguments, **keywords)

    monkeypatch.setattr(SeriesSource, "signal_bars", counted)

    ff.features.validate(rsi_15m(), "ES", "1m", *FEBRUARY_WINDOW, reads=[rsi(n=14)], seed=SEED)

    assert sorted(str(timeframe) for timeframe in loaded) == ["15m", "1m"]


def test_the_start_check_moves_the_window_across_the_roll_and_compares_from_its_middle() -> None:
    # The amendment: the start check moves the feature's window, not the roll calendar's anchor,
    # so a feature of the roll's own columns gives the same values from either start; and a
    # running total, which never forgets, fails it alone.
    report = ff.features.validate(roll_columns(), "ES", "1m", *FEBRUARY_WINDOW, seed=SEED)

    check = report.start_check
    assert (check.whole_from, check.later_from) == (date(2026, 2, 11), date(2026, 2, 17))
    assert check.compared_from == date(2026, 2, 17)
    assert check.passed
    assert report.passed, report.summary()
    rolled = ff.market.load("ES", "1m", *FEBRUARY_WINDOW).collect().filter("roll_flag")
    assert rolled.get_column("trade_date").to_list() == [date(2026, 2, 19)]


def test_a_validation_is_kept_beside_the_versions_by_its_hash() -> None:
    # The prompt: the report is stored with the version, the latest of each content hash, and
    # the versions of the feature still save and load.
    report = ff.features.validate(previous_close(), "ES", "1m", *FEBRUARY_WINDOW, seed=SEED)

    features = resolve_paths(os.environ).features_dir
    kept = features / "previous_close" / "validations" / f"{previous_close.hash}.json"
    assert ValidationReport.model_validate_json(kept.read_bytes()) == report
    saved = ff.features.save(previous_close)
    assert ff.features.load("previous_close", saved.version).hash == report.hash


def test_a_window_of_one_trade_date_is_refused() -> None:
    with pytest.raises(ValueError, match="Expected bars of ES on two trade dates"):
        ff.features.validate(previous_close(), "ES", "1m", "2026-02-11", "2026-02-11")
