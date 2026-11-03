"""The leak detector of step 3.4 (`02-engine-and-data.md` §6, ADR-0010, D-71): `validate` cuts every
input at instants, compares the values before each cut with the whole range's, moves the window's
start, and reads the source with the lint. Its report names the first failing cut and row of a
leak (Done means 2), cuts at every kind of instant the amendment lists, repeats with its seed,
fails a cut that compares no value, loads each grid once, and is kept beside the feature's
versions. The planted and clean suites are `python/tests/features/leaks/`."""

import os
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any

import polars as pl
import pytest

import fefat as ff
from fefat.config import resolve_paths
from fefat.features import TimeframeInput, ValidationReport
from fefat.features.cuts import CutKind
from fefat.features.examples import rsi
from fefat.features.source_lint import LintRule
from fefat.features.validation_report import CutResult, FeatureRead, StartCheck
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


@ff.feature(
    inputs=[next_close, TimeframeInput(timeframe="15m")], outputs={"next_15m_close": "price"}
)
def next_15m_close(bars: pl.LazyFrame) -> pl.Expr:
    return pl.col("next_close")


def test_a_leak_inside_a_feature_of_a_higher_timeframe_fails_while_its_bar_is_in_progress() -> None:
    # The amendment and the step review: every input is cut at its own availability, so a
    # 15-minute bar in progress at a cut is held back, and a feature reading the next 15-minute
    # close through the feature it reads fails each cut inside a 15-minute bar, though its own
    # source reads nothing ahead; the lint warns of the feature it reads.
    report = ff.features.validate(
        next_15m_close(), "ES", "1m", *FEBRUARY_WINDOW, reads=[next_close()], seed=SEED
    )

    inside = [cut for cut in report.cuts if CutKind.HIGHER_TIMEFRAME_LAST_BAR in cut.kinds]
    warned = [(finding.feature, finding.rule) for finding in report.lint]
    assert warned == [("next_close", LintRule.NEGATIVE_SHIFT)]
    assert inside
    assert not any(cut.passed for cut in inside)


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
    # The step and ponytail reviews: the report keeps what drew its cuts, so that it repeats.
    read = FeatureRead(name="rsi", hash=rsi.hash, parameters={"n": 14})
    assert (report.reads, report.stops, report.random_cuts) == ((read,), 24, 16)


def test_a_warmup_longer_than_the_data_compares_nothing_and_fails() -> None:
    # The amendment: a spliced series' first session has no front, so the store's bars start on
    # 2026-02-03, and to the session after the window's last, 02-09, they hold 6,900 minutes, fewer
    # than the 7,500 bars RSI(300) needs: no cut and not the start check compares a value, and the
    # report fails rather than pass on nothing.
    report = ff.features.validate(rsi(n=300), "ES", "1m", "2026-02-03", "2026-02-06", seed=SEED)

    assert report.uncompared() == ["rsi"]
    assert not report.failing_cuts()
    assert not report.passed
    assert "values: no value of rsi compared at any cut, as a warm-up longer" in (report.summary())


@ff.feature(outputs={"roll_close": "price"})
def roll_close(bars: pl.LazyFrame) -> pl.Expr:
    return pl.when(pl.col("roll_flag")).then(pl.col("close")).forward_fill()


def test_an_output_null_until_the_roll_passes_with_its_values_compared_after_it() -> None:
    # The code review and the leakage audit: an output null for whole sessions by design compares
    # nothing at the cuts before its first value, which decide nothing alone, and the cuts after
    # the roll at the open of 2026-02-19 compare its values, so the report passes.
    report = ff.features.validate(roll_close(), "ES", "1m", *FEBRUARY_WINDOW, seed=SEED)

    assert any(cut.compared == {"roll_close": 0} for cut in report.cuts)
    assert report.passed, report.summary()


def test_a_start_the_data_does_not_let_move_checks_nothing_and_fails() -> None:
    # The ponytail review: at the store's first session, 2026-02-03, the warm-up before the
    # window's middle trade date starts where the whole range does, so the start check compares
    # the feature with itself; it fails rather than pass on nothing.
    report = ff.features.validate(previous_close(), "ES", "1m", "2026-02-03", "2026-02-05")

    check = report.start_check
    assert (check.whole_from, check.later_from) == (date(2026, 2, 3), date(2026, 2, 3))
    assert not check.passed
    assert "the start did not move, since the data begins on 2026-02-03" in str(check)
    assert not report.passed


@ff.feature(outputs={"session_close": "price"})
def session_close_from_the_store(bars: pl.LazyFrame) -> pl.LazyFrame:
    daily = ff.market.load("ES", "1d", "2026-02-02", "2026-02-20")
    closes = daily.select("trade_date", session_close="close")
    joined = bars.join(closes, on="trade_date", how="left", maintain_order="left")
    return joined.select("ts_close", "session_close")


def test_a_feature_reading_data_itself_fails_where_the_cuts_cannot_see_it() -> None:
    # The leakage audit: a feature that loads the store itself reads what the cuts never cut, so
    # each session's close sits on its every row and every cut agrees; the lint reads the load and
    # fails the report.
    report = ff.features.validate(
        session_close_from_the_store(), "ES", "1m", *FEBRUARY_WINDOW, seed=SEED
    )

    assert not report.failing_cuts()
    assert report.start_check.passed
    assert [finding.rule for finding in report.lint] == [LintRule.READS_DATA]
    assert not report.passed
    assert report.summary().splitlines()[0].endswith("FAILED")


@ff.feature(inputs=[session_close_from_the_store], outputs={"wrapped": "price"})
def wrapped(bars: pl.LazyFrame) -> pl.Expr:
    return pl.col("session_close")


def test_data_a_feature_it_reads_loads_itself_fails_too() -> None:
    # The leakage audit, second round: the lint reads every feature the validated one reads,
    # whose data the cuts never cut either.
    report = ff.features.validate(
        wrapped(), "ES", "1m", *FEBRUARY_WINDOW, reads=[session_close_from_the_store()], seed=SEED
    )

    found = [(finding.feature, finding.rule) for finding in report.lint]
    assert found == [("session_close_from_the_store", LintRule.READS_DATA)]
    assert not report.passed


def test_a_frame_a_notebook_loaded_outside_the_feature_fails() -> None:
    # The leakage audit, second round: a frame a cell loaded before, which a feature joins, holds
    # data the cuts never cut, as a load in the feature does.
    closes = ff.market.load("ES", "1d", "2026-02-02", "2026-02-20")
    closes = closes.select("trade_date", session_close="close").collect()

    @ff.feature(outputs={"session_close": "price"})
    def joined_close(bars: pl.LazyFrame) -> pl.LazyFrame:
        joined = bars.join(closes.lazy(), on="trade_date", how="left", maintain_order="left")
        return joined.select("ts_close", "session_close")

    report = ff.features.validate(joined_close(), "ES", "1m", *FEBRUARY_WINDOW, seed=SEED)

    assert not report.failing_cuts()
    assert [finding.rule for finding in report.lint] == [LintRule.READS_DATA]
    assert not report.passed


@ff.feature(outputs={"nothing": "ratio"})
def nothing(bars: pl.LazyFrame) -> pl.Expr:
    return pl.lit(None, dtype=pl.Float64)


def test_an_output_no_cut_compares_a_value_of_fails_the_report_alone() -> None:
    # The leakage audit, second round: an output null everywhere agrees at every cut and in the
    # start check, which moves, so the minimum of values compared alone fails the report.
    report = ff.features.validate(nothing(), "ES", "1m", *FEBRUARY_WINDOW, seed=SEED)

    assert not report.failing_cuts()
    assert report.start_check.passed
    assert report.lint == ()
    assert report.uncompared() == ["nothing"]
    assert not report.passed


def test_values_the_start_check_alone_compared_leave_an_output_uncompared() -> None:
    # The leakage audit, second round: the start check reads the same data after each cut as the
    # whole range, so it cannot see a look-ahead, and values it alone compared count for nothing.
    cut = CutResult(instant=0, kinds=(CutKind.RANDOM,), compared={"x": 0}, difference=None)
    check = StartCheck(
        whole_from=date(2026, 2, 3),
        later_from=date(2026, 2, 4),
        compared_from=date(2026, 2, 5),
        compared={"x": 1_380},
        difference=None,
    )
    report = ValidationReport(
        feature="x",
        hash="0" * 64,
        parameters={},
        reads=(),
        instrument="ES",
        timeframe="1m",
        provider="synthetic",
        start=date(2026, 2, 3),
        end=date(2026, 2, 6),
        seed=SEED,
        stops=0,
        random_cuts=0,
        cuts=(cut,),
        start_check=check,
        lint=(),
        created_at=datetime(2026, 11, 3, tzinfo=UTC),
    )

    assert report.uncompared() == ["x"]
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


def test_a_cut_where_the_store_ends_removes_nothing_and_is_left_out() -> None:
    # The store ends at the close of 2026-02-20: the cuts at and after that close remove nothing,
    # so the report lists none of them, and every cut it lists fails a feature reading ahead.
    report = ff.features.validate(next_close(), "ES", "1m", "2026-02-18", "2026-02-20", seed=SEED)

    assert max(cut.instant for cut in report.cuts) < instant_nanoseconds("2026-02-20T22:00:00Z")
    assert report.failing_cuts() == report.cuts


def test_a_window_of_one_trade_date_or_a_negative_number_of_cuts_is_refused() -> None:
    with pytest.raises(ValueError, match="Expected bars of ES on two trade dates"):
        ff.features.validate(previous_close(), "ES", "1m", "2026-02-11", "2026-02-11")
    with pytest.raises(ValueError, match="got stops=24 and random_cuts=-1"):
        ff.features.validate(previous_close(), "ES", "1m", *FEBRUARY_WINDOW, random_cuts=-1)


def test_stops_caps_the_stops_drawn_beside_the_four_always_cut() -> None:
    # The code review: `stops` caps the stops drawn beside these four, which every validation
    # cuts at, and no more.
    report = ff.features.validate(previous_close(), "ES", "1m", *FEBRUARY_WINDOW, stops=0)

    assert report.stops == 0
    kinds = {kind for cut in report.cuts for kind in cut.kinds}
    closes = [cut.instant for cut in report.cuts if CutKind.SESSION_CLOSE in cut.kinds]
    assert {CutKind.WEEKEND, CutKind.HOLIDAY_HALT} <= kinds
    assert closes[0] == instant_nanoseconds("2026-02-11T22:00:00Z")
    assert closes[-1] == instant_nanoseconds("2026-02-19T22:00:00Z")
    assert len(closes) == 3
