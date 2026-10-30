"""Which of the store's datasets a load reads (`fefat.market.api.load`, steps 1.8 to 1.10,
`02-engine-and-data.md` §1.8).

A root's datasets come from one provider: the one named; the only one that holds the root; or,
where several hold a product of the catalog, the first of its recommended sources whose presets
hold it, Databento first for the catalog's futures. `origin` narrows them to imported or synced
data. A provider's datasets of a root hold dated contracts or one continuous series, never
both. A load builds its bars from the finest data the provider holds, or the fidelity named
(`fefat.market.fidelity`): trades, then bars by their timeframe, finest first, none coarser
than the bars asked for; bars coarser than a minute are an import's finest data, which fill
backtests at their own fidelity. The roll calendar reads the 1-minute bars, or else the finest
bars held. `dataset_warnings` names what every load of a dataset, and its import, warns of. A
backtest builds its signal bars from the data `signal_source` names (step 2.12).
"""

from datetime import date

from fefat.market.catalog import CATALOG, Catalog
from fefat.market.coverage import dataset_coverage, session_datasets
from fefat.market.fidelity import ONE_MINUTE, ONE_SECOND, TickFidelity
from fefat.market.layout import Dataset, DatasetOrigin, SeriesKind
from fefat.market.schema import BarSchemaName, SchemaKind, Timeframe
from fefat.market.sources import SOURCE_GUIDE, SourceGuide
from fefat.market.store import Store


def provider_datasets(
    store: Store,
    root: str,
    provider: str | None,
    origin: DatasetOrigin | None,
    catalog: Catalog = CATALOG,
    guide: SourceGuide = SOURCE_GUIDE,
) -> dict[str, Dataset]:
    """The root's datasets of trades, TBBO, and bars of one provider, by their schema, of
    `origin` where it is named (module docstring)."""
    found = [
        dataset
        for dataset in session_datasets(store)
        if dataset.root == root
        and (origin is None or store.dataset_metadata(dataset).origin is origin)
    ]
    providers = sorted({dataset.provider for dataset in found})
    if provider is not None and provider not in providers:
        held = " and ".join(providers) if providers else "none"
        raise ValueError(f"Expected a provider of {root} in the store ({held}), got {provider!r}.")
    chosen = _one_provider(root, providers, catalog, guide) if provider is None else provider
    return {str(dataset.schema_name): dataset for dataset in found if dataset.provider == chosen}


def _one_provider(root: str, providers: list[str], catalog: Catalog, guide: SourceGuide) -> str:
    if len(providers) == 1:
        return providers[0]
    recommended = _recommended(root, providers, catalog, guide)
    if recommended is not None:
        return recommended
    held = " and ".join(providers) if providers else "none"
    hint = "; name one with provider=" if providers else ""
    raise ValueError(f"Expected one provider of {root} in the store, got {held}{hint}.")


def _recommended(
    root: str, providers: list[str], catalog: Catalog, guide: SourceGuide
) -> str | None:
    """The first preset, among the presets of the catalog product's sources in order of
    recommendation, that is one of the `providers`; None for a root the catalog does not list."""
    products = [product for product in catalog.products if product.root == root]
    if not products:
        return None
    for source_id in products[0].sources:
        for preset in guide.source(source_id).presets:
            if preset.id in providers:
                return preset.id
    return None


def series_of(store: Store, datasets: dict[str, Dataset]) -> SeriesKind:
    """The series kind the provider's datasets of a root share; datasets that mix kinds, which
    imports keep apart, are refused."""
    kinds = {store.dataset_metadata(dataset).series for dataset in datasets.values()}
    if len(kinds) != 1:
        named = ", ".join(sorted(kinds)) if kinds else "none"
        folders = ", ".join(str(dataset.relative_folder()) for dataset in datasets.values())
        raise ValueError(f"Expected the datasets {folders} of one series kind, got {named}.")
    return kinds.pop()


def dataset_warnings(dataset: Dataset, series: SeriesKind) -> list[str]:
    """What every load of `dataset`, and its import, warns of: bars coarser than a minute,
    which fill backtests at their own fidelity, and a continuous series, which runs without
    rolls and, back-adjusted, at prices no order traded at (D-49)."""
    folder = dataset.relative_folder()
    schema_name = dataset.schema_name
    found = []
    if (
        isinstance(schema_name, BarSchemaName)
        and schema_name.timeframe.nominal_seconds() > ONE_MINUTE.nominal_seconds()
    ):
        found.append(
            f"{folder} holds {schema_name.timeframe.in_words()} bars, coarser than a minute: "
            "backtests on them fill at that fidelity"
        )
    if series is not SeriesKind.CONTRACT:
        distortion = (
            ", and its back-adjusted prices distort price levels and are no prices an order "
            "traded at, so its bars have no raw close"
            if series is SeriesKind.CONTINUOUS_BACK_ADJUSTED
            else ""
        )
        found.append(
            f"{folder} is a {series} series, one synthetic contract with roll handling "
            f"off{distortion}"
        )
    return found


def source_dataset(
    datasets: dict[str, Dataset],
    fidelity: TickFidelity | Timeframe | None,
    timeframe: Timeframe,
    root: str,
) -> Dataset:
    """The dataset of the fidelity named, trades or bars of a timeframe such as `1m`, or
    without one the finest held, whose data is no coarser than `timeframe`."""
    held = _finest_first(datasets)
    if fidelity is None:
        if not held:
            raise ValueError(f"Expected trades or bars of {root}, got none.")
        return _no_coarser_than(held[0], timeframe, root)
    if fidelity is TickFidelity.TBBO:
        raise ValueError(
            "Expected trades or bars to build bars from, got tbbo: load does not build bars from "
            "TBBO yet (docs/masterplan/BACKLOG.md)."
        )
    chosen = [pair for pair in held if pair[0] == fidelity]
    if not chosen:
        raise ValueError(f"Expected {_records(fidelity)} of {root} in the store, got none.")
    return _no_coarser_than(chosen[0], timeframe, root)


def roll_dataset(datasets: dict[str, Dataset], root: str) -> Dataset:
    """The bars the root's roll calendar is built from: its 1-minute bars, or else its finest."""
    minutes = datasets.get("ohlcv-1m")
    if minutes is not None:
        return minutes
    bars = [
        dataset for fidelity, dataset in _finest_first(datasets) if isinstance(fidelity, Timeframe)
    ]
    if not bars:
        raise ValueError(f"Expected bars of {root} to splice its contracts, got none.")
    return bars[0]


_SIGNAL_SOURCES: tuple[TickFidelity | Timeframe, ...] = (
    ONE_MINUTE,
    ONE_SECOND,
    TickFidelity.TRADES,
)
"""The data a backtest's signal bars may be built from."""


def signal_source(
    store: Store, datasets: dict[str, Dataset], timeframe: Timeframe, dates: tuple[date, date]
) -> TickFidelity | Timeframe:
    """The data a backtest builds its signal bars of `timeframe` from (step 2.12): of the
    1-minute bars, 1-second bars, and trades held that build them, the finest of those whose
    trade dates cover the most of the window from `dates`' first to its last, since ticks may
    cover a part of the window that bars cover, or bars a part the ticks cover, and among equals
    `load`'s own choice, whose trades give the vwap and trade count an import's bars lack (your
    choice of 2026-10-30); else what `load` reads, the finest data held, an import's coarser
    bars, which it refuses when they are coarser than `timeframe`."""
    held = _finest_first(datasets)
    if not held:
        named = ", ".join(sorted(datasets)) or "none"
        raise ValueError(f"Expected trades or bars to build signal bars from, got {named}.")
    building = [
        (level, dataset)
        for level, dataset in held
        if level in _SIGNAL_SOURCES and _builds(level, timeframe)
    ]
    if not building:
        return held[0][0]
    covered = [_days_covered(store, dataset, dates) for _, dataset in building]
    return building[covered.index(max(covered))][0]


def _builds(level: TickFidelity | Timeframe, timeframe: Timeframe) -> bool:
    """Whether `level` builds bars of `timeframe`: trades always, and bars whose length divides
    its length, bucketed alike from the session's open (`02` §1.4)."""
    if not isinstance(level, Timeframe):
        return True
    return timeframe.nominal_seconds() % level.nominal_seconds() == 0


def _days_covered(store: Store, dataset: Dataset, dates: tuple[date, date]) -> int:
    """How many days of the window from `dates`' first to its last lie between the dataset's
    first and last trade dates."""
    coverage = dataset_coverage(store, dataset)
    if coverage is None:
        return 0
    first = max(dates[0], coverage.first_trade_date)
    last = min(dates[1], coverage.last_trade_date)
    return max(0, (last - first).days + 1)


def _finest_first(
    datasets: dict[str, Dataset],
) -> list[tuple[TickFidelity | Timeframe, Dataset]]:
    """The datasets a load builds bars from, by their fidelity: trades, then bars by timeframe."""
    trades: list[tuple[TickFidelity | Timeframe, Dataset]] = [
        (TickFidelity.TRADES, dataset)
        for dataset in datasets.values()
        if dataset.schema_name.kind is SchemaKind.TRADES
    ]
    bars = sorted(
        (
            (dataset.schema_name.timeframe, dataset)
            for dataset in datasets.values()
            if isinstance(dataset.schema_name, BarSchemaName)
        ),
        key=lambda pair: pair[0].nominal_seconds(),
    )
    return [*trades, *bars]


def _no_coarser_than(
    pair: tuple[TickFidelity | Timeframe, Dataset], timeframe: Timeframe, root: str
) -> Dataset:
    """The dataset of `pair`, refused where its bars are coarser than `timeframe`."""
    fidelity, source = pair
    if isinstance(fidelity, Timeframe) and timeframe.nominal_seconds() < fidelity.nominal_seconds():
        raise ValueError(
            f"Expected a timeframe of {fidelity} or coarser from {_records(fidelity)} of {root}, "
            f"got {timeframe}."
        )
    return source


def _records(fidelity: TickFidelity | Timeframe) -> str:
    """What the data of a fidelity is called: trades, or bars such as 1-minute bars."""
    if isinstance(fidelity, Timeframe):
        return f"{fidelity.in_words()} bars"
    return "trades"
