"""What `load` builds a symbol's signal bars from (`fefat.market.api`, steps 1.8 to 3.3), split
from the data API at step 5.1: a `SeriesSource`, built once, gives the bars of many windows, as
the feature cache reads a window's partitions (step 3.3). `series_source_in` builds one for the
store and cache folder its caller names, as the app's services, which hold the store the
container built (D-27); `series_source` for the store in `FEFAT_DATA_DIR` and the session tables
cached in `FEFAT_HOME`, as a notebook's `load`.

    source = series_source_in(Store(paths.data_dir), paths.cache_dir, "ES")
    source.signal_bars(Timeframe.parse("5m"), (date(2026, 3, 6), date(2026, 3, 6)))
"""

import os
import warnings
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from fefat.config import resolve_paths
from fefat.market.aggressor import PRINT_COLUMNS, SIDE_VOLUME_COLUMNS, side_volumes
from fefat.market.calendar import SessionTable
from fefat.market.continuous import CONTINUOUS_COLUMNS, RollCalendar
from fefat.market.contracts import parse_contract_name
from fefat.market.coverage import dataset_coverage
from fefat.market.dataset_choice import (
    building_datasets,
    dataset_warnings,
    provider_datasets,
    series_of,
)
from fefat.market.fidelity import TickFidelity
from fefat.market.instruments import Instrument, InstrumentKind, InstrumentTable
from fefat.market.layout import Dataset, DatasetOrigin, SeriesKind
from fefat.market.roll_calendars import kept_roll_calendar
from fefat.market.saved_instruments import instrument_table
from fefat.market.schema import Timeframe
from fefat.market.signal_grid import SourceSpan, front_contracts, gridded_bars, source_spans
from fefat.market.store import ListedStore, Store

SIGNAL_BAR_COLUMNS = pl.Schema({**CONTINUOUS_COLUMNS, "zero_volume": pl.Boolean})
"""The columns `load` returns, whatever the mode: a bar's, its contract, its raw close, the
offset of its prices, whether it is a new front's first, and whether its bucket is empty."""


class UnknownSymbolError(ValueError):
    """A symbol that names no root of the instrument table and no contract of one."""

    def __init__(self, symbol: str, roots: tuple[str, ...]) -> None:
        super().__init__(
            f"Expected a root ({', '.join(roots)}) or a contract such as MESH2024, got {symbol!r}."
        )


@dataclass(frozen=True)
class SeriesSource:
    """What `load` builds a symbol's signal bars from (module docstring): the store, the root's
    instrument and session table, one provider's datasets of it by schema and their series kind,
    the contract the symbol names, where it names one, and the roll calendar a spliced series
    follows, None for a series that is not spliced."""

    store: Store
    instrument: Instrument
    sessions: SessionTable
    datasets: dict[str, Dataset]
    series: SeriesKind
    contract: str | None
    calendar: RollCalendar | None

    @property
    def provider(self) -> str:
        """The provider whose datasets the bars come from."""
        return next(iter(self.datasets.values())).provider

    @property
    def symbol(self) -> str:
        """The contract named, else the root."""
        return self.instrument.root if self.contract is None else self.contract

    def counted(self, dates: tuple[date, date]) -> pl.DataFrame | None:
        """The contract whose data chooses each trade date's level (`signal_bar_eras`): the front
        a spliced series keeps, or the one contract named; every contract's for a series of a
        product that does not expire, or of every contract."""
        if self.calendar is not None:
            return front_contracts(self.calendar)
        if self.contract is not None:
            rows = self.sessions.between(*dates)
            return rows.select("trade_date", contract=pl.lit(self.contract))
        return None

    def dates_read(self, dates: tuple[date, date]) -> tuple[date, date]:
        """The trade dates `signal_bars` reads for the window `dates`, from the session before its
        first, which the feature cache's keys pin (`fefat.features.cache_keys`)."""
        # shortcut: one session of lead-in, so a contract without trades in it starts its grid on
        # the window's first date at its first bar; read back to each contract's last bar when a
        # strategy needs it.
        return self.sessions.preceding(dates[0]).trade_date, dates[1]

    def signal_bars(
        self,
        timeframe: Timeframe,
        dates: tuple[date, date],
        wanted: TickFidelity | Timeframe | None = None,
    ) -> pl.DataFrame:
        """`load`'s bars of `timeframe` on the trade dates `dates` spans, each date's from the
        level `wanted`, or else from the finest that holds it, read from the session before the
        first: none where the store holds none, which `load` refuses."""
        first, last = dates
        dates_read = self.dates_read(dates)
        counted = self.counted(dates_read)
        spans = source_spans(
            self.store, self.datasets, timeframe, dates_read, wanted=wanted, contracts=counted
        )
        _warn_of(spans, self.series)
        building = (
            building_datasets(self.datasets, timeframe)
            if wanted is None
            else [span.dataset for span in spans]
        )
        gridded = gridded_bars(
            self.store,
            spans,
            timeframe,
            self.sessions,
            dates_read,
            self.contract,
            self.calendar,
            building,
        )
        if self.calendar is None:
            unspliced = _unspliced(gridded, self.series)
            return _signal_bars(unspliced, first, last, ("contract", "ts_open"))
        return _signal_bars(self.calendar.continuous_bars(gridded), first, last, ("ts_open",))

    def side_volumes(self, timeframe: Timeframe, dates: tuple[date, date]) -> pl.DataFrame:
        """The volume of the prints of each bucket of `timeframe` by aggressor side on the trade
        dates `dates` spans that the provider's trades hold, each date's of the contract whose
        bars it gives (`counted`), held back before the bucket of the trades' first print and
        from their end, with the columns of `SIDE_VOLUME_COLUMNS` (`fefat.market.aggressor`):
        none without trades."""
        trades = self.datasets.get("trades")
        coverage = None if trades is None else dataset_coverage(self.store, trades)
        if trades is None or coverage is None:
            return pl.DataFrame(schema=SIDE_VOLUME_COLUMNS)
        first, last = dates
        counted = self.counted(dates)
        fronts = None if counted is None else set(counted.select("trade_date", "contract").rows())
        read = [
            file.partition
            for file in self.store.list_partitions(trades)
            if isinstance(file.partition.key, date)
            and first <= file.partition.key <= last
            and (fronts is None or (file.partition.key, file.partition.contract) in fronts)
        ]
        if not read:
            return pl.DataFrame(schema=SIDE_VOLUME_COLUMNS)
        prints = pl.concat(self.store.scan_partition(each).select(PRINT_COLUMNS) for each in read)
        until = min(self.sessions.following(last).open, coverage.received_until)
        held = sorted({each.key for each in read if isinstance(each.key, date)})
        in_hand = (coverage.received_from, until)
        return side_volumes(prints.collect(), timeframe, self.sessions, held, in_hand)


def series_source(
    root_or_symbol: str,
    continuous: bool | None = None,
    provider: str | None = None,
    origin: str | None = None,
) -> SeriesSource:
    """What `load` reads the bars of `root_or_symbol` from, `continuous`, `provider`, and
    `origin` taken as `load` takes them, in the store `FEFAT_DATA_DIR` names with the session
    tables cached in `FEFAT_HOME` (`series_source_in`)."""
    paths = resolve_paths(os.environ)
    return series_source_in(
        Store(paths.data_dir), paths.cache_dir, root_or_symbol, continuous, provider, origin
    )


def series_source_in(
    store: Store,
    cache_folder: Path,
    root_or_symbol: str,
    continuous: bool | None = None,
    provider: str | None = None,
    origin: str | None = None,
) -> SeriesSource:
    """What `load` reads the bars of `root_or_symbol` from in `store`, the session tables cached
    in `cache_folder`: built once, it gives the bars of many windows
    (`SeriesSource.signal_bars`), each dataset listed once, as the store held it then
    (`ListedStore`); a symbol that names no root and no contract of one is refused with
    `UnknownSymbolError`."""
    listed = ListedStore(store.folder)
    table = instrument_table(listed.folder)
    root, contract = _root_and_contract(root_or_symbol, table)
    instrument = table.get(root)
    sessions = table.sessions_of(root, cache_folder)
    datasets = provider_datasets(listed, root, provider, parse_origin(origin))
    series = series_of(listed, datasets)
    splices = _splices(instrument, contract, continuous, series)
    calendar = kept_roll_calendar(listed, datasets, instrument, sessions) if splices else None
    return SeriesSource(
        store=listed,
        instrument=instrument,
        sessions=sessions,
        datasets=datasets,
        series=series,
        contract=contract,
        calendar=calendar,
    )


def parse_origin(origin: str | None) -> DatasetOrigin | None:
    """`origin`, as `load` and `roll_calendar` take it, as the type: `import`, or `sync` once
    connectors exist; None narrows nothing."""
    if origin is None:
        return None
    try:
        return DatasetOrigin(origin)
    except ValueError as error:
        named = ", ".join(choice.value for choice in DatasetOrigin)
        raise ValueError(f"Expected an origin of {named}, got {origin!r}.") from error


def _root_and_contract(symbol: str, table: InstrumentTable) -> tuple[str, str | None]:
    """The root a symbol names, and the contract when it names one (`MESH2024`)."""
    roots = table.roots()
    if symbol in roots:
        return symbol, None
    try:
        root, _ = parse_contract_name(symbol)
    except ValueError as error:
        raise UnknownSymbolError(symbol, roots) from error
    if root not in roots:
        raise UnknownSymbolError(symbol, roots)
    return root, symbol


def _splices(
    instrument: Instrument, contract: str | None, continuous: bool | None, series: SeriesKind
) -> bool:
    """Whether the load splices the root's contracts: by default for a futures root, and
    never for a contract, a product that does not expire, or a continuous series."""
    splices_by_default = (
        contract is None
        and instrument.kind is InstrumentKind.FUTURES
        and series is SeriesKind.CONTRACT
    )
    if continuous is None:
        return splices_by_default
    if continuous and not splices_by_default:
        named = f"the {instrument.kind} {instrument.root}"
        if series is not SeriesKind.CONTRACT:
            named = f"the {series} series of {instrument.root}"
        if contract:
            named = f"the contract {contract}"
        raise ValueError(
            f"Expected continuous=False or no continuous for {named}, which no roll calendar "
            "splices, got True."
        )
    return continuous


def _warn_of(spans: list[SourceSpan], series: SeriesKind) -> None:
    """Warn, on every load, of what `dataset_warnings` names of each dataset the bars come from:
    bars coarser than a minute as the finest data, and a continuous series."""
    for source in dict.fromkeys(span.dataset for span in spans):
        for warning in dataset_warnings(source, series):
            warnings.warn(warning, UserWarning, stacklevel=4)


def _unspliced(gridded: pl.DataFrame, series: SeriesKind) -> pl.DataFrame:
    """Each contract's own bars; a back-adjusted series has neither a raw close nor an offset,
    since its prices hold the gaps of rolls after them (D-49)."""
    adjusted = series is SeriesKind.CONTINUOUS_BACK_ADJUSTED
    return gridded.with_columns(
        close_raw=pl.lit(None, dtype=pl.Int64) if adjusted else pl.col("close"),
        adj_offset=pl.lit(None if adjusted else 0, dtype=pl.Int64),
        roll_flag=pl.lit(False),
    )


def _signal_bars(
    bars: pl.DataFrame, first: date, last: date, order: tuple[str, ...]
) -> pl.DataFrame:
    """The bars of the trade dates from `first` to `last`, with the columns of
    `SIGNAL_BAR_COLUMNS`, sorted by `order`."""
    return (
        bars.filter(pl.col("trade_date").is_between(first, last))
        .with_columns(zero_volume=pl.col("volume") == 0)
        .select(SIGNAL_BAR_COLUMNS.names())
        .sort(*order)
    )
