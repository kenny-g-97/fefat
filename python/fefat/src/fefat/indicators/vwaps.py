"""Volume-weighted average prices (step 3.6, D-71, D-78): the session's, from its open or from a
local time of day such as the cash open; the week's, from its first session; one from the last
bar a Boolean column flags; and how far the close lies from the session's, in ATRs and in ticks.
Each weighs a bar's own vwap by its volume, or its typical price where the data has no vwap
(`anchors.bar_price`), and is a price in the bars' 1e-9 units, null until some volume has traded
since its start."""

import polars as pl

from fefat.features.definition import SessionCount, feature
from fefat.indicators.anchors import bar_price, flagged, session_start, within_sessions
from fefat.indicators.ranges import atr
from fefat.indicators.ticks import instrument_tick
from fefat.market.calendar_definition import LocalTime, TimeZoneName
from fefat.market.contracts import parse_contract_name


def volume_weighted(volume: pl.Expr, partition: pl.Expr | str) -> pl.Expr:
    """The average of the bars' prices (`bar_price`) weighted by `volume` from each partition's
    first row to each row, null until some volume has traded and on the rows `volume` is null."""
    weighted = (bar_price() * volume).cum_sum().over(partition)
    total = volume.cum_sum().over(partition)
    return pl.when(total > 0).then(weighted / total)


@feature(
    params={"anchor": None, "time_zone": "America/Chicago"},
    outputs={"session_vwap": "price"},
)
def session_vwap(bars: pl.LazyFrame, anchor: LocalTime | None, time_zone: TimeZoneName) -> pl.Expr:
    """The session's VWAP from its open, or from the local time of day `anchor` in `time_zone` on
    the trade date's own day, such as `anchor="08:30"` for the cash open of CME's equity index,
    from the first bar opening at or after it, null before it."""
    since = pl.col("ts_open") >= session_start(anchor, time_zone)
    return volume_weighted(pl.when(since).then(pl.col("volume").cast(pl.Float64)), "trade_date")


@feature(warmup_sessions=6, outputs={"weekly_vwap": "price"})
def weekly_vwap(bars: pl.LazyFrame) -> pl.Expr:
    """The week's VWAP from the open of its first session, the trade dates of a week running from
    Monday, whose session CME opens on Sunday evening; after six sessions of warm-up, one fewer
    than the most trade dates a week holds, so that a value's week opened inside the data read."""
    week = pl.col("trade_date").dt.truncate("1w")
    return volume_weighted(pl.col("volume").cast(pl.Float64), week)


@feature(
    params={"sessions": 1},
    warmup_sessions=lambda sessions: sessions - 1,
    outputs={"vwap_since": "price"},
)
def vwap_since(bars: pl.LazyFrame, flag: str, sessions: SessionCount) -> pl.Expr:
    """The VWAP from the last bar on which the Boolean column `flag` of the bars is true, that
    bar's volume included, such as `roll_flag` for a roll's first bar: null before the first such
    bar, and once the last lies further back than this session and the `sessions` - 1 before it,
    which bound what it remembers (`anchors.within_sessions`)."""
    flags = flagged(bars, flag)
    vwap = volume_weighted(pl.col("volume").cast(pl.Float64), flags.cum_sum())
    return pl.when(within_sessions(flags, sessions)).then(vwap)


@feature(inputs=[session_vwap, atr], outputs={"atrs": "ratio", "ticks": "ratio"})
def distance_from_vwap(bars: pl.LazyFrame, instrument: str) -> dict[str, pl.Expr]:
    """How far the close lies above the session's VWAP, below it when negative: in ATRs, over the
    ATR on the row, null where it is 0, and in ticks of the root `instrument`, as a run reads its
    tick, the trader's saved instruments included; the VWAP and the ATR those of the slots given
    beside it, with their parameters."""
    # shortcut: the tick is read when the feature is evaluated, which the feature cache's key does
    # not pin; key the instrument table when a saved instrument's tick can change (BACKLOG.md).
    distance = pl.col("close") - pl.col("session_vwap")
    return {
        "atrs": pl.when(pl.col("atr") > 0).then(distance / pl.col("atr")),
        "ticks": distance / _tick_of(bars, instrument),
    }


def _tick_of(bars: pl.LazyFrame, instrument: str) -> int:
    """The tick of the root `instrument`, refused unless each contract of `bars` is one of it: a
    contract named after it, as `ESM2026` is, or it, as a perpetual is, never another root that
    starts with it, as `BTCUSDT-PERP` does with spot's `BTCUSDT`."""
    contracts = bars.select(pl.col("contract").unique().sort()).collect().get_column("contract")
    foreign = [each for each in contracts if _root_of(each) != instrument]
    if foreign:
        raise ValueError(
            f"Expected the bars of {instrument}, whose tick the distance counts in, got contract "
            f"{foreign[0]}."
        )
    return instrument_tick(instrument)


def _root_of(contract: str) -> str:
    """The root a contract's name gives, or the name itself, as a perpetual's or a spot pair's."""
    try:
        root, _ = parse_contract_name(contract)
    except ValueError:
        return contract
    return root
