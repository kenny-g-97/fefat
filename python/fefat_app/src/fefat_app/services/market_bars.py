"""The bars of a window over the API, a page at a time (step 5.1, `01-architecture.md` section 7,
D-93): each page is `load`'s bars of its own trade dates (`fefat.market.series_source`), at most
`BARS_PER_PAGE` of them, column by column, with its opens in whole seconds and its prices in the
instrument's units, so that no number passes the 2^53 that JavaScript's numbers hold exactly (the
phase's header); `next_from` is the instant the next page opens at, which the caller sends back
as the window's start, none on the last page.

A window is cut to the trade dates held by the datasets that build its timeframe, from a named
contract's own first one, before anything is read, and a page's trade dates are counted ahead
from the session table, each session's buckets of the timeframe, so that a request reads the
sessions of one page, not of its window, though the sessions of a page of coarse bars may hold
many prints (the `shortcut:` in `_page_end`). The pages of a spliced series, of a contract, or
of a product that does not expire join to one `load` of the window; with `continuous` false, a
contract that stopped trading before a page's first session has no rows on it, as `load` reads
one session of lead-in (`SeriesSource.dates_read`)."""

from datetime import UTC, date, datetime
from pathlib import Path
from typing import NamedTuple

import polars as pl
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from fefat.market.calendar import SessionTable, utc_text
from fefat.market.coverage import dataset_coverage
from fefat.market.dataset_choice import building_datasets
from fefat.market.engine_units import price_in_units
from fefat.market.layout import DatasetOrigin
from fefat.market.schema import Timeframe, TimeUnit
from fefat.market.series_source import (
    SIGNAL_BAR_COLUMNS,
    SeriesSource,
    UnknownSymbolError,
    series_source_in,
)
from fefat.market.store import Store

BARS_PER_PAGE = 20_000
"""The most bars a page holds (step 5.1)."""
WINDOW_START = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}(T[0-9]{2}:[0-9]{2}:[0-9]{2}Z)?$"
"""A window's start: a trade date, such as 2026-03-06, or the instant a page opens at in UTC,
such as 2026-03-06T03:20:00Z, as a page's `next_from` gives it."""
_NANOSECONDS_PER_SECOND = 1_000_000_000


class BarsRequest(BaseModel):
    """A page of a window's bars: the instrument, a root such as `ES` or a contract such as
    `ESH2026`; the timeframe, such as `5m`; the trade date the window starts on, or the instant
    the page opens at (`WINDOW_START`); the trade date the window ends on; and, as `load` takes
    them, whether a futures root's contracts are spliced, which they are by default, the provider
    whose datasets the bars come from, the catalog's recommended source among those that hold
    the root by default, and the origin of its datasets, any by default."""

    model_config = ConfigDict(frozen=True)

    instrument: str
    timeframe: str
    start: str = Field(pattern=WINDOW_START)
    end: date
    continuous: bool | None = None
    provider: str | None = None
    origin: DatasetOrigin | None = None


class BarColumns(BaseModel):
    """A page's bars, column by column, by their open, the bars of one open by their contract:
    each bar's open in whole seconds since the Unix epoch, UTC; its trade date; its prices in the
    instrument's units, adjusted on a spliced series; its volume, in lots of the dataset's size
    unit, a contract, or 0.001 BTC for bitcoin's perpetual; and its contract."""

    model_config = ConfigDict(frozen=True)

    time: tuple[int, ...]
    trade_date: tuple[date, ...]
    open: tuple[float, ...]
    high: tuple[float, ...]
    low: tuple[float, ...]
    close: tuple[float, ...]
    volume: tuple[int, ...]
    contract: tuple[str, ...]


class BarsPage(BaseModel):
    """A page of a window's bars: the instrument and the timeframe asked for, the provider whose
    datasets the bars come from, the bars, and the instant the next page opens at, which the
    caller sends as the window's start, none on the last page."""

    model_config = ConfigDict(frozen=True)

    instrument: str
    timeframe: str
    provider: str
    bars: BarColumns
    next_from: AwareDatetime | None


class NoSuchInstrumentError(ValueError):
    """An instrument that names no root and no contract of one (`UnknownSymbolError`)."""


class BarsRefusedError(ValueError):
    """A window whose bars the SDK refuses, such as one a provider named does not hold or a
    timeframe finer than the data, with the SDK's reason."""


class _Page(NamedTuple):
    """A page's rows, with the columns of `SIGNAL_BAR_COLUMNS`, and the instant the next page
    opens at, in nanoseconds since the Unix epoch, none on the last page."""

    rows: pl.DataFrame
    next_open: int | None


def bars_page(store: Store, cache_folder: Path, request: BarsRequest) -> BarsPage:
    """The page of bars `request` asks for, read from `store`, the session tables cached in
    `cache_folder` (module docstring); `NoSuchInstrumentError` for an instrument that names no
    root and no contract of one, and `BarsRefusedError` for a window the SDK refuses."""
    try:
        source = series_source_in(
            store,
            cache_folder,
            request.instrument,
            request.continuous,
            request.provider,
            request.origin,
        )
        page = _page(source, Timeframe.parse(request.timeframe), request)
    except UnknownSymbolError as unknown:
        raise NoSuchInstrumentError(str(unknown)) from unknown
    except ValueError as refused:
        raise BarsRefusedError(str(refused)) from refused
    next_from = None if page.next_open is None else _instant(page.next_open)
    return BarsPage(
        instrument=request.instrument,
        timeframe=request.timeframe,
        provider=source.provider,
        bars=_columns(page.rows),
        next_from=next_from,
    )


def _page(source: SeriesSource, timeframe: Timeframe, request: BarsRequest) -> _Page:
    """The rows of the page `request` asks for, and where the next one opens."""
    first, opens_from = _start(request.start, source.sessions)
    if request.end < first:
        raise ValueError(
            f"Expected the start {first} on or before the end, got the end {request.end}."
        )
    held = _held_dates(source, timeframe)
    if held is None or held[1] < first or request.end < held[0]:
        return _Page(pl.DataFrame(schema=SIGNAL_BAR_COLUMNS), None)
    first, last = max(first, held[0]), min(request.end, held[1])
    # shortcut: a page counts the bars it sends, not the data it reads: a page of 1d bars built
    # from trades reads every print of its window; cap a page's sessions by the finest dataset
    # that builds it when a store holds years of ticks (BACKLOG, step 5.4).
    through = _page_end(source.sessions, timeframe, first, last)
    rows = source.signal_bars(timeframe, (first, through))
    if opens_from is not None:
        rows = rows.filter(pl.col("ts_open") >= opens_from)
    rows = rows.sort("ts_open", "contract")
    if rows.height > BARS_PER_PAGE:
        next_open: int = rows.item(BARS_PER_PAGE, "ts_open")
        return _Page(rows.filter(pl.col("ts_open") < next_open), next_open)
    if through == last:
        return _Page(rows, None)
    following = source.sessions.following(through)
    return _Page(rows, following.open if following.trade_date <= last else None)


def _start(text: str, sessions: SessionTable) -> tuple[date, int | None]:
    """The trade date a window starts on, and the instant its page opens at, in nanoseconds
    since the Unix epoch, where `text` names one rather than a trade date (`WINDOW_START`)."""
    if "T" not in text:
        return date.fromisoformat(text), None
    instant = int(datetime.fromisoformat(text).timestamp()) * _NANOSECONDS_PER_SECOND
    opens, closes = sessions.span()
    if not opens <= instant < closes:
        raise ValueError(
            f"Expected an instant from {utc_text(opens)} to before {utc_text(closes)}, got {text}."
        )
    at = pl.DataFrame({"instant": [instant]}, schema={"instant": pl.Int64})
    trade_date: date = sessions.assign_trade_dates_or_previous(at, "instant").item(0, "trade_date")
    return trade_date, instant


def _held_dates(source: SeriesSource, timeframe: Timeframe) -> tuple[date, date] | None:
    """The first and the last trade date the source's datasets that build `timeframe` hold,
    the first of the contract's own partitions where the source names one, since `load` gives a
    contract no bars before its first; none while they hold no partition of it."""
    building = building_datasets(source.datasets, timeframe)
    held = [
        found for each in building if (found := dataset_coverage(source.store, each)) is not None
    ]
    named = held
    if source.contract is not None:
        named = [
            found
            for each in building
            if (found := dataset_coverage(source.store, each, source.contract)) is not None
        ]
    if not named:
        return None
    return min(each.first_trade_date for each in named), max(each.last_trade_date for each in held)


def _page_end(sessions: SessionTable, timeframe: Timeframe, first: date, last: date) -> date:
    """The last trade date a page reads from `first`: the first whose sessions from `first` on
    hold more than `BARS_PER_PAGE` buckets of `timeframe`, or `last`."""
    counted = sessions.between(first, last).with_columns(total=_buckets(timeframe).cum_sum())
    beyond = counted.filter(pl.col("total") > BARS_PER_PAGE)
    if beyond.is_empty():
        return last
    return beyond.item(0, "trade_date")


def _buckets(timeframe: Timeframe) -> pl.Expr:
    """The buckets of `timeframe` in each session of a session table's rows: a daily bar's one,
    or each `timeframe` from the open, the last cut at the close (`fefat.market.bars`)."""
    if timeframe.unit is TimeUnit.DAY:
        return pl.col("open").is_not_null().cast(pl.Int64)
    width = timeframe.nominal_nanoseconds()
    return (pl.col("close") - pl.col("open") + width - 1) // width


def _columns(rows: pl.DataFrame) -> BarColumns:
    """A page's rows as the API sends them (`BarColumns`)."""
    sent = rows.select(
        time=pl.col("ts_open") // _NANOSECONDS_PER_SECOND,
        trade_date=pl.col("trade_date"),
        open=price_in_units("open"),
        high=price_in_units("high"),
        low=price_in_units("low"),
        close=price_in_units("close"),
        volume=pl.col("volume"),
        contract=pl.col("contract"),
    )
    return BarColumns.model_validate(sent.to_dict(as_series=False))


def _instant(nanoseconds: int) -> datetime:
    """An instant in nanoseconds since the Unix epoch, a bar's open, which falls on a whole
    second, as an aware instant in UTC."""
    return datetime.fromtimestamp(nanoseconds // _NANOSECONDS_PER_SECOND, UTC)
