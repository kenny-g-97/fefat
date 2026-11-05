"""Signal bars built by hand for the session-aware indicators' tests (step 3.6): five-minute bars
of trade dates at clock times in Chicago, each with its high, low, close, volume, and vwap, which
an indicator reads as it reads `load`'s."""

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import polars as pl

from fefat.features import FeatureSpec

SECOND = 1_000_000_000
FIVE_MINUTES = 300 * SECOND
BAR_SCHEMA = pl.Schema(
    {
        "ts_open": pl.Int64,
        "ts_close": pl.Int64,
        "trade_date": pl.Date,
        "high": pl.Int64,
        "low": pl.Int64,
        "close": pl.Int64,
        "volume": pl.UInt64,
        "vwap": pl.Int64,
        "close_raw": pl.Int64,
    }
)


def chicago(day: date, clock: str) -> int:
    """The instant of `clock`, `HH:MM`, in Chicago on `day`, in nanoseconds since the epoch."""
    local = datetime.combine(day, time.fromisoformat(clock), ZoneInfo("America/Chicago"))
    return int(local.timestamp()) * SECOND


def bar(
    day: date, clock: str, high: int, low: int, close: int, volume: int, vwap: int | None = None
) -> dict[str, object]:
    """The five-minute bar of trade date `day` opening at `clock` in Chicago on that day."""
    opened = chicago(day, clock)
    return {
        "ts_open": opened,
        "ts_close": opened + FIVE_MINUTES,
        "trade_date": day,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "vwap": vwap,
        "close_raw": close,
    }


def frame(*rows: dict[str, object]) -> pl.DataFrame:
    """The bars `rows`, in their order, with the columns of `BAR_SCHEMA`."""
    return pl.DataFrame(list(rows), schema=BAR_SCHEMA)


def traded(day: date, clock: str, price: int, volume: int = 1) -> dict[str, object]:
    """A bar that traded at one price, its vwap that price."""
    return bar(day, clock, price, price, price, volume, price)


def flagged_sessions() -> pl.DataFrame:
    """Two sessions of three bars, 2026-03-06's and 03-09's, of prices 10 to 60 and a volume of
    one each, the second bar of the first and the third of the second flagged in `event`."""
    clocks = ["08:00", "08:05", "08:10"]
    rows = [
        traded(date(2026, 3, 6), clock, price)
        for clock, price in zip(clocks, [10, 20, 30], strict=True)
    ]
    rows += [
        traded(date(2026, 3, 9), clock, price)
        for clock, price in zip(clocks, [40, 50, 60], strict=True)
    ]
    return frame(*rows).with_columns(event=pl.Series([False, True, False, False, False, True]))


def values_of(spec: FeatureSpec, bars: pl.DataFrame, output: str) -> list[object]:
    """The values of the output `output` of the feature `spec` evaluated over `bars`, its warm-up
    rows' included."""
    return spec.evaluate(bars).collect().get_column(output).to_list()
