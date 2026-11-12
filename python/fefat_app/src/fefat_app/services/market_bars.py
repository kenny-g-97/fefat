"""The bars of a window over the API, a page at a time (step 5.1, `01-architecture.md` section 7,
D-93): each page is `load`'s bars of its own trade dates (`fefat.market.series_source`), at most
`BARS_PER_PAGE` of them, column by column, with its opens in whole seconds and its prices in the
instrument's units, so that no number passes the 2^53 that JavaScript's numbers hold exactly (the
phase's header); `next_from` is the instant the next page opens at, which the caller sends back
as the window's start, none on the last page.

A window is cut to the trade dates held by the datasets that build its timeframe, a named
contract's own first and last (step 5.4), before anything is read, which `bars_span` gives the
chart before it asks for a window, for a spliced series within the sessions its roll calendar
decides; and a page's trade dates are counted ahead
from the session table, each session's buckets of the timeframe, so that a request reads the
sessions of one page, not of its window, and from step 5.4 at most `FINE_SESSIONS_PER_PAGE`
sessions of prints or of bars finer than a minute and at most `SESSIONS_PER_PAGE` sessions, so
that a page of coarse bars never reads its window's every print. A page that ends at a session
hands over to the next session's open. The pages of a spliced series, of a contract, or of a
product that does not expire join to one `load` of the window, but that `load` reads one session
of lead-in (`SeriesSource.dates_read`): a page that starts after a session without bars of a
contract lacks the zero-volume rows that would lead to its first bar, and with `continuous`
false, a contract that stopped trading before a page's first session has no rows on it."""

from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import Path
from typing import NamedTuple

import polars as pl
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from fefat.market.calendar import SessionTable, utc_text
from fefat.market.continuous import RollCalendar
from fefat.market.coverage import dataset_coverage
from fefat.market.dataset_choice import building_datasets
from fefat.market.engine_units import price_in_units
from fefat.market.layout import DatasetOrigin, SeriesKind
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
FINE_SESSIONS_PER_PAGE = 20
"""The most sessions of prints, or of bars finer than a minute, a page reads (step 5.4)."""
SESSIONS_PER_PAGE = 260
"""The most sessions a page reads, about a year of a futures product's (step 5.4)."""
WINDOW_START = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}(T[0-9]{2}:[0-9]{2}:[0-9]{2}Z)?$"
"""A window's start: a trade date, such as 2026-03-06, or the instant a page opens at in UTC,
such as 2026-03-06T03:20:00Z, as a page's `next_from` gives it."""
_NANOSECONDS_PER_SECOND = 1_000_000_000


class SeriesRequest(BaseModel):
    """A series of bars: the instrument, a root such as `ES` or a contract such as `ESH2026`;
    the timeframe, such as `5m`; and, as `load` takes them, whether a futures root's contracts
    are spliced, which they are by default, the provider whose datasets the bars come from, the
    catalog's recommended source among those that hold the root by default, and the origin of
    its datasets, any by default."""

    model_config = ConfigDict(frozen=True)

    instrument: str
    timeframe: str
    continuous: bool | None = None
    provider: str | None = None
    origin: DatasetOrigin | None = None


class BarPrices(StrEnum):
    """The prices a page's bars carry (step 5.4): adjusted, a spliced series' prices plus the
    offset its rolls added, which every feature reads (`fefat.market.continuous`), or raw, the
    prices each bar's contract traded at; the two are one for a series that is not spliced."""

    ADJUSTED = "adjusted"
    RAW = "raw"


class BarsRequest(SeriesRequest):
    """A page of a series' window: the trade date the window starts on, or the instant the page
    opens at (`WINDOW_START`), the trade date the window ends on, and the prices its bars
    carry."""

    start: str = Field(pattern=WINDOW_START)
    end: date
    prices: BarPrices = BarPrices.ADJUSTED


class HeldDates(BaseModel):
    """The first and the last trade date a series' data holds."""

    model_config = ConfigDict(frozen=True)

    first: date
    last: date


class BarsSpan(BaseModel):
    """What a series' data holds (step 5.4): the instrument and the timeframe asked for, the
    provider whose datasets the bars come from, and the trade dates its data that builds the
    timeframe holds, a named contract's own, none while it holds none; the chart asks for its
    windows within them."""

    model_config = ConfigDict(frozen=True)

    instrument: str
    timeframe: str
    provider: str
    held: HeldDates | None


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
    datasets the bars come from, the bars, the instant the next page opens at, which the caller
    sends as the window's start, none on the last page, and what `load` warns of the datasets
    the page's bars come from, as a notebook shows it (step 5.4)."""

    model_config = ConfigDict(frozen=True)

    instrument: str
    timeframe: str
    provider: str
    bars: BarColumns
    next_from: AwareDatetime | None
    warnings: tuple[str, ...]


class NoSuchInstrumentError(ValueError):
    """An instrument that names no root and no contract of one (`UnknownSymbolError`)."""


class BarsRefusedError(ValueError):
    """A window whose bars the SDK refuses, such as one a provider named does not hold or a
    timeframe finer than the data, with the SDK's reason."""


class _Page(NamedTuple):
    """A page's rows, with the columns of `SIGNAL_BAR_COLUMNS`, the instant the next page opens
    at, in nanoseconds since the Unix epoch, none on the last page, and what `load` warns of
    them."""

    rows: pl.DataFrame
    next_open: int | None
    warnings: tuple[str, ...]


def bars_span(store: Store, cache_folder: Path, request: SeriesRequest) -> BarsSpan:
    """What the series `request` names holds in `store`, the session tables cached in
    `cache_folder`; refused as `bars_page` refuses."""
    with _refusals():
        source = _source(store, cache_folder, request)
        held = _decided(_held_dates(source, Timeframe.parse(request.timeframe)), source.calendar)
    return BarsSpan(
        instrument=request.instrument,
        timeframe=request.timeframe,
        provider=source.provider,
        held=None if held is None else HeldDates(first=held[0], last=held[1]),
    )


def bars_page(store: Store, cache_folder: Path, request: BarsRequest) -> BarsPage:
    """The page of bars `request` asks for, read from `store`, the session tables cached in
    `cache_folder` (module docstring); `NoSuchInstrumentError` for an instrument that names no
    root and no contract of one, and `BarsRefusedError` for a window the SDK refuses."""
    with _refusals():
        source = _source(store, cache_folder, request)
        _require_prices(source, request.prices)
        page = _page(source, Timeframe.parse(request.timeframe), request)
    rows = page.rows if request.prices is BarPrices.ADJUSTED else _traded(page.rows)
    next_from = None if page.next_open is None else _instant(page.next_open)
    return BarsPage(
        instrument=request.instrument,
        timeframe=request.timeframe,
        provider=source.provider,
        bars=_columns(rows),
        next_from=next_from,
        warnings=page.warnings,
    )


@contextmanager
def _refusals() -> Generator[None]:
    """The SDK's refusals as the service's: `NoSuchInstrumentError` for a symbol that names no
    root and no contract of one, and `BarsRefusedError` for any other."""
    try:
        yield
    except UnknownSymbolError as unknown:
        raise NoSuchInstrumentError(str(unknown)) from unknown
    except ValueError as refused:
        raise BarsRefusedError(str(refused)) from refused


def _require_prices(source: SeriesSource, prices: BarPrices) -> None:
    """Refuse raw prices of a back-adjusted import, whose prices hold the gaps of later rolls and
    which keeps no raw ones (D-49)."""
    if prices is BarPrices.RAW and source.series is SeriesKind.CONTINUOUS_BACK_ADJUSTED:
        raise ValueError(
            f"Expected adjusted prices of the back-adjusted series of {source.symbol}, which keeps "
            "no raw prices, got raw."
        )


def _traded(rows: pl.DataFrame) -> pl.DataFrame:
    """`rows` at the prices each bar's contract traded at: less the offset a spliced series'
    rolls added, 0 for any other series (`fefat.market.continuous`)."""
    return rows.with_columns(pl.col("open", "high", "low", "close") - pl.col("adj_offset"))


def _source(store: Store, cache_folder: Path, request: SeriesRequest) -> SeriesSource:
    """What `load` builds the series `request` names from."""
    return series_source_in(
        store,
        cache_folder,
        request.instrument,
        request.continuous,
        request.provider,
        request.origin,
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
        return _Page(pl.DataFrame(schema=SIGNAL_BAR_COLUMNS), None, ())
    first, last = max(first, held[0]), min(request.end, held[1])
    through = _page_end(source.sessions, timeframe, (first, last), _fine_dates(source, timeframe))
    rows, warned = source.warned_signal_bars(timeframe, (first, through))
    if opens_from is not None:
        rows = rows.filter(pl.col("ts_open") >= opens_from)
    rows = rows.sort("ts_open", "contract")
    if rows.height > BARS_PER_PAGE:
        next_open: int = rows.item(BARS_PER_PAGE, "ts_open")
        return _Page(rows.filter(pl.col("ts_open") < next_open), next_open, warned)
    if through == last:
        return _Page(rows, None, warned)
    following = source.sessions.following(through)
    return _Page(rows, following.open if following.trade_date <= last else None, warned)


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
    """The first and the last trade date the source's datasets that build `timeframe` hold, the
    contract's own where the source names one, since `load` gives a contract no bars before its
    first and only empty ones after its last (step 5.4); none while they hold no partition of
    it."""
    building = building_datasets(source.datasets, timeframe)
    named = [
        found
        for each in building
        if (found := dataset_coverage(source.store, each, source.contract)) is not None
    ]
    if not named:
        return None
    return min(each.first_trade_date for each in named), max(each.last_trade_date for each in named)


def _decided(
    held: tuple[date, date] | None, calendar: RollCalendar | None
) -> tuple[date, date] | None:
    """`held` cut to the sessions `calendar` decides a front for, where the series splices
    contracts: `load` gives no bars before its first front and refuses those after its last
    (`fefat.market.signal_grid.require_fronts_through`); none where they do not meet (step 5.4's
    engine review)."""
    if held is None or calendar is None:
        return held
    fronts = calendar.rows
    if fronts.is_empty():
        return None
    first: date = max(held[0], fronts.item(0, "trade_date"))
    last: date = min(held[1], fronts.item(-1, "trade_date"))
    return None if last < first else (first, last)


def _fine_dates(source: SeriesSource, timeframe: Timeframe) -> set[date]:
    """The trade dates on which the datasets that build `timeframe` hold prints or bars finer
    than a minute, a named contract's own: a partition of each trade date
    (`fefat.market.layout`), which a page reads whole."""
    return {
        file.partition.key
        for dataset in building_datasets(source.datasets, timeframe)
        for file in source.store.list_partitions(dataset)
        if isinstance(file.partition.key, date)
        and source.contract in (None, file.partition.contract)
    }


def _page_end(
    sessions: SessionTable, timeframe: Timeframe, dates: tuple[date, date], fine: set[date]
) -> date:
    """The last trade date a page reads from the first of `dates`: the first whose sessions from
    there on hold more than `BARS_PER_PAGE` buckets of `timeframe`, the
    `FINE_SESSIONS_PER_PAGE`th of the `fine` dates, or the `SESSIONS_PER_PAGE`th session, or
    else the last of `dates`, so that a page reads a bounded part of its window (step 5.4)."""
    first, last = dates
    counted = sessions.between(first, last).with_columns(
        buckets=_buckets(timeframe).cum_sum(),
        fine=pl.col("trade_date").is_in(fine).cum_sum(),
        read=pl.int_range(1, pl.len() + 1),
    )
    beyond = counted.filter(
        (pl.col("buckets") > BARS_PER_PAGE)
        | (pl.col("fine") >= FINE_SESSIONS_PER_PAGE)
        | (pl.col("read") >= SESSIONS_PER_PAGE)
    )
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
