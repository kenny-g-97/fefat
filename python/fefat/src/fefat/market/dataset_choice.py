"""Which of the store's datasets a load reads (`fefat.market.api.load`, steps 1.8 to 1.10,
`02-engine-and-data.md` §1.8).

A root's datasets come from one provider: the one named; the only one that holds the root; or,
where several hold a product of the catalog, the first of its recommended sources whose presets
hold it, Databento first for the catalog's futures. `origin` narrows them to imported or synced
data. A provider's datasets of a root hold dated contracts or one continuous series, never
both. A load builds its bars from the finest data the provider holds, or the data named:
trades (`tick`), then bars by their timeframe, finest first, none coarser than the bars asked
for; bars coarser than a minute are an import's finest data, which fill backtests at their own
fidelity. The roll calendar reads the 1-minute bars, or else the finest bars held.
"""

from fefat.market.catalog import CATALOG, Catalog
from fefat.market.coverage import session_datasets
from fefat.market.layout import Dataset, DatasetOrigin, SeriesKind
from fefat.market.schema import BarSchemaName, SchemaKind, Timeframe
from fefat.market.sources import SOURCE_GUIDE, SourceGuide
from fefat.market.store import Store

AUTO = "auto"
"""The fidelity of `load` that takes the finest data the store holds."""
TICK = "tick"
"""The fidelity of trades."""


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


def source_dataset(
    datasets: dict[str, Dataset], fidelity: str, timeframe: Timeframe, root: str
) -> Dataset:
    """The dataset of the fidelity named, `tick` or a timeframe such as `1m`, or with `auto` of
    the finest held, whose data is no coarser than `timeframe`."""
    held = _finest_first(datasets)
    if fidelity != AUTO and fidelity != TICK:
        _require_a_timeframe(fidelity)
    chosen = [pair for pair in held if fidelity in (AUTO, pair[0])]
    if not chosen and fidelity == AUTO:
        raise ValueError(f"Expected trades or bars of {root}, got none.")
    if not chosen:
        raise ValueError(f"Expected {_records(fidelity)} of {root} in the store, got none.")
    label, source = chosen[0]
    schema_name = source.schema_name
    if (
        isinstance(schema_name, BarSchemaName)
        and timeframe.nominal_seconds() < schema_name.timeframe.nominal_seconds()
    ):
        raise ValueError(
            f"Expected a timeframe of {label} or coarser from {_records(label)} of {root}, "
            f"got {timeframe}."
        )
    return source


def roll_dataset(datasets: dict[str, Dataset], root: str) -> Dataset:
    """The bars the root's roll calendar is built from: its 1-minute bars, or else its finest."""
    minutes = datasets.get("ohlcv-1m")
    if minutes is not None:
        return minutes
    bars = [dataset for label, dataset in _finest_first(datasets) if label != TICK]
    if not bars:
        raise ValueError(f"Expected bars of {root} to splice its contracts, got none.")
    return bars[0]


def _finest_first(datasets: dict[str, Dataset]) -> list[tuple[str, Dataset]]:
    """The datasets a load builds bars from, by their fidelity: trades, then bars by timeframe."""
    trades = [
        (TICK, dataset)
        for dataset in datasets.values()
        if dataset.schema_name.kind is SchemaKind.TRADES
    ]
    bars = sorted(
        (
            (str(dataset.schema_name.timeframe), dataset)
            for dataset in datasets.values()
            if isinstance(dataset.schema_name, BarSchemaName)
        ),
        key=lambda pair: Timeframe.parse(pair[0]).nominal_seconds(),
    )
    return [*trades, *bars]


def _require_a_timeframe(fidelity: str) -> None:
    try:
        Timeframe.parse(fidelity)
    except ValueError as error:
        raise ValueError(
            f"Expected a fidelity of {AUTO}, {TICK}, or a timeframe such as 1m, got {fidelity!r}."
        ) from error


def _records(label: str) -> str:
    """What the data of a fidelity is called: trades, or bars such as 1-minute bars."""
    if label == TICK:
        return "trades"
    return f"{Timeframe.parse(label).in_words()} bars"
