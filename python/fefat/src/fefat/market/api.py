"""The SDK's data API (steps 1.8 and 1.9): `load` gives the signal bars of a product or a
contract in one call, `datasets` lists what the store holds, and `roll_calendar` gives the roll
calendar `load` splices a future with (step 2.9). `series_source` gives what `load` reads a
symbol's bars from, built once to give the bars of many windows, as the feature cache reads a
window's partitions (step 3.3), and `series_source_in` the same for a store its caller names
(`fefat.market.series_source`, step 5.1); and a roll calendar is built once in a process for each
state of the data it reads, so that a notebook's loop of loads, a cache's partitions, and a
backtest do not build it again (D-71).

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
from datetime import date, datetime

import polars as pl

from fefat.config import resolve_paths
from fefat.market.catalog import CATALOG
from fefat.market.continuous import RollCalendar
from fefat.market.dataset_choice import provider_datasets
from fefat.market.fidelity import TickFidelity, parse_fidelity
from fefat.market.roll_calendars import kept_roll_calendar
from fefat.market.saved_instruments import instrument_table
from fefat.market.schema import Timeframe
from fefat.market.series_source import (
    SIGNAL_BAR_COLUMNS,
    SeriesSource,
    parse_origin,
    series_source,
)
from fefat.market.status import DATASET_COLUMNS, dataset_status
from fefat.market.store import Store

__all__ = [
    "DATASETS_COLUMNS",
    "SIGNAL_BAR_COLUMNS",
    "SeriesSource",
    "datasets",
    "load",
    "parse_trade_date",
    "roll_calendar",
    "series_source",
]

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
    datasets = provider_datasets(store, root, provider, parse_origin(origin))
    return kept_roll_calendar(store, datasets, instrument, sessions)


def datasets() -> pl.DataFrame:
    """Every dataset of trades, TBBO, or bars the store holds, with the columns of
    `DATASETS_COLUMNS`, sorted by provider, root, and schema; an empty store gives no rows, and
    `ff.market.CATALOG.version` the catalog's version whatever the store holds."""
    paths = resolve_paths(os.environ)
    listed = dataset_status(Store(paths.data_dir), paths.reports_dir)
    return listed.with_columns(catalog_version=pl.lit(CATALOG.version, dtype=pl.UInt32))


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
