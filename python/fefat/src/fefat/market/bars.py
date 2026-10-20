"""Bars of any timeframe from trades, and coarser bars from finer ones, with one convention
(`02-engine-and-data.md` §1.4, D-43).

A bar is the bucket `[open + k·Δ, open + (k+1)·Δ)` of its session, anchored at the session's open
(`fefat.market.calendar`), and holds the prints received in it: trades are bucketed by
`ts_recv`, as the vendor buckets its own bars, `ts_open` is the bucket's start, and `ts_close`
its end, when the bar is available. Every built-in session opens on a whole UTC hour, so buckets
of a timeframe that divides an hour fall where the vendor's do. A print takes the trade date of
the session that opened last before it (`SessionTable.assign_trade_dates_or_previous`, as the
importers date a vendor's bars), so a print received after a close, in the break, gets a bar of
its own opening at or after the close: the close cuts a bucket that straddles it in two (an
hourly bar of a 12:15 early close runs from 12:00 to 12:15, and the prints after it form a bar
opening at 12:15). A daily bar is the session itself, from its open to its close, and holds the
session's prints only. Bars are sparse: a bucket without prints has no bar.

`vwap` is rounded down to the prices' 1e-9 units, so each resampling, which weighs rounded
vwaps, can lower it by one more unit; `trade_count` and `vwap` are null where any finer bar
lacks them (a vendor's). A bar closing after `received_until`, the instant before which every
print is in hand (a file's end, or the next session's open for a complete trade date), is held
back: it is left out, and building again with the later prints completes it.

`session_grid` is the dense view for signals: every bucket of every session of a range but those
inside a halt, for each instrument, with its bar where it has one and `zero_volume` where not.

    table = sessions_of(BUILT_IN[CalendarId.CME_EQUITY_INDEX], resolve_paths(os.environ).cache_dir)
    five_minutes = resample_bars(minute_bars, Timeframe(count=5, unit=TimeUnit.MINUTE), table, end)
"""

from datetime import date

import polars as pl

from fefat.market.calendar import SessionTable, utc_text
from fefat.market.schema import (
    Timeframe,
    TimeUnit,
    parse_schema_name,
    polars_schema,
    require_columns,
)

BAR_COLUMNS = polars_schema(parse_schema_name("ohlcv-1m"))
"""The columns of bars, the same for every timeframe (`fefat.market.schema`)."""
GRID_COLUMNS = pl.Schema({**BAR_COLUMNS, "zero_volume": pl.Boolean})
"""The columns of the session grid: a bar's, and whether its bucket holds no print."""

_TRADES_COLUMNS = polars_schema(parse_schema_name("trades"))


def build_bars(
    trades: pl.DataFrame, timeframe: Timeframe, sessions: SessionTable, received_until: int
) -> pl.DataFrame:
    """The bars of `timeframe` of `trades`, which have the store's trades columns, sorted by
    instrument and `ts_open`, with the bars closing after `received_until` held back. Each print
    is a bar of its own, received at `ts_recv`, and `resample_bars` buckets them, so building
    from trades and resampling finer bars follow one rule."""
    require_columns(_TRADES_COLUMNS, trades.schema, "the trades to build bars from")
    dated = sessions.assign_trade_dates_or_previous(trades, "ts_recv")
    price = pl.col("price")
    prints = dated.select(
        ts_open=pl.col("ts_recv"),
        ts_close=pl.col("ts_recv") + 1,
        trade_date=pl.col("trade_date"),
        instrument_id=pl.col("instrument_id"),
        open=price,
        high=price,
        low=price,
        close=price,
        volume=pl.col("size").cast(pl.UInt64),
        trade_count=pl.lit(1, dtype=pl.UInt32),
        vwap=price,
    )
    return resample_bars(prints, timeframe, sessions, received_until)


def resample_bars(
    bars: pl.DataFrame, timeframe: Timeframe, sessions: SessionTable, received_until: int
) -> pl.DataFrame:
    """The bars of `timeframe` from finer `bars` of the same sessions, in the buckets that
    `build_bars` uses, sorted by instrument and `ts_open`, with the bars closing after
    `received_until` held back. A finer bar must lie inside one bucket and hold some volume,
    and a daily bar leaves out the finer bars opening at or after its session's close."""
    require_columns(BAR_COLUMNS, bars.schema, "the bars to resample")
    _require_a_bar_timeframe(timeframe)
    if bars.is_empty():
        return bars
    _require_volume(bars)
    bucketed = in_buckets(bars, timeframe, sessions)
    _require_nested(bucketed, timeframe)
    return (
        bucketed.sort("instrument_id", "ts_open", maintain_order=True)
        .group_by("instrument_id", "trade_date", "bucket_open", "bucket_close")
        .agg(
            open=pl.col("open").first(),
            high=pl.col("high").max(),
            low=pl.col("low").min(),
            close=pl.col("close").last(),
            volume=pl.col("volume").sum(),
            trade_count=_where_every_bar_has("trade_count", pl.col("trade_count").sum()),
            vwap=_where_every_bar_has("vwap", _volume_weighted_vwap()),
        )
        .rename({"bucket_open": "ts_open", "bucket_close": "ts_close"})
        .filter(pl.col("ts_close") <= received_until)
        .sort("instrument_id", "ts_open")
        .select(BAR_COLUMNS.names())
    )


def session_grid(
    bars: pl.DataFrame,
    timeframe: Timeframe,
    sessions: SessionTable,
    received_until: int,
    first: date,
    last: date,
) -> pl.DataFrame:
    """The dense view of sparse `bars` of `timeframe` for signals: for each instrument of
    `bars`, a row for every bucket of every session from trade date `first` to `last`, from
    the instrument's first bar in the grid on and up to the buckets closing by
    `received_until`, but the buckets lying wholly inside a halt (`Session.halts`), sorted by
    instrument and `ts_open`, with the columns of `GRID_COLUMNS`. A bucket with a bar holds it;
    one without is `zero_volume`, with volume and trade count 0, no vwap, and its prices at the
    close of the instrument's bar before it. No row exists, is missing, or is filled because of
    a later bar (D-12), so a contract that stopped trading keeps its rows to `last`: a range
    within a contract's life leaves them out. Bars outside the grid, received after a close or
    inside a halt, are left out; a bucket that a halt covers only in part stays, with the prints
    received in it inside the halt, so these count in a coarse grid's row and in no row of a
    fine grid. Every bar must be a bucket of `timeframe` in its session (no bars of another)."""
    require_columns(BAR_COLUMNS, bars.schema, "the bars of the session grid")
    _require_a_bar_timeframe(timeframe)
    _require_bars_of_the_timeframe(bars, timeframe, sessions)
    in_range = sessions.between(first, last)
    buckets = _outside_halts(_session_buckets(in_range, timeframe), in_range).filter(
        pl.col("ts_close") <= received_until
    )
    instruments = bars.select("instrument_id").unique()
    sparse = bars.rename({"ts_close": "bar_close", "trade_date": "bar_trade_date"})
    grid = buckets.join(instruments, how="cross").join(
        sparse, on=["instrument_id", "ts_open"], how="left"
    )
    _require_one_bar_a_bucket(grid, buckets.height * instruments.height)
    traded = pl.col("bar_close").is_not_null().cum_max().over("instrument_id")
    return _with_empty_buckets_filled(grid.sort("instrument_id", "ts_open").filter(traded))


def _require_a_bar_timeframe(timeframe: Timeframe) -> None:
    if timeframe.unit is TimeUnit.DAY and timeframe.count != 1:
        raise ValueError(
            f"Expected 1d, a session's bar, or an intraday timeframe, got {timeframe}."
        )


def _require_volume(bars: pl.DataFrame) -> None:
    """Refuse a bar, or a print, of no volume, whose vwap would divide by zero."""
    empty = bars.filter(pl.col("volume") == 0)
    if empty.is_empty():
        return
    raise ValueError(
        f"Expected bars of some volume, got {empty.height} without, the first opening at "
        f"{utc_text(empty.item(0, 'ts_open'))}."
    )


def in_buckets(bars: pl.DataFrame, timeframe: Timeframe, sessions: SessionTable) -> pl.DataFrame:
    """The bars beside the bucket of `timeframe` each opens in, `bucket_open` to `bucket_close`:
    a bucket the session's close cuts in two is two, the bars before the close ending at it and
    those after it, in the break, starting at it and ending by the next session's open, so a
    trade date's bars are all complete then; a daily bucket leaves out the bars from the close
    on."""
    dates = pl.col("trade_date")
    first, last = bars.select(first=dates.min(), last=dates.max()).row(0)
    bounds = sessions.between_with_next_opens(first, last).select(
        "trade_date", "next_open", session_open="open", session_close="close"
    )
    joined = bars.join(bounds, on="trade_date", how="left", maintain_order="left")
    _require_their_sessions(joined)
    session_open, session_close = pl.col("session_open"), pl.col("session_close")
    if timeframe.unit is TimeUnit.DAY:
        return joined.filter(pl.col("ts_open") < session_close).with_columns(
            bucket_open=session_open, bucket_close=session_close
        )
    width = timeframe.nominal_nanoseconds()
    start = session_open + (pl.col("ts_open") - session_open) // width * width
    before_the_close = pl.col("ts_open") < session_close
    return joined.with_columns(
        bucket_open=pl.when(before_the_close)
        .then(start)
        .otherwise(pl.max_horizontal(start, session_close)),
        bucket_close=pl.when(before_the_close)
        .then(pl.min_horizontal(start + width, session_close))
        .otherwise(pl.min_horizontal(start + width, pl.col("next_open"))),
    )


def _require_their_sessions(joined: pl.DataFrame) -> None:
    orphans = joined.filter(pl.col("session_open").is_null())
    if not orphans.is_empty():
        raise ValueError(
            f"Expected a session on the trade date of every bar, got none on "
            f"{orphans.item(0, 'trade_date')} for {orphans.height} of them."
        )
    early = joined.filter(pl.col("ts_open") < pl.col("session_open"))
    if early.is_empty():
        return
    ts_open, trade_date, session_open = early.select("ts_open", "trade_date", "session_open").row(0)
    raise ValueError(
        f"Expected bars opening at or after the open of their session, got one at "
        f"{utc_text(ts_open)} dated {trade_date}, whose session opens at {utc_text(session_open)}."
    )


def _require_nested(bucketed: pl.DataFrame, timeframe: Timeframe) -> None:
    straddling = bucketed.filter(pl.col("ts_close") > pl.col("bucket_close"))
    if straddling.is_empty():
        return
    ts_open, ts_close = straddling.select("ts_open", "ts_close").row(0)
    raise ValueError(
        f"Expected bars nested in the buckets of {timeframe}, got {straddling.height} straddling "
        f"them, the first from {utc_text(ts_open)} to {utc_text(ts_close)}."
    )


def _where_every_bar_has(column: str, value: pl.Expr) -> pl.Expr:
    return pl.when(pl.col(column).is_not_null().all()).then(value)


def _volume_weighted_vwap() -> pl.Expr:
    """The vwap of a bucket from its bars' vwaps weighted by their volumes, exactly in 128-bit
    integers, rounded down."""
    volume = pl.col("volume").cast(pl.Int128)
    notional = (pl.col("vwap").cast(pl.Int128) * volume).sum()
    return (notional // volume.sum()).cast(pl.Int64)


def _session_buckets(sessions: pl.DataFrame, timeframe: Timeframe) -> pl.DataFrame:
    """Every bucket of `timeframe` of each session: its trade date, `ts_open`, and `ts_close`,
    the last one cut at the close."""
    if timeframe.unit is TimeUnit.DAY:
        return sessions.select("trade_date", ts_open="open", ts_close="close")
    width = timeframe.nominal_nanoseconds()
    return (
        sessions.select("trade_date", "close", ts_open=pl.int_ranges("open", "close", width))
        .explode("ts_open")
        .select(
            "trade_date",
            "ts_open",
            ts_close=pl.min_horizontal(pl.col("ts_open") + width, pl.col("close")),
        )
    )


def _outside_halts(buckets: pl.DataFrame, sessions: pl.DataFrame) -> pl.DataFrame:
    """The buckets but those lying wholly inside a halt: within a session the halts do not
    overlap, so only the last halt starting at or before a bucket can hold it."""
    halts = sessions.select("halts").explode("halts").unnest("halts").drop_nulls().sort("start")
    if halts.is_empty():
        return buckets
    inside = pl.col("ts_close") <= pl.col("end")
    return (
        buckets.sort("ts_open")
        .join_asof(halts, left_on="ts_open", right_on="start", strategy="backward")
        .filter(~inside.fill_null(False))
        .drop("start", "end")
    )


def _require_bars_of_the_timeframe(
    bars: pl.DataFrame, timeframe: Timeframe, sessions: SessionTable
) -> None:
    """Refuse a bar that is not a bucket of `timeframe` in its session, as bars of another
    timeframe are, wherever it lies."""
    if bars.is_empty():
        return
    bucketed = in_buckets(bars, timeframe, sessions)
    misfits = bucketed.filter(
        (pl.col("ts_open") != pl.col("bucket_open"))
        | (pl.col("ts_close") != pl.col("bucket_close"))
    )
    if misfits.is_empty():
        return
    ts_open, ts_close = misfits.select("ts_open", "ts_close").row(0)
    raise ValueError(
        f"Expected bars of {timeframe} in the buckets of their sessions, got one from "
        f"{utc_text(ts_open)} to {utc_text(ts_close)}."
    )


def _require_one_bar_a_bucket(grid: pl.DataFrame, rows: int) -> None:
    """Refuse a bar given twice, or dated otherwise than the session of its bucket."""
    if grid.height != rows:
        twice = grid.filter(pl.struct("instrument_id", "ts_open").is_duplicated())
        instrument_id, ts_open = twice.select("instrument_id", "ts_open").row(0)
        raise ValueError(
            f"Expected one bar for each instrument and ts_open, got {grid.height - rows} more, "
            f"the first of instrument_id {instrument_id} opening {utc_text(ts_open)}."
        )
    elsewhere = grid.filter(
        pl.col("bar_close").is_not_null() & (pl.col("bar_trade_date") != pl.col("trade_date"))
    )
    if elsewhere.is_empty():
        return
    ts_open, bar_trade_date, trade_date = elsewhere.select(
        "ts_open", "bar_trade_date", "trade_date"
    ).row(0)
    raise ValueError(
        f"Expected each bar dated by the session of its bucket, got the bar opening "
        f"{utc_text(ts_open)} dated {bar_trade_date} in the session of {trade_date}."
    )


def _with_empty_buckets_filled(grid: pl.DataFrame) -> pl.DataFrame:
    empty = pl.col("bar_close").is_null()
    previous_close = pl.col("close").fill_null(strategy="forward").over("instrument_id")
    prices = {
        price: pl.when(empty).then(previous_close).otherwise(pl.col(price))
        for price in ("open", "high", "low", "close")
    }
    return grid.with_columns(
        **prices,
        volume=pl.col("volume").fill_null(pl.lit(0, dtype=pl.UInt64)),
        trade_count=pl.when(empty)
        .then(pl.lit(0, dtype=pl.UInt32))
        .otherwise(pl.col("trade_count")),
        zero_volume=empty,
    ).select(GRID_COLUMNS.names())
