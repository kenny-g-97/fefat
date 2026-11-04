"""Indicators (steps 3.5 and 3.6, `02-engine-and-data.md` §6, D-75, D-78): the common indicators
and those of the trading session as features, each a `FeatureDef` built from Polars expressions
over the signal bars that declares its warm-up, the first giving TA-Lib's values, its seeding
included. Levels (`price`) and distances (`price_distance`)
are in the bars' 1e-9 units of price, so that `ff.Stop(atr=1.5)` reads `atr(14)` as it reads a
distance worked out from the bars; ratios carry no unit. Each takes its parameters by name or in
their order, and a feature of several outputs fills a column for each, `<slot>_<output>`.

    features={"rsi": ff.indicators.rsi(14), "band": ff.indicators.bollinger(n=20)}

| Indicator | Call, with its defaults | Outputs (kind) | Warm-up | TA-Lib |
| --- | --- | --- | --- | --- |
| Simple moving average | `sma(n=20)` | `sma` (price) | n - 1 | SMA |
| Exponential moving average | `ema(n=20)` | `ema` (price) | 13 n | EMA |
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
| Keltner channels | `keltner(n=20, atr_n=10, multiplier=2.0)` | `middle`, `upper`, `lower` (price) | 13 n or 25 atr_n, the longer | EMA and ATR |
| Session VWAP | `session_vwap(anchor=None, time_zone='America/Chicago')` | `session_vwap` (price) | 0 | none |
| Weekly VWAP | `weekly_vwap()` | `weekly_vwap` (price) | 6 sessions | none |
| VWAP since a flagged bar | `vwap_since(flag, sessions=1)` | `vwap_since` (price) | sessions - 1 sessions | none |
| Distance from the VWAP | `distance_from_vwap(instrument)` | `atrs`, `ticks` (ratio) | the VWAP's and the ATR's it reads | none |
| Opening range | `opening_range(minutes=30, anchor=None, time_zone='America/Chicago')` | `range_high`, `range_low` (price), `range_width` (price_distance) | 0 | none |
| Session before | `previous_session()` | `previous_high`, `previous_low`, `previous_close` (price) | 1 session | none |
| Session high and low | `session_high_low()` | `session_high`, `session_low` (price) | 0 | none |
| Time since the open | `time_since_open()` | `bars_since_open` (count), `minutes_since_open` (other) | 0 | none |
| Bars since a flagged bar | `bars_since(flag, sessions=1)` | `bars_since` (count) | sessions - 1 sessions | none |
| Realised volatility | `realised_volatility(n=20)` | `realised_volatility` (ratio) | n | none |
| Relative volume | `relative_volume(sessions=20, time_zone='America/Chicago')` | `relative_volume` (ratio) | sessions sessions | none |
| Cumulative delta | `cumulative_delta()` | `delta`, `cumulative_delta` (count) | 0 | none |
| Swings | `swings(n=5)` | `swing_high`, `swing_low` (flag), `swing_high_price`, `swing_low_price` (price) | 2 n | none |

TA-Lib's seeding is reproduced exactly: an exponential average starts from the simple average of
its first values, as EMA, MACD, RSI, ATR, ADX, and Keltner's do, where Polars' `ewm_mean` would
start from the first value alone, and every output is null until TA-Lib's first value. An
exponential average never forgets those first bars, so its warm-up is the bars after which they
weigh less than 4e-11: 25 times the period of Wilder's averages, in RSI and ATR, 13 times an
EMA's, which forgets twice as fast, 25 times MACD's longest, whose difference of two averages
magnifies what they keep, and 50 times ADX's, smoothed twice. Values from any start then agree
within the 1e-9 the feature cache and the leak detector allow (D-73, D-74). Where TA-Lib
divides by zero, as the RSI of closes that have not moved, the stochastic of a flat range, or the
rate of change after a close of zero, it gives 0 or 50 and these give null, as do the
stochastic's averages over such a bar, while ADX skips one, as TA-Lib's does. `round_down_to_tick`
and `round_up_to_tick` put a price worked out from them on the instrument's tick (F-RND-01).

The session's indicators (step 3.6, D-71, D-78) start at the calendar's session open, the open
every trade date and bar take, 17:00 Chicago the evening before for CME's equity index, or from a
local time of day in the product's time zone on the trade date's own day, such as
`anchor="08:30"` for the cash open. A session is a trade date's rows of the grid, which leave
halts out (D-43), and the session before is the trade date before in the session table. An
indicator that remembers whole sessions declares them as its warm-up, which the runtime reads
before a window on any timeframe; one since a flagged bar forgets it after the sessions it is
given. Cumulative delta reads the prints' aggressor sides through the trades input, null where
they carry none, and a swing is flagged on the n-th bar after it, never on its own bar."""

from fefat.indicators.averages import ema, macd, sma, wma
from fefat.indicators.bands import bollinger, donchian, keltner
from fefat.indicators.oscillators import adx, momentum, obv, roc, rsi, stochastic
from fefat.indicators.ranges import (
    atr,
    realised_volatility,
    standard_deviation,
    true_range,
    z_score,
)
from fefat.indicators.sessions import (
    bars_since,
    opening_range,
    previous_session,
    session_high_low,
    time_since_open,
)
from fefat.indicators.swings import swings
from fefat.indicators.ticks import round_down_to_tick, round_up_to_tick
from fefat.indicators.volume import cumulative_delta, relative_volume
from fefat.indicators.vwaps import distance_from_vwap, session_vwap, vwap_since, weekly_vwap

__all__ = [
    "adx",
    "atr",
    "bars_since",
    "bollinger",
    "cumulative_delta",
    "distance_from_vwap",
    "donchian",
    "ema",
    "keltner",
    "macd",
    "momentum",
    "obv",
    "opening_range",
    "previous_session",
    "realised_volatility",
    "relative_volume",
    "roc",
    "round_down_to_tick",
    "round_up_to_tick",
    "rsi",
    "session_high_low",
    "session_vwap",
    "sma",
    "standard_deviation",
    "stochastic",
    "swings",
    "time_since_open",
    "true_range",
    "vwap_since",
    "weekly_vwap",
    "wma",
    "z_score",
]
