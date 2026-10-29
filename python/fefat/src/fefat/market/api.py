"""The SDK's data API (steps 1.8 and 1.9): `load` gives the signal bars of a product or a
contract in one call, `datasets` lists what the store holds, and `roll_calendar` gives the roll
calendar `load` splices a future with (step 2.9).

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
the finest the store holds; `tbbo` is refused, since bars are not built from TBBO yet; a
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
from datetime import date, datetime

import polars as pl

from fefat.config import resolve_paths
from fefat.market.bars import build_bars, resample_bars, session_grid
from fefat.market.calendar import SessionTable
from fefat.market.catalog import CATALOG, RollRule
from fefat.market.continuous import CONTINUOUS_COLUMNS, RollCalendar, volume_rolls
from fefat.market.continuous_check import contracts_by_instrument
from fefat.market.contracts import parse_contract_name
from fefat.market.coverage import dataset_coverage
from fefat.market.dataset_choice import (
    dataset_warnings,
    provider_datasets,
    roll_dataset,
    series_of,
    source_dataset,
)
from fefat.market.fidelity import TickFidelity, parse_fidelity
from fefat.market.instruments import Instrument, InstrumentKind, InstrumentTable
from fefat.market.layout import Dataset, DatasetOrigin, PartitionRequest, SeriesKind
from fefat.market.roll_decisions import CONTRACT_BAR_COLUMNS
from fefat.market.saved_instruments import instrument_table
from fefat.market.schema import (
    SchemaKind,
    Timeframe,
)
from fefat.market.status import DATASET_COLUMNS, dataset_status
from fefat.market.store import Store

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
    paths = resolve_paths(os.environ)
    store = Store(paths.data_dir)
    table = instrument_table(paths.data_dir)
    root, contract = _root_and_contract(root_or_symbol, table)
    instrument = table.get(root)
    first, last = _trade_date(start, "start"), _trade_date(end, "end")
    if last < first:
        raise ValueError(f"Expected the start {first} on or before the end, got the end {last}.")
    bar_timeframe = Timeframe.parse(timeframe)
    sessions = table.sessions_of(root, paths.cache_dir)
    datasets = provider_datasets(store, root, provider, _origin(origin))
    series = series_of(store, datasets)
    splices = _splices(instrument, contract, continuous, series)
    wanted = None if fidelity is None else parse_fidelity(fidelity)
    source = source_dataset(datasets, wanted, bar_timeframe, root)
    _warn_of(source, series)
    if not splices:
        gridded = _gridded(store, source, bar_timeframe, sessions, first, last, contract)
        bars = _signal_bars(_unspliced(gridded, series), first, last, ("contract", "ts_open"))
        return _some(bars, contract or root, first, last).lazy()
    calendar = _roll_calendar(store, datasets, instrument, sessions)
    gridded = _gridded(store, source, bar_timeframe, sessions, first, last, contract, calendar)
    bars = _signal_bars(calendar.continuous_bars(gridded), first, last, ("ts_open",))
    return _some(bars, root, first, last).lazy()


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
    return _roll_calendar(store, datasets, instrument, sessions)


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


def _trade_date(value: str | date, name: str) -> date:
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


def _warn_of(source: Dataset, series: SeriesKind) -> None:
    """Warn, on every load, of what `dataset_warnings` names: bars coarser than a minute as the
    finest data, and a continuous series."""
    for warning in dataset_warnings(source, series):
        warnings.warn(warning, UserWarning, stacklevel=3)


def _gridded(
    store: Store,
    source: Dataset,
    timeframe: Timeframe,
    sessions: SessionTable,
    first: date,
    last: date,
    contract: str | None,
    calendar: RollCalendar | None = None,
) -> pl.DataFrame:
    """The bars of `timeframe` built from `source` on the session grid, with the columns of
    `CONTRACT_BAR_COLUMNS`, from the session before `first`, so that a contract that traded in
    it has the same rows on `first` whatever day a window starts, up to `last` and the end of
    the data; given the roll `calendar`, the rows of each session's front only, which a
    spliced load keeps, instead of every contract's on every session."""
    # shortcut: one session of lead-in, so a contract without trades in it starts its grid on
    # `first` at its first bar; read back to each contract's last bar when a strategy needs it.
    lead_in = sessions.preceding(first).trade_date
    rows = store.scan_contracts(PartitionRequest(dataset=source, start=lead_in, end=last))
    if contract is not None:
        rows = rows.filter(pl.col("contract") == contract)
    window = rows.collect()
    contracts = contracts_by_instrument(window)
    coverage = dataset_coverage(store, source)
    if coverage is None:
        raise ValueError(f"Expected partitions of {source.relative_folder()}, got none.")
    received_until = min(sessions.following(last).open, coverage.received_until)
    bars = _bars_of(window.drop("contract"), source, timeframe, sessions, received_until)
    fronts = None
    if calendar is not None:
        _require_fronts_for(bars, calendar)
        fronts = _fronts_with_their_lead_in(calendar, contracts)
    grid = session_grid(bars, timeframe, sessions, received_until, lead_in, last, rows_for=fronts)
    return grid.join(contracts, on="instrument_id").select(CONTRACT_BAR_COLUMNS.names())


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


def _roll_calendar(
    store: Store, datasets: dict[str, Dataset], instrument: Instrument, sessions: SessionTable
) -> RollCalendar:
    """The root's roll calendar, from the 1-minute bars of its whole dataset, or else its
    finest bars (an import's 5-minute bars), whatever the window, and from its first whole
    session: the bars of a first session the data starts
    inside are left out, since their volumes are partial. It rolls by volume, the only rule load
    applies, and a product the catalog gives another rule is refused rather than rolled by
    volume (step 2.9)."""
    rule = CATALOG.roll_rule(instrument.root)
    if rule is not RollRule.VOLUME:
        raise ValueError(
            f"Expected the roll rule volume for {instrument.root}, the only rule load applies, "
            f"got {rule} in the product catalog (fefat.market.catalog)."
        )
    request = PartitionRequest(
        dataset=roll_dataset(datasets, instrument.root), start=date.min, end=date.max
    )
    bars = store.scan_contracts(request).collect()
    first_day, first_open, received_until = bars.select(
        pl.col("trade_date").min(), pl.col("ts_open").min(), pl.col("ts_close").max()
    ).row(0)
    if first_open > sessions.session(first_day).open:
        bars = bars.filter(pl.col("trade_date") > first_day)
    return volume_rolls(bars, sessions, instrument, received_until)


def _fronts_with_their_lead_in(calendar: RollCalendar, contracts: pl.DataFrame) -> pl.DataFrame:
    """The sessions and instruments a spliced load grids: each session's front, and each front
    on the session before it took over, so that a new front's rows on its first day start at
    the open when it traded the session before, whatever day a window starts."""
    fronts = calendar.rows.select("trade_date", "contract")
    lead_in = fronts.with_columns(trade_date=pl.col("trade_date").shift(1)).drop_nulls()
    return (
        pl.concat([fronts, lead_in])
        .unique()
        .join(contracts, on="contract")
        .select("trade_date", "instrument_id")
    )


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
