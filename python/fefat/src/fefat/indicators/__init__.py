"""Indicators (step 3.5, `02-engine-and-data.md` §6, D-75): the common indicators as features,
each a `FeatureDef` of Polars expressions over the signal bars that declares its warm-up and
gives TA-Lib's values, its seeding included. Levels (`price`) and distances (`price_distance`)
are in the bars' 1e-9 units of price, so that `ff.Stop(atr=1.5)` reads `atr(14)` as it reads a
distance worked out from the bars; ratios carry no unit. Each takes its parameters by name or in
their order, and a feature of several outputs fills a column for each, `<slot>_<output>`.

    features={"rsi": ff.indicators.rsi(14), "band": ff.indicators.bollinger(n=20)}

| Indicator | Call, with its defaults | Outputs (kind) | Warm-up in bars | TA-Lib |
| --- | --- | --- | --- | --- |
| Simple moving average | `sma(n=20)` | `sma` (price) | n - 1 | SMA |
| Exponential moving average | `ema(n=20)` | `ema` (price) | 25 n | EMA |
| Weighted moving average | `wma(n=20)` | `wma` (price) | n - 1 | WMA |
| MACD | `macd(fast=12, slow=26, signal=9)` | `macd`, `signal`, `histogram` (price_distance) | 25 times the longest | MACD |
| Relative strength index | `rsi(n=14)` | `rsi` (ratio, 0 to 100) | 25 n | RSI |
| Stochastic | `stochastic(n=14, k_smoothing=3, d_smoothing=3)` | `percent_k`, `percent_d` (ratio, 0 to 100) | n + k_smoothing + d_smoothing - 3 | STOCH |
| Rate of change | `roc(n=10)` | `roc` (ratio, in percent) | n | ROC |
| Momentum | `momentum(n=10)` | `momentum` (price_distance) | n | MOM |
| Average directional index | `adx(n=14)` | `adx`, `plus_di`, `minus_di` (ratio, 0 to 100) | 50 n | ADX, PLUS_DI, MINUS_DI |
| On-balance volume | `obv(n=20)` | `obv` (count) | n | OBV's change over n bars |
| True range | `true_range()` | `true_range` (price_distance) | 1 | TRANGE |
| Average true range | `atr(n=14)` | `atr` (price_distance) | 25 n | ATR |
| Standard deviation | `standard_deviation(n=20)` | `standard_deviation` (price_distance) | n - 1 | STDDEV |
| Z-score | `z_score(n=20)` | `z_score` (ratio) | n - 1 | (close - SMA) / STDDEV |
| Bollinger bands | `bollinger(n=20, deviations=2.0)` | `middle`, `upper`, `lower` (price), `band_width`, `percent_b` (ratio) | n - 1 | BBANDS |
| Donchian channels | `donchian(n=20)` | `upper`, `lower`, `middle` (price) | n - 1 | MAX, MIN |
| Keltner channels | `keltner(n=20, atr_n=10, multiplier=2.0)` | `middle`, `upper`, `lower` (price) | 25 times the longest | EMA and ATR |

TA-Lib's seeding is reproduced exactly: an exponential average starts from the simple average of
its first values, as EMA, MACD, RSI, ATR, ADX, and Keltner's do, where Polars' `ewm_mean` would
start from the first value alone, and every output is null until TA-Lib's first value. An
exponential average never forgets those first bars, so its warm-up is 25 times its period, after
which they weigh less than 1e-11, and ADX's, smoothed twice, 50 times; values from any start then
agree within the 1e-9 the feature cache and the leak detector allow (D-73, D-74). Where TA-Lib
divides by zero, as the RSI of closes that have not moved or the stochastic of a flat range, it
gives 0 or 50 and these give null. `round_down_to_tick` and `round_up_to_tick` put a price worked
out from them on the instrument's tick (F-RND-01)."""

from fefat.indicators.averages import ema, macd, sma, wma
from fefat.indicators.bands import bollinger, donchian, keltner
from fefat.indicators.oscillators import adx, momentum, obv, roc, rsi, stochastic
from fefat.indicators.ranges import atr, standard_deviation, true_range, z_score
from fefat.indicators.ticks import round_down_to_tick, round_up_to_tick

__all__ = [
    "adx",
    "atr",
    "bollinger",
    "donchian",
    "ema",
    "keltner",
    "macd",
    "momentum",
    "obv",
    "roc",
    "round_down_to_tick",
    "round_up_to_tick",
    "rsi",
    "sma",
    "standard_deviation",
    "stochastic",
    "true_range",
    "wma",
    "z_score",
]
