"""The SDK's data API (steps 1.8 and 1.9): `load` gives the signal bars of a product or a
contract in one call, and `catalog` lists what the store holds.

    import fefat as ff

    bars = ff.market.load("MES", "5m", "2024-01-01", "2024-03-31").collect()
    march = ff.market.load("MESH2024", "1m", "2024-03-01", "2024-03-15").collect()
    ticks = ff.market.load("ES", "1m", "2026-03-06", "2026-03-06", fidelity="tick")
    from_databento = ff.market.load("MES", "5m", "2024-01-01", "2024-03-31", provider="databento")
    ff.market.catalog()

Both read the store in `FEFAT_DATA_DIR` (`fefat.config.resolve_paths`), and the session tables
cached in `FEFAT_HOME`.

`load(root_or_symbol, timeframe, start, end, continuous=None, fidelity="auto", provider=None)`
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
- `close_raw`: the contract's own close, which orders execute against;
- `adj_offset`: what was added to the raw prices, so that `close = close_raw + adj_offset`;
- `roll_flag`: true on the first bar of each new front contract, on the trade date it rolled;
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

`fidelity` names the data the bars are built from: `tick` (trades), `1s`, or `1m` bars, or
`auto`, the finest the store holds; a timeframe finer than it is refused. `provider` names the
provider whose datasets the bars come from, such as `databento`, where several hold the root;
without it a root that several hold is refused, since choosing by the catalog's
recommendation waits for a second provider (step 1.10). The bars are built when `load` runs,
and the frame is lazy so that a notebook adds its own columns and filters before it collects.
"""

import os
from datetime import date, datetime

import polars as pl

from fefat.config import resolve_paths
from fefat.market import instruments
from fefat.market.bars import build_bars, resample_bars, session_grid
from fefat.market.builtin_calendars import BUILT_IN
from fefat.market.calendar import SessionTable, sessions_of
from fefat.market.catalog import CATALOG
from fefat.market.continuous import CONTINUOUS_COLUMNS, RollCalendar, volume_rolls
from fefat.market.continuous_check import contracts_by_instrument
from fefat.market.contracts import parse_contract_name
from fefat.market.coverage import Fidelity, dataset_coverage, session_datasets
from fefat.market.instruments import Instrument, InstrumentKind
from fefat.market.layout import Dataset, PartitionRequest
from fefat.market.roll_decisions import CONTRACT_BAR_COLUMNS
from fefat.market.schema import (
    BarSchemaName,
    SchemaKind,
    Timeframe,
)
from fefat.market.status import DATASET_COLUMNS, dataset_status
from fefat.market.store import Store

SIGNAL_BAR_COLUMNS = pl.Schema({**CONTINUOUS_COLUMNS, "zero_volume": pl.Boolean})
"""The columns `load` returns, whatever the mode: a bar's, its contract, its raw close, the
offset of its prices, whether it is a new front's first, and whether its bucket is empty."""
AUTO = "auto"
"""The fidelity of `load` that takes the finest data the store holds."""
CATALOG_COLUMNS = pl.Schema({**DATASET_COLUMNS, "catalog_version": pl.UInt32})
"""The catalog's row per dataset of trades, TBBO, or bars: the columns of `DATASET_COLUMNS`
(`fefat.market.status`) and the version of the product catalog (`fefat.market.catalog`)."""


def load(
    root_or_symbol: str,
    timeframe: str,
    start: str | date,
    end: str | date,
    continuous: bool | None = None,
    fidelity: str = AUTO,
    provider: str | None = None,
) -> pl.LazyFrame:
    """The signal bars of `root_or_symbol` (a root such as `MES`, or a contract such as
    `MESH2024`) of `timeframe` on the trade dates from `start` to `end`, with the columns of
    `SIGNAL_BAR_COLUMNS`; the module docstring has the details and examples."""
    root, contract = _root_and_contract(root_or_symbol)
    instrument = instruments.get(root)
    splices = _splices(instrument, contract, continuous)
    first, last = _trade_date(start, "start"), _trade_date(end, "end")
    if last < first:
        raise ValueError(f"Expected the start {first} on or before the end, got the end {last}.")
    bar_timeframe = Timeframe.parse(timeframe)
    paths = resolve_paths(os.environ)
    store = Store(paths.data_dir)
    # shortcut: the calendar of the root's newest instrument version, as the quality report
    # takes it; load by version when a root's calendar changes over time.
    sessions = sessions_of(BUILT_IN[instrument.calendar_id], paths.cache_dir)
    datasets = _datasets_of(store, root, provider)
    source = _source(datasets, fidelity, bar_timeframe, root)
    gridded = _gridded(store, source, bar_timeframe, sessions, first, last, contract)
    if not splices:
        bars = _signal_bars(_unspliced(gridded), first, last, ("contract", "ts_open"))
        if contract is not None and bars.is_empty():
            raise ValueError(
                f"Expected bars of {contract} from {first} to {last} in the store, got none."
            )
        return bars.lazy()
    calendar = _roll_calendar(store, datasets, instrument, sessions)
    _require_fronts_for(gridded, calendar)
    return _signal_bars(_spliced(gridded, calendar), first, last, ("ts_open",)).lazy()


def catalog() -> pl.DataFrame:
    """Every dataset of trades, TBBO, or bars the store holds, with the columns of
    `CATALOG_COLUMNS`, sorted by provider, root, and schema; an empty store gives no rows, and
    `ff.market.CATALOG.version` the catalog's version whatever the store holds."""
    paths = resolve_paths(os.environ)
    datasets = dataset_status(Store(paths.data_dir), paths.reports_dir)
    return datasets.with_columns(catalog_version=pl.lit(CATALOG.version, dtype=pl.UInt32))


def _root_and_contract(symbol: str) -> tuple[str, str | None]:
    """The root a symbol names, and the contract when it names one (`MESH2024`)."""
    roots = instruments.STATIC_TABLE.roots()
    if symbol in roots:
        return symbol, None
    try:
        root, _ = parse_contract_name(symbol)
    except ValueError as error:
        raise ValueError(
            f"Expected a root ({', '.join(roots)}) or a contract such as MESH2024, got {symbol!r}."
        ) from error
    instruments.get(root)
    return root, symbol


def _splices(instrument: Instrument, contract: str | None, continuous: bool | None) -> bool:
    """Whether the load splices the root's contracts: by default for a futures root, and
    never for a contract or a product that does not expire."""
    splices_by_default = contract is None and instrument.kind is InstrumentKind.FUTURES
    if continuous is None:
        return splices_by_default
    if continuous and not splices_by_default:
        named = (
            f"the contract {contract}" if contract else f"the {instrument.kind} {instrument.root}"
        )
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


def _datasets_of(store: Store, root: str, provider: str | None) -> dict[str, Dataset]:
    """The root's datasets of trades, TBBO, and bars by their schema, from `provider`, or from
    the one provider that holds the root when it is None."""
    found = [dataset for dataset in session_datasets(store) if dataset.root == root]
    providers = sorted({dataset.provider for dataset in found})
    held = " and ".join(providers) if providers else "none"
    if provider is not None and provider not in providers:
        raise ValueError(f"Expected a provider of {root} in the store ({held}), got {provider!r}.")
    if provider is None and len(providers) != 1:
        hint = "; name one with provider=" if providers else ""
        raise ValueError(f"Expected one provider of {root} in the store, got {held}{hint}.")
    chosen = providers[0] if provider is None else provider
    return {str(dataset.schema_name): dataset for dataset in found if dataset.provider == chosen}


def _source(
    datasets: dict[str, Dataset], fidelity: str, timeframe: Timeframe, root: str
) -> Dataset:
    """The dataset of the fidelity named, or with `auto` of the finest the store holds, whose
    data is no coarser than `timeframe`."""
    held = [held for held in Fidelity if str(held.schema_name()) in datasets]
    chosen = _chosen_fidelity(fidelity, held, root)
    finest = chosen.schema_name()
    if (
        isinstance(finest, BarSchemaName)
        and timeframe.nominal_seconds() < finest.timeframe.nominal_seconds()
    ):
        raise ValueError(
            f"Expected a timeframe of {chosen} or coarser from {chosen.records()} of {root}, "
            f"got {timeframe}."
        )
    return datasets[str(finest)]


def _chosen_fidelity(fidelity: str, held: list[Fidelity], root: str) -> Fidelity:
    """The fidelity named, or with `auto` the finest of those `held`; one the store does not
    hold is refused."""
    if fidelity == AUTO and held:
        return held[0]
    if fidelity == AUTO:
        raise ValueError(f"Expected trades, 1-second, or 1-minute bars of {root}, got none.")
    try:
        chosen = Fidelity(fidelity)
    except ValueError as error:
        named = ", ".join(choice.value for choice in Fidelity)
        raise ValueError(f"Expected a fidelity of {AUTO}, {named}, got {fidelity!r}.") from error
    if chosen not in held:
        raise ValueError(f"Expected {chosen.records()} of {root} in the store, got none.")
    return chosen


def _gridded(
    store: Store,
    source: Dataset,
    timeframe: Timeframe,
    sessions: SessionTable,
    first: date,
    last: date,
    contract: str | None,
) -> pl.DataFrame:
    """The bars of `timeframe` built from `source` on the session grid, with the columns of
    `CONTRACT_BAR_COLUMNS`, from the session before `first`, so that a contract that traded in
    it has the same rows on `first` whatever day a window starts, up to `last` and the end of
    the data."""
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
    grid = session_grid(bars, timeframe, sessions, received_until, lead_in, last)
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
    """The root's roll calendar, from the 1-minute bars of its whole dataset, whatever the
    window, and from its first whole session: the bars of a first session the data starts
    inside are left out, since their volumes are partial."""
    minutes = datasets.get("ohlcv-1m")
    if minutes is None:
        raise ValueError(
            f"Expected 1-minute bars of {instrument.root} to splice its contracts, got none."
        )
    request = PartitionRequest(dataset=minutes, start=date.min, end=date.max)
    bars = store.scan_contracts(request).collect()
    first_day, first_open, received_until = bars.select(
        pl.col("trade_date").min(), pl.col("ts_open").min(), pl.col("ts_close").max()
    ).row(0)
    if first_open > sessions.session(first_day).open:
        bars = bars.filter(pl.col("trade_date") > first_day)
    return volume_rolls(bars, sessions, instrument, received_until)


def _require_fronts_for(gridded: pl.DataFrame, calendar: RollCalendar) -> None:
    """Refuse bars of sessions after the roll calendar's last, whose fronts no 1-minute bars
    decided, as finer data that runs past the 1-minute bars gives: splicing would drop them."""
    decided = calendar.rows.get_column("trade_date")
    beyond = gridded.get_column("trade_date")
    if not decided.is_empty():
        beyond = beyond.filter(beyond > decided.max())
    if beyond.is_empty():
        return
    through = "no session" if decided.is_empty() else f"{decided.max()}"
    raise ValueError(
        f"Expected 1-minute bars of {calendar.root} that decide the front contracts through "
        f"{beyond.max()}, got fronts through {through}."
    )


def _spliced(gridded: pl.DataFrame, calendar: RollCalendar) -> pl.DataFrame:
    """The front's grid rows of each session, adjusted (`RollCalendar.continuous_bars`), with
    `roll_flag` on the first bar of each new front on the trade date it rolled, whatever bars
    the window holds before it."""
    rolled_to = calendar.rolls().select("trade_date", "contract", rolled=pl.lit(True))
    first_bar = pl.col("ts_open") == pl.col("ts_open").min().over("trade_date", "contract")
    return (
        calendar.continuous_bars(gridded)
        .join(rolled_to, on=["trade_date", "contract"], how="left")
        .with_columns(roll_flag=pl.col("rolled").fill_null(False) & first_bar)
        .drop("rolled")
    )


def _unspliced(gridded: pl.DataFrame) -> pl.DataFrame:
    return gridded.with_columns(
        close_raw=pl.col("close"),
        adj_offset=pl.lit(0, dtype=pl.Int64),
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
