"""The indicators of step 3.5 against TA-Lib (Done means 1): every output of every indicator, with
its defaults and with other parameters, is null exactly where TA-Lib gives no value, so that its
seeding is TA-Lib's, and elsewhere within `TOLERANCE` of TA-Lib's value, on a random walk of
20,000 bars and on the fixtures' 1-minute and 5-minute bars of ES and 1-minute bars of bitcoin.
TA-Lib reads the same prices, in the bars' 1e-9 units, as floats. Each indicator's warm-up leaves
no null and no NaN after it on the random walk, whose bars are never flat (Done means 2)."""

from collections.abc import Callable, Iterator
from dataclasses import dataclass

import numpy as np
import polars as pl
import pytest
import talib

import fefat as ff
from fefat.features import FeatureSpec
from notebook_runs import store_with

TOLERANCE = 1e-9
"""The largest difference allowed from TA-Lib's value, as a share of the output's largest
magnitude among the rows compared: the tolerance within which the feature cache and the leak
detector take two evaluations as equal (D-73, D-74). Polars and TA-Lib add and multiply in other
orders, so the last bits of their floats differ."""
GOLDEN_SEED = 20_261_104
"""The random walk's seed, recorded in the pull request."""
POINT = 1_000_000_000
TICK = 250_000_000
MINUTE = 60_000_000_000
SMA = talib.MA_Type.SMA
"""TA-Lib's simple average, the average STOCH and BBANDS take here."""
FIXTURE_BARS = {
    "ES 1m": ("ES", "1m", "2026-03-05", "2026-03-09"),
    "ES 5m": ("ES", "5m", "2026-03-05", "2026-03-09"),
    "BTCUSDT-PERP 1m": ("BTCUSDT-PERP", "1m", "2026-03-07", "2026-03-07"),
}
"""The fixtures' bars the goldens read, by `load`'s arguments."""
indicators = ff.indicators


def random_bars(rows: int, seed: int) -> pl.DataFrame:
    """A random walk of 1-minute bars of ES's tick in 1e-9 units: each close up to four ticks
    from the one before, which it equals one time in nine, each bar's high and low one or two
    ticks beyond its open and close, so that no bar is flat, and a volume of 1 to 999."""
    generator = np.random.default_rng(seed)
    closes = 4_500 * POINT + TICK * np.cumsum(generator.integers(-4, 5, rows))
    opens = np.concatenate([closes[:1], closes[:-1]])
    return pl.DataFrame(
        {
            "ts_close": MINUTE * np.arange(1, rows + 1),
            "open": opens,
            "high": np.maximum(opens, closes) + TICK * generator.integers(1, 3, rows),
            "low": np.minimum(opens, closes) - TICK * generator.integers(1, 3, rows),
            "close": closes,
            "volume": generator.integers(1, 1_000, rows).astype(np.uint64),
        }
    )


@pytest.fixture(scope="module")
def frames(tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict[str, pl.DataFrame]]:
    """The random walk and the fixtures' bars, loaded once for the module."""
    with pytest.MonkeyPatch.context() as patched:
        folder = tmp_path_factory.mktemp("goldens")
        patched.setenv("FEFAT_HOME", str(folder / "fefat-home"))
        patched.setenv("FEFAT_DATA_DIR", str(folder / "fefat-data"))
        store_with("ohlcv-1m")
        loaded = {name: ff.market.load(*args).collect() for name, args in FIXTURE_BARS.items()}
        yield {"random walk": random_bars(20_000, GOLDEN_SEED), **loaded}


@dataclass(frozen=True)
class Prices:
    """The bars' columns as TA-Lib reads them: floats, in the bars' 1e-9 units of price."""

    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray

    @classmethod
    def of(cls, bars: pl.DataFrame) -> "Prices":
        columns = ("high", "low", "close", "volume")
        return cls(*(bars.get_column(name).cast(pl.Float64).to_numpy() for name in columns))


@dataclass(frozen=True)
class Golden:
    """An indicator with its parameters, and TA-Lib's values of each of its outputs."""

    spec: FeatureSpec
    expected: Callable[[Prices], dict[str, np.ndarray]]


def changes(values: np.ndarray, n: int) -> np.ndarray:
    """Each value less the one `n` rows before it, none for the first `n` rows."""
    return np.concatenate([np.full(n, np.nan), values[n:] - values[:-n]])


def bollinger(n: int, deviations: float) -> Callable[[Prices], dict[str, np.ndarray]]:
    def expected(prices: Prices) -> dict[str, np.ndarray]:
        upper, middle, lower = talib.BBANDS(prices.close, n, deviations, deviations, SMA)
        return {
            "middle": middle,
            "upper": upper,
            "lower": lower,
            "band_width": (upper - lower) / middle,
            "percent_b": (prices.close - lower) / (upper - lower),
        }

    return expected


def donchian(n: int) -> Callable[[Prices], dict[str, np.ndarray]]:
    def expected(prices: Prices) -> dict[str, np.ndarray]:
        upper, lower = talib.MAX(prices.high, n), talib.MIN(prices.low, n)
        return {"upper": upper, "lower": lower, "middle": (upper + lower) / 2}

    return expected


def keltner(n: int, atr_n: int, multiplier: float) -> Callable[[Prices], dict[str, np.ndarray]]:
    def expected(prices: Prices) -> dict[str, np.ndarray]:
        middle = talib.EMA(prices.close, n)
        offset = multiplier * talib.ATR(prices.high, prices.low, prices.close, atr_n)
        return {"middle": middle, "upper": middle + offset, "lower": middle - offset}

    return expected


def directional(n: int) -> Callable[[Prices], dict[str, np.ndarray]]:
    def expected(prices: Prices) -> dict[str, np.ndarray]:
        bars = (prices.high, prices.low, prices.close)
        return {
            "adx": talib.ADX(*bars, n),
            "plus_di": talib.PLUS_DI(*bars, n),
            "minus_di": talib.MINUS_DI(*bars, n),
        }

    return expected


GOLDENS = [
    Golden(indicators.sma(20), lambda p: {"sma": talib.SMA(p.close, 20)}),
    Golden(indicators.sma(3), lambda p: {"sma": talib.SMA(p.close, 3)}),
    Golden(indicators.ema(20), lambda p: {"ema": talib.EMA(p.close, 20)}),
    Golden(indicators.ema(2), lambda p: {"ema": talib.EMA(p.close, 2)}),
    Golden(indicators.wma(20), lambda p: {"wma": talib.WMA(p.close, 20)}),
    Golden(indicators.wma(7), lambda p: {"wma": talib.WMA(p.close, 7)}),
    Golden(
        indicators.macd(12, 26, 9),
        lambda p: dict(
            zip(("macd", "signal", "histogram"), talib.MACD(p.close, 12, 26, 9), strict=True)
        ),
    ),
    Golden(
        indicators.macd(5, 35, 5),
        lambda p: dict(
            zip(("macd", "signal", "histogram"), talib.MACD(p.close, 5, 35, 5), strict=True)
        ),
    ),
    Golden(indicators.rsi(14), lambda p: {"rsi": talib.RSI(p.close, 14)}),
    Golden(indicators.rsi(2), lambda p: {"rsi": talib.RSI(p.close, 2)}),
    Golden(
        indicators.stochastic(14, 3, 3),
        lambda p: dict(
            zip(
                ("percent_k", "percent_d"),
                talib.STOCH(p.high, p.low, p.close, 14, 3, SMA, 3, SMA),
                strict=True,
            )
        ),
    ),
    Golden(
        indicators.stochastic(5, 1, 4),
        lambda p: dict(
            zip(
                ("percent_k", "percent_d"),
                talib.STOCH(p.high, p.low, p.close, 5, 1, SMA, 4, SMA),
                strict=True,
            )
        ),
    ),
    Golden(indicators.roc(10), lambda p: {"roc": talib.ROC(p.close, 10)}),
    Golden(indicators.roc(1), lambda p: {"roc": talib.ROC(p.close, 1)}),
    Golden(indicators.momentum(10), lambda p: {"momentum": talib.MOM(p.close, 10)}),
    Golden(indicators.momentum(3), lambda p: {"momentum": talib.MOM(p.close, 3)}),
    Golden(indicators.adx(14), directional(14)),
    Golden(indicators.adx(2), directional(2)),
    Golden(indicators.obv(20), lambda p: {"obv": changes(talib.OBV(p.close, p.volume), 20)}),
    Golden(indicators.obv(1), lambda p: {"obv": changes(talib.OBV(p.close, p.volume), 1)}),
    Golden(indicators.true_range(), lambda p: {"true_range": talib.TRANGE(p.high, p.low, p.close)}),
    Golden(indicators.atr(14), lambda p: {"atr": talib.ATR(p.high, p.low, p.close, 14)}),
    Golden(indicators.atr(1), lambda p: {"atr": talib.ATR(p.high, p.low, p.close, 1)}),
    Golden(
        indicators.standard_deviation(20),
        lambda p: {"standard_deviation": talib.STDDEV(p.close, 20, 1)},
    ),
    Golden(
        indicators.standard_deviation(5),
        lambda p: {"standard_deviation": talib.STDDEV(p.close, 5, 1)},
    ),
    Golden(
        indicators.z_score(20),
        lambda p: {"z_score": (p.close - talib.SMA(p.close, 20)) / talib.STDDEV(p.close, 20, 1)},
    ),
    Golden(indicators.bollinger(20, 2.0), bollinger(20, 2.0)),
    Golden(indicators.bollinger(10, 1.5), bollinger(10, 1.5)),
    Golden(indicators.donchian(20), donchian(20)),
    Golden(indicators.donchian(5), donchian(5)),
    Golden(indicators.keltner(20, 10, 2.0), keltner(20, 10, 2.0)),
    Golden(indicators.keltner(10, 20, 1.5), keltner(10, 20, 1.5)),
]
"""Every indicator with its defaults and with other parameters, and TA-Lib's values of it, or
of what it is made of where TA-Lib has none: the z-score from SMA and STDDEV, the band width
and %b from BBANDS, Donchian channels from MAX and MIN, Keltner channels from EMA and ATR, and
OBV over a window from OBV's change over it."""


def call_text(spec: FeatureSpec) -> str:
    """The indicator's call as its id, such as `rsi(n=14)`."""
    parameters = ", ".join(f"{name}={value!r}" for name, value in dict(spec.parameters).items())
    return f"{spec.definition.name}({parameters})"


def assert_matches(label: str, ours: pl.Series, theirs: np.ndarray) -> None:
    """`ours` null exactly where `theirs`, TA-Lib's, holds no value, and elsewhere within
    `TOLERANCE` of it."""
    missing, absent = ours.is_null().to_numpy(), np.isnan(theirs)
    apart = np.flatnonzero(missing != absent)
    if apart.size:
        row = int(apart[0])
        raise AssertionError(
            f"{label}: at row {row}, {ours[row]} here and {theirs[row]} in TA-Lib, "
            f"{apart.size} rows apart"
        )
    expected = theirs[~absent]
    assert expected.size > 0, f"{label}: no value to compare"
    gap = np.abs(ours.cast(pl.Float64).to_numpy()[~missing] - expected).max()
    assert gap <= TOLERANCE * np.abs(expected).max(), f"{label}: {gap} from TA-Lib"


@pytest.mark.parametrize("golden", GOLDENS, ids=lambda golden: call_text(golden.spec))
def test_each_output_is_talib_s_from_its_first_value(
    golden: Golden, frames: dict[str, pl.DataFrame]
) -> None:
    for name, bars in frames.items():
        ours = golden.spec.evaluate(bars).collect()
        with np.errstate(invalid="ignore", divide="ignore"):
            expected = golden.expected(Prices.of(bars))
        assert set(expected) == set(golden.spec.definition.outputs)
        for output, theirs in expected.items():
            assert_matches(f"{name}, {output}", ours.get_column(output), theirs)


@pytest.mark.parametrize("golden", GOLDENS, ids=lambda golden: call_text(golden.spec))
def test_no_output_is_null_or_nan_once_the_warmup_has_passed(
    golden: Golden, frames: dict[str, pl.DataFrame]
) -> None:
    # Done means 2: from the row after the declared warm-up on, every output has a finite value.
    spec = golden.spec
    values = spec.evaluate(frames["random walk"]).collect().slice(spec.warmup)

    assert values.height > 0
    for output in spec.definition.outputs:
        column = values.get_column(output)
        assert column.null_count() == 0, f"{output}: null after the warm-up of {spec.warmup}"
        if column.dtype.is_float():
            assert column.is_finite().all(), f"{output}: NaN or infinite after the warm-up"
