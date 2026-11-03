"""The example features of step 3.1 (`fefat.features.examples`): RSI as `02-engine-and-data.md`
§5 writes it, held to its definition worked out in plain Python; ATR in the bars' 1e-9 units of
price, which the execution template reads; and a flag of a window of the trading day in local
time, across the clock change of 2026-03-08 and on the fixtures' bars."""

import itertools
import re
import warnings
from collections.abc import Sequence
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import polars as pl
import pytest

import fefat as ff
from fefat.features import FeatureDef, FeatureSpec
from fefat.features.examples import atr, in_session_window, rsi
from notebook_runs import store_with

POINT = 1_000_000_000
TICK = 250_000_000
"""ES's tick in the bars' 1e-9 units of price."""


def weighted_means(values: Sequence[float | None], n: int) -> list[float | None]:
    """`ewm_mean(alpha=1/n)` by its definition: at each value, the mean of the values so far, the
    one k bars back weighing (1 - 1/n) ** k, a leading null left null."""
    means: list[float | None] = []
    seen: list[float] = []
    for value in values:
        if value is None:
            means.append(None)
            continue
        seen.append(value)
        weights = [(1 - 1 / n) ** back for back in range(len(seen) - 1, -1, -1)]
        means.append(sum(w * v for w, v in zip(weights, seen, strict=True)) / sum(weights))
    return means


def rsi_by_definition(closes: list[int], n: int) -> list[float | None]:
    """100 less 100 over one plus the mean rise over the mean fall, none while nothing moved."""
    changes = [None, *(after - before for before, after in itertools.pairwise(closes))]
    rises = weighted_means([None if c is None else max(c, 0) for c in changes], n)
    falls = weighted_means([None if c is None else max(-c, 0) for c in changes], n)
    values: list[float | None] = []
    for rise, fall in zip(rises, falls, strict=True):
        if rise is None or fall is None or rise == fall == 0:
            values.append(None)
        elif fall == 0:
            values.append(100.0)
        else:
            values.append(100 - 100 / (1 + rise / fall))
    return values


def test_rsi_is_the_mean_rise_over_the_mean_fall_by_its_definition() -> None:
    steps = [0, 0, 0, 4, -4, 8, 8, 20, 12, 16, 4, 24, 24, 0, -8, 12]
    closes = [5_000 * POINT + step * TICK for step in steps]
    bars = pl.DataFrame({"ts_close": range(len(closes)), "close": closes})

    values = rsi(n=5).evaluate(bars).collect()["rsi"].to_list()

    expected = rsi_by_definition(closes, 5)
    assert [value is None for value in values] == [value is None for value in expected]
    assert [value is None for value in values[:3]] == [True, True, True]
    measured = [value for value in values if value is not None]
    assert measured == pytest.approx([value for value in expected if value is not None], rel=1e-9)
    assert all(0 <= value <= 100 for value in measured)


def test_rsi_warms_up_for_ten_times_its_bars() -> None:
    bars = pl.DataFrame({"ts_close": range(200), "close": [5_000 * POINT] * 200})

    frame = rsi(n=14).evaluate(bars).collect()

    assert rsi(n=14).warmup == 140
    assert frame["warmup"].sum() == 140
    assert frame["rsi"].null_count() == 200


def test_atr_averages_the_true_range_in_the_bars_units() -> None:
    bars = pl.DataFrame(
        {
            "ts_close": [60, 120, 180, 240],
            "high": [101 * POINT, 102 * POINT, 101 * POINT, 103 * POINT],
            "low": [99 * POINT, 100 * POINT + 2 * TICK, 100 * POINT, 102 * POINT],
            "close": [
                100 * POINT,
                101 * POINT + 2 * TICK,
                100 * POINT + TICK,
                102 * POINT + 2 * TICK,
            ],
        }
    )
    widened_to_the_close_before = [8 * TICK, 8 * TICK, 6 * TICK, 11 * TICK]

    values = atr(n=2).evaluate(bars).collect()["atr"].to_list()

    assert values == pytest.approx(weighted_means(widened_to_the_close_before, 2), rel=1e-12)
    assert values[0] == 2 * POINT


def chicago(day: int, clock: str) -> int:
    """The instant of `clock` in Chicago on March `day` of 2026, in nanoseconds since the epoch."""
    local = datetime.combine(
        date(2026, 3, day), time.fromisoformat(clock), ZoneInfo("America/Chicago")
    )
    return int(local.timestamp()) * POINT


def flags(closes: list[int], **parameters: str) -> list[bool]:
    frame = pl.DataFrame({"ts_close": closes})
    return in_session_window(**parameters).evaluate(frame).collect()["in_session_window"].to_list()


def test_the_session_window_follows_local_time_across_the_clock_change() -> None:
    clocks = ["08:25", "08:30", "14:55", "15:00"]
    before, after = [chicago(6, c) for c in clocks], [chicago(9, c) for c in clocks]

    assert after[1] - before[1] == (3 * 24 - 1) * 3_600 * POINT
    assert flags(before) == [False, True, True, False]
    assert flags(after) == [False, True, True, False]


def test_a_window_whose_end_comes_first_runs_past_midnight() -> None:
    evening = [chicago(5, c) for c in ["16:59", "17:00", "23:55"]]
    morning = [chicago(6, c) for c in ["00:05", "08:25", "08:30"]]

    flagged = flags([*evening, *morning], start="17:00", end="08:30")

    assert flagged == [False, True, True, True, True, False]


def test_the_session_window_flags_the_cash_session_of_the_fixtures_bars() -> None:
    store_with("ohlcv-1m")
    bars = ff.market.load("ES", "5m", "2026-03-06", "2026-03-06")

    flagged = in_session_window().evaluate(bars).collect()["in_session_window"].sum()

    assert flagged == 78


@pytest.mark.parametrize("example", [rsi, atr])
def test_a_count_of_bars_below_one_is_refused(example: FeatureDef) -> None:
    expected = (
        f"Expected the parameters of feature {example.name} as {{n: int}}, got n=0: Input "
        "should be greater than or equal to 1."
    )

    with pytest.raises(ValueError, match=re.escape(expected)):
        example(n=0)
    assert example.parameter_schema["properties"]["n"]["minimum"] == 1


@pytest.mark.parametrize(
    ("parameters", "refusal"),
    [
        ({"start": "8:30"}, "got start='8:30': String should match pattern"),
        ({"end": 1500}, "got end=1500: Input should be a valid string."),
        (
            {"time_zone": "Mars/Olympus"},
            "got time_zone='Mars/Olympus': Value error, Expected an IANA",
        ),
    ],
)
def test_the_session_windows_parameters_are_checked(
    parameters: dict[str, object], refusal: str
) -> None:
    expected = (
        "Expected the parameters of feature in_session_window as "
        f"{{start: str, end: str, time_zone: str}}, {refusal}"
    )

    with pytest.raises(ValueError, match=re.escape(expected)):
        in_session_window(**parameters)


def atr_strategy() -> ff.SignalStrategy:
    """A long in the cash session when RSI falls below 50, with a stop of 1.5 ATRs."""
    return ff.SignalStrategy(
        instrument="ES",
        timeframe="5m",
        features={"rsi": rsi(n=14), "atr": atr(n=14), "cash": in_session_window()},
        long_entry=(pl.col("rsi") < 50) & pl.col("cash"),
        short_entry=pl.lit(False),
        execution=ff.Execution(
            entry=ff.Market(), stop=ff.Stop(atr=1.5), targets=[ff.Target(r=2)], sizing=ff.Fixed(1)
        ),
    )


def test_the_examples_take_their_slots_in_a_signal_strategy() -> None:
    store_with("ohlcv-1m")
    bars = ff.market.load("ES", "5m", "2026-03-05", "2026-03-09")

    signals = atr_strategy().signals(bars).collect()

    assert signals.select("rsi", "atr", "cash").schema == pl.Schema(
        {"rsi": pl.Float64, "atr": pl.Float64, "cash": pl.Boolean}
    )
    assert signals.select(pl.col("rsi", "atr").is_nan().sum()).row(0) == (0, 0)
    assert signals.head(140).select(pl.col("rsi", "atr").null_count()).row(0) == (140, 140)
    assert signals.slice(140).select(pl.col("rsi", "atr").null_count()).row(0) == (0, 0)
    assert signals["long_entry"].sum() > 0
    assert not signals.head(140)["long_entry"].any()


def test_the_examples_refuse_contracts_stacked_one_after_another() -> None:
    """`load(continuous=False)` gives each contract's bars after the one before, so ESM2026's
    first bars would read ESH2026's last close, days later, as the bar before."""
    store_with("ohlcv-1m")
    stacked = ff.market.load("ES", "5m", "2026-03-05", "2026-03-09", continuous=False)

    with pytest.raises(ValueError, match=re.escape("as load(continuous=False) stacks contracts")):
        rsi(n=14).evaluate(stacked)


@pytest.mark.parametrize("example", [rsi(n=14), atr(n=14), in_session_window()])
def test_the_examples_values_before_a_cut_never_change(example: FeatureSpec) -> None:
    """D-12: cut at each session's first and last close, and a nanosecond either side, the
    fixtures' bars give the values before the cut that the whole three sessions give."""
    store_with("ohlcv-1m")
    bars = ff.market.load("ES", "5m", "2026-03-05", "2026-03-09").collect()
    whole = example.evaluate(bars).collect()
    edges = bars.group_by("trade_date").agg(
        first=pl.col("ts_close").min(), last=pl.col("ts_close").max()
    )
    cuts = {
        edge + step
        for edge in edges["first"].to_list() + edges["last"].to_list()
        for step in (-1, 0, 1)
    }

    for cut in sorted(cuts):
        before = example.evaluate(bars.filter(pl.col("ts_close") <= cut)).collect()
        assert before.rows() == whole.filter(pl.col("ts_close") <= cut).rows(), cut


def test_a_stop_reads_the_example_atr_in_the_bars_units() -> None:
    """The template reads an ATR as a distance in 1e-9 units of price (F-RND-01); an ATR in
    points would lie below one tick, which a run warns of (BACKLOG.md)."""
    store_with("ohlcv-1m")

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        run = ff.backtest.run(atr_strategy(), "2026-03-05", "2026-03-09")

    assert run.trades.height > 0
    assert (run.trades["atr_at_entry"] > TICK).all()
    assert not [str(w.message) for w in caught if "below one tick" in str(w.message)]
