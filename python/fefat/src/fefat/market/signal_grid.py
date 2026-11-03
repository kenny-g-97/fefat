"""The session grid `load` gives its bars on (`fefat.market.api`, steps 1.8 and 3.2): each trade
date's bars built from the dataset `source_spans` names for it, the fidelity asked for or else
the finest level that holds the date (D-71), on one grid from the session before the window
on, so that a date's rows, and its empty buckets priced at the close before them, are those any
window holding it gives; each dataset's dates up to the end of its data, where a bucket not yet
complete is held back (D-43); and, given a roll calendar, the rows of each session's front."""

from collections.abc import Sequence
from datetime import date
from typing import NamedTuple

import polars as pl

from fefat.market.bars import build_bars, resample_bars, session_grid
from fefat.market.calendar import SessionTable
from fefat.market.continuous import RollCalendar
from fefat.market.continuous_check import contracts_by_instrument
from fefat.market.coverage import dataset_coverage
from fefat.market.dataset_choice import signal_bar_eras, source_dataset
from fefat.market.fidelity import TickFidelity
from fefat.market.layout import Dataset, PartitionRequest
from fefat.market.roll_decisions import CONTRACT_BAR_COLUMNS
from fefat.market.schema import SchemaKind, Timeframe
from fefat.market.store import Store


class SourceSpan(NamedTuple):
    """A dataset and the trade dates, from `first` to `last`, whose bars it builds."""

    dataset: Dataset
    first: date
    last: date


def source_spans(
    store: Store,
    datasets: dict[str, Dataset],
    timeframe: Timeframe,
    dates: tuple[date, date],
    *,
    wanted: TickFidelity | Timeframe | None,
    contracts: pl.DataFrame | None,
) -> list[SourceSpan]:
    """The datasets the bars of `timeframe` of the trade dates `dates` span are built from:
    every date's from the fidelity `wanted`, or else each date's from the finest level that
    holds it for the contract `contracts` names that day, every contract where it is None
    (`signal_bar_eras`); none where no level holds a date of them."""
    if not datasets:
        raise ValueError("Expected trades or bars to build bars from, got none.")
    root = next(iter(datasets.values())).root
    if wanted is not None:
        return [SourceSpan(source_dataset(datasets, wanted, timeframe, root), *dates)]
    eras = signal_bar_eras(store, datasets, timeframe, dates, contracts)
    return [
        SourceSpan(source_dataset(datasets, era.fidelity, timeframe, root), era.first, era.last)
        for era in eras
    ]


def gridded_bars(
    store: Store,
    spans: Sequence[SourceSpan],
    timeframe: Timeframe,
    sessions: SessionTable,
    dates: tuple[date, date],
    contract: str | None,
    calendar: RollCalendar | None,
    building: Sequence[Dataset],
) -> pl.DataFrame:
    """The bars of `timeframe` on the session grid of the trade dates `dates` span, with the
    columns of `CONTRACT_BAR_COLUMNS`: each span's dates built from its dataset, up to the end of
    its data; given the roll `calendar`, the rows of each session's front only, which a spliced
    load keeps, instead of every contract's on every session; none without spans. The grid runs
    to the end of `dates` or of the data of `building`, the datasets that build the bars,
    whichever comes first, so that a date no level holds, even in a stretch between two
    datasets, has the rows any window holding it gives, whichever datasets it reaches (the
    leakage audit of step 3.3)."""
    if not spans:
        return pl.DataFrame(schema=CONTRACT_BAR_COLUMNS)
    first, last = dates
    data_ends = {span.dataset: _end_of_data(store, span.dataset) for span in spans}
    ends = [min(sessions.following(span.last).open, data_ends[span.dataset]) for span in spans]
    received_until = min(
        sessions.following(last).open, max(_end_of_data(store, each) for each in building)
    )
    windows = [_rows(store, span, contract) for span in spans]
    contracts = contracts_by_instrument(
        pl.concat(window.select("instrument_id", "contract") for window in windows)
    )
    bars = pl.concat(
        _bars_of(window.drop("contract"), span.dataset, timeframe, sessions, end)
        for window, span, end in zip(windows, spans, ends, strict=True)
    )
    fronts = None
    if calendar is not None:
        _require_fronts_for(bars, calendar)
        fronts = _fronts_with_their_lead_in(calendar, contracts)
    grid = session_grid(bars, timeframe, sessions, received_until, first, last, rows_for=fronts)
    within = grid.filter(~_past_their_data(spans, ends))
    return within.join(contracts, on="instrument_id").select(CONTRACT_BAR_COLUMNS.names())


def _past_their_data(spans: Sequence[SourceSpan], ends: Sequence[int]) -> pl.Expr:
    """Whether a row of a span's dates closes after the end of that span's data, a bucket held
    back (D-43) though a later span's data runs on."""
    return pl.any_horizontal(
        pl.col("trade_date").is_between(span.first, span.last) & (pl.col("ts_close") > end)
        for span, end in zip(spans, ends, strict=True)
    )


def _rows(store: Store, span: SourceSpan, contract: str | None) -> pl.DataFrame:
    """The span's records of its trade dates, each with its contract, of `contract` alone where
    it is named."""
    request = PartitionRequest(dataset=span.dataset, start=span.first, end=span.last)
    rows = store.scan_contracts(request)
    if contract is not None:
        rows = rows.filter(pl.col("contract") == contract)
    return rows.collect()


def _end_of_data(store: Store, dataset: Dataset) -> int:
    """The instant by which every record of the dataset is in hand, after which a bucket is held
    back (D-43, D-45); a dataset without partitions has none in hand."""
    coverage = dataset_coverage(store, dataset)
    return 0 if coverage is None else coverage.received_until


def _bars_of(
    rows: pl.DataFrame,
    source: Dataset,
    timeframe: Timeframe,
    sessions: SessionTable,
    received_until: int,
) -> pl.DataFrame:
    """The bars of `timeframe` from the rows of `source`: built from trades, resampled from
    finer bars, or the stored bars themselves."""
    if source.schema_name.kind is SchemaKind.TRADES:
        return build_bars(rows, timeframe, sessions, received_until)
    if str(source.schema_name) == f"ohlcv-{timeframe}":
        return rows
    return resample_bars(rows, timeframe, sessions, received_until)


def front_contracts(calendar: RollCalendar) -> pl.DataFrame:
    """The contract whose bars a spliced load gives on each trade date (`trade_date` and
    `contract`): the session's front, and on a first session without one, the contract that
    became the front after it, whose rows lead in to its first."""
    fronts, lead_in = _fronts_and_lead_in(calendar)
    return pl.concat([fronts, lead_in.join(fronts, on="trade_date", how="anti")])


def _fronts_with_their_lead_in(calendar: RollCalendar, contracts: pl.DataFrame) -> pl.DataFrame:
    """The sessions and instruments a spliced load grids: each session's front, and each front
    on the session before it took over, so that a new front's rows on its first day start at
    the open when it traded the session before, whatever day a window starts."""
    fronts, lead_in = _fronts_and_lead_in(calendar)
    return (
        pl.concat([fronts, lead_in])
        .unique()
        .join(contracts, on="contract")
        .select("trade_date", "instrument_id")
    )


def _fronts_and_lead_in(calendar: RollCalendar) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Each session's front (`trade_date` and `contract`), and each front on the session before
    it took over."""
    fronts = calendar.rows.select("trade_date", "contract")
    return fronts, fronts.with_columns(trade_date=pl.col("trade_date").shift(1)).drop_nulls()


def _require_fronts_for(bars: pl.DataFrame, calendar: RollCalendar) -> None:
    """Refuse bars of sessions after the roll calendar's last, whose fronts no 1-minute bars
    decided, as finer data that runs past the 1-minute bars gives: splicing would drop them."""
    decided = calendar.rows.get_column("trade_date")
    beyond = bars.get_column("trade_date")
    if not decided.is_empty():
        beyond = beyond.filter(beyond > decided.max())
    if beyond.is_empty():
        return
    through = "no session" if decided.is_empty() else f"{decided.max()}"
    raise ValueError(
        f"Expected 1-minute bars of {calendar.root} that decide the front contracts through "
        f"{beyond.max()}, got fronts through {through}."
    )
