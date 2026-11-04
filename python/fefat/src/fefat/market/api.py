"""The SDK's data API (steps 1.8 and 1.9): `load` gives the signal bars of a product or a
contract in one call, `datasets` lists what the store holds, and `roll_calendar` gives the roll
calendar `load` splices a future with (step 2.9). `series_source` gives what `load` reads a
symbol's bars from, built once to give the bars of many windows, as the feature cache reads a
window's partitions (step 3.3); and a roll calendar is built once in a process for each state of
the data it reads, so that a notebook's loop of loads, a cache's partitions, and a backtest do
not build it again (D-71).

    import fefat as ff

    bars = ff.market.load("MES", "5m", "2024-01-01", "2024-03-31").collect()
    march = ff.market.load("MESH2024", "1m", "2024-03-01", "2024-03-15").collect()
    ticks = ff.market.load("ES", "1m", "2026-03-06", "2026-03-06", fidelity="trades")
    from_databento = ff.market.load("MES", "5m", "2024-01-01", "2024-03-31", provider="databento")
    ff.market.datasets()

Both read the store in `FEFAT_DATA_DIR` (`fefat.config.resolve_paths`), and the session tables
cached in `FEFAT_HOME`.

`load(root_or_symbol, timeframe, start, end, continuous=None, fidelity=None, provider=None,
origin=None)`
returns the bars of `timeframe` (`1s`, `5m`, `1h`, `1d`, ...) of the trade dates from `start`
to `end`, dates or text such as `2024-01-31`, as a Polars LazyFrame with the columns of
`SIGNAL_BAR_COLUMNS`:

- `ts_open`, `ts_close`: the bucket of the session, `[open + k·Δ, open + (k+1)·Δ)` anchored at
  the session's open, in nanoseconds since the Unix epoch, UTC; a bar may be used from its
  `ts_close` (`fefat.market.bars`);
- `trade_date`: the session's trade date (`fefat.market.calendar`);
- `instrument_id`: the vendor's id of the contract;
- `open`, `high`, `low`, `close`, `vwap`: prices in 1e-9 units, adjusted on a continuous
  series; `vwap` is null where the data has none, as on a vendor's bars;
- `volume`, `trade_count`: what traded in the bucket;
- `contract`: the contract the bar belongs to, such as `MESH2024`;
- `close_raw`: the contract's own close, which orders execute against, and null on a
  back-adjusted series an import holds, whose prices no order traded at (D-49);
- `adj_offset`: what was added to the raw prices, so that `close = close_raw + adj_offset`,
  null where `close_raw` is;
- `roll_flag`: true on the first bar of each new front contract at or after its roll's open;
- `zero_volume`: true on a bucket without trades, priced at the close before it.

The bars lie on the session grid: a row for every bucket of every session but those inside a
halt, from each contract's first bar in the range on, up to the end of the data, where the
buckets not yet complete are held back (D-43); a print in the break after a close is in no
row. A futures product (`MES`) is spliced by default into one forward-anchored series
(`fefat.market.continuous`, D-44): each session's front contract, chosen by volume from the
1-minute bars of the whole dataset, so that a window's fronts and prices never depend on
where it starts, with `adj_offset` 0 for the dataset's first contract and moved by each roll's
gap since; the window is read from the session before its start, so that a front that traded
there has the same first rows and roll flag as in a longer window. `continuous=False` gives every contract's own bars instead, each with
`adj_offset` 0, sorted by contract; a contract (`MESH2024`) and a perpetual or spot pair load
alone, and a continuous load of them is refused. A contract that stopped trading keeps its
rows to `end`, as zero-volume bars, since the grid adds no row because of a later one.

`fidelity` names the data the bars are built from (`fefat.market.fidelity`, as text or as the
type): `trades`, or bars of a timeframe such as `1s`, `1m`, or an import's `5m`; without it,
each trade date's from the finest level the store holds for it that builds the bars, of
the contract whose bars it gives that day (`fefat.market.dataset_choice.signal_bar_eras`,
step 3.2); `tbbo` is refused, since bars are not built from TBBO yet; a
timeframe finer than the data is refused, and bars coarser than a minute as the finest data are warned of on every
load, since backtests on them fill at that fidelity. `provider` names the provider whose
datasets the bars come from, such as `databento`, where several hold the root; without it the
catalog's recommended source among them is taken, and a root the catalog does not list that
several hold is refused (`fefat.market.dataset_choice`). `origin` (`import`, or `sync` once
connectors exist) narrows the datasets to those of that origin. A continuous series an import
stored as one synthetic contract (step 1.10) loads as it is, never spliced, and every load of it
warns that roll handling is off, and, back-adjusted, that its prices distort price levels
and its bars have no raw close. The
bars are built when `load` runs, and the frame is lazy so that a notebook adds its own columns
and filters before it collects.
"""

import os
import warnings
from dataclasses import dataclass
from datetime import date, datetime

import polars as pl

from fefat.config import resolve_paths
from fefat.market.aggressor import PRINT_COLUMNS, SIDE_VOLUME_COLUMNS, side_volumes
from fefat.market.calendar import SessionTable
from fefat.market.catalog import CATALOG
from fefat.market.continuous import CONTINUOUS_COLUMNS, RollCalendar
from fefat.market.contracts import parse_contract_name
from fefat.market.coverage import dataset_coverage
from fefat.market.dataset_choice import (
    building_datasets,
    dataset_warnings,
    provider_datasets,
    series_of,
)
from fefat.market.fidelity import TickFidelity, parse_fidelity
from fefat.market.instruments import Instrument, InstrumentKind, InstrumentTable
from fefat.market.layout import Dataset, DatasetOrigin, SeriesKind
from fefat.market.roll_calendars import kept_roll_calendar
from fefat.market.saved_instruments import instrument_table
from fefat.market.schema import Timeframe
from fefat.market.signal_grid import SourceSpan, front_contracts, gridded_bars, source_spans
from fefat.market.status import DATASET_COLUMNS, dataset_status
from fefat.market.store import ListedStore, Store

SIGNAL_BAR_COLUMNS = pl.Schema({**CONTINUOUS_COLUMNS, "zero_volume": pl.Boolean})
"""The columns `load` returns, whatever the mode: a bar's, its contract, its raw close, the
offset of its prices, whether it is a new front's first, and whether its bucket is empty."""
DATASETS_COLUMNS = pl.Schema({**DATASET_COLUMNS, "catalog_version": pl.UInt32})
"""The row per dataset of trades, TBBO, or bars that `datasets` gives: the columns of
`DATASET_COLUMNS` (`fefat.market.status`) and the version of the product catalog
(`fefat.market.catalog`)."""


def load(
    root_or_symbol: str,
    timeframe: str,
    start: str | date,
    end: str | date,
    continuous: bool | None = None,
    fidelity: str | TickFidelity | Timeframe | None = None,
    provider: str | None = None,
    origin: str | None = None,
) -> pl.LazyFrame:
    """The signal bars of `root_or_symbol` (a root such as `MES`, or a contract such as
    `MESH2024`) of `timeframe` on the trade dates from `start` to `end`, with the columns of
    `SIGNAL_BAR_COLUMNS`; the module docstring has the details and examples."""
    first, last = parse_trade_date(start, "start"), parse_trade_date(end, "end")
    if last < first:
        raise ValueError(f"Expected the start {first} on or before the end, got the end {last}.")
    bar_timeframe = Timeframe.parse(timeframe)
    wanted = None if fidelity is None else parse_fidelity(fidelity)
    source = series_source(root_or_symbol, continuous, provider, origin)
    bars = source.signal_bars(bar_timeframe, (first, last), wanted)
    return _some(bars, source.symbol, first, last).lazy()


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
        bars it gives (`counted`), held back from the end of the trades, with the columns of
        `SIDE_VOLUME_COLUMNS` (`fefat.market.aggressor`): none without trades."""
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
        return side_volumes(prints.collect(), timeframe, self.sessions, held, until)


def series_source(
    root_or_symbol: str,
    continuous: bool | None = None,
    provider: str | None = None,
    origin: str | None = None,
) -> SeriesSource:
    """What `load` reads the bars of `root_or_symbol` from, `continuous`, `provider`, and
    `origin` taken as `load` takes them: built once, it gives the bars of many windows
    (`SeriesSource.signal_bars`), as the feature cache reads a window's partitions
    (`fefat.features.cache`), each dataset listed once, as the store held it then
    (`ListedStore`)."""
    paths = resolve_paths(os.environ)
    store = ListedStore(paths.data_dir)
    table = instrument_table(paths.data_dir)
    root, contract = _root_and_contract(root_or_symbol, table)
    instrument = table.get(root)
    sessions = table.sessions_of(root, paths.cache_dir)
    datasets = provider_datasets(store, root, provider, _origin(origin))
    series = series_of(store, datasets)
    splices = _splices(instrument, contract, continuous, series)
    calendar = kept_roll_calendar(store, datasets, instrument, sessions) if splices else None
    return SeriesSource(
        store=store,
        instrument=instrument,
        sessions=sessions,
        datasets=datasets,
        series=series,
        contract=contract,
        calendar=calendar,
    )


def _some(bars: pl.DataFrame, named: str, first: date, last: date) -> pl.DataFrame:
    """`bars`, refused when empty: a window past the data, or on a dataset's first session,
    which never has a front, would otherwise read as a frame without an error."""
    if bars.is_empty():
        raise ValueError(f"Expected bars of {named} from {first} to {last} in the store, got none.")
    return bars


def roll_calendar(
    root: str, provider: str | None = None, origin: str | None = None
) -> RollCalendar:
    """The roll calendar `load` splices the futures product `root` with, from the datasets it
    would read (D-44): each session's front, and at each roll the contract rolled from, the gap,
    and the reason, which a backtest across the roll transfers its position by
    (`RollCalendar.rolls()`, step 2.9); `provider` and `origin` choose the datasets as `load`'s
    do."""
    paths = resolve_paths(os.environ)
    store = Store(paths.data_dir)
    table = instrument_table(paths.data_dir)
    instrument = table.get(root)
    sessions = table.sessions_of(root, paths.cache_dir)
    datasets = provider_datasets(store, root, provider, _origin(origin))
    return kept_roll_calendar(store, datasets, instrument, sessions)


def datasets() -> pl.DataFrame:
    """Every dataset of trades, TBBO, or bars the store holds, with the columns of
    `DATASETS_COLUMNS`, sorted by provider, root, and schema; an empty store gives no rows, and
    `ff.market.CATALOG.version` the catalog's version whatever the store holds."""
    paths = resolve_paths(os.environ)
    listed = dataset_status(Store(paths.data_dir), paths.reports_dir)
    return listed.with_columns(catalog_version=pl.lit(CATALOG.version, dtype=pl.UInt32))


def _root_and_contract(symbol: str, table: InstrumentTable) -> tuple[str, str | None]:
    """The root a symbol names, and the contract when it names one (`MESH2024`)."""
    roots = table.roots()
    if symbol in roots:
        return symbol, None
    try:
        root, _ = parse_contract_name(symbol)
    except ValueError as error:
        raise ValueError(
            f"Expected a root ({', '.join(roots)}) or a contract such as MESH2024, got {symbol!r}."
        ) from error
    table.get(root)
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


def parse_trade_date(value: str | date, name: str) -> date:
    """`value`, the `name` of a window such as its `start`, as a trade date: a date, or its ISO
    text; an instant is refused."""
    if isinstance(value, datetime):
        raise ValueError(
            f"Expected the {name} as a date such as 2024-01-31, got the instant {value!r}."
        )
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(
            f"Expected the {name} as a date such as 2024-01-31, got {value!r}."
        ) from error


def _origin(origin: str | None) -> DatasetOrigin | None:
    if origin is None:
        return None
    try:
        return DatasetOrigin(origin)
    except ValueError as error:
        named = ", ".join(choice.value for choice in DatasetOrigin)
        raise ValueError(f"Expected an origin of {named}, got {origin!r}.") from error


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
