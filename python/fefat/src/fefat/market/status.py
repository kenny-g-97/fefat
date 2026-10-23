"""What the store holds of each dataset and of each catalog product (step 1.9,
`02-engine-and-data.md` §1.8).

`dataset_status` gives each dataset of trades, TBBO, or bars its provider, root, schema, and
fidelity, its contracts and trade dates, the quality verdict of its root's report from its
provider, stale when the report's last trade date is before the dataset's, the origin and
licence scope of its `dataset.json`, and the last day a file of its provider that fed its root
was imported, from the raw manifest; `ff.market.catalog()` lists it. `product_status` gives
each product of the catalog, in catalog order, its datasets, complete at their fidelity when
they start by the first trade date of the product's history and partial when after it, or one
row that says it is missing, with its first recommended source; then the datasets of roots the
catalog does not list, unlisted. `fefat data status` prints it.

    paths = resolve_paths(os.environ)
    product_status(Store(paths.data_dir), paths.reports_dir)
"""

from enum import StrEnum
from pathlib import Path

import polars as pl

from fefat.market.catalog import CATALOG, Catalog
from fefat.market.coverage import DatasetCoverage, dataset_coverage, session_datasets
from fefat.market.fidelity import TickFidelity
from fefat.market.layout import Dataset, DatasetMetadata
from fefat.market.quality_report import quality_standing, quality_verdict
from fefat.market.raw_manifest import RawManifest
from fefat.market.schema import BarSchemaName, SchemaKind
from fefat.market.sources import SOURCE_GUIDE, SourceGuide
from fefat.market.store import Store

DATASET_COLUMNS = pl.Schema(
    {
        "provider": pl.String,
        "root": pl.String,
        "schema": pl.String,
        "fidelity": pl.String,
        "contracts": pl.UInt32,
        "first_trade_date": pl.Date,
        "last_trade_date": pl.Date,
        "quality": pl.String,
        "checked_through": pl.Date,
        "origin": pl.String,
        "licence_scope": pl.String,
        "last_import": pl.Date,
    }
)
"""A dataset's row: its provider, root, and schema; its fidelity (`fefat.market.fidelity`),
`trades`, `tbbo`, or the timeframe of its bars; how many contracts it holds; its first and last trade date; the
quality verdict of its root's report from its provider, with the last trade date the report
checked, none while unchecked; its origin and the licence scope of its source; and the last day
a file of its provider that fed its root was imported, none without a record of one."""


class CoverageStatus(StrEnum):
    """How a dataset covers a catalog product: from the first trade date of the product's
    history, or from later; a product without any dataset is missing, and a dataset of a root
    the catalog does not list is unlisted."""

    COMPLETE = "complete"
    PARTIAL = "partial"
    MISSING = "missing"
    UNLISTED = "unlisted"


STATUS_COLUMNS = pl.Schema(
    {
        "root": pl.String,
        "coverage": pl.String,
        "history_from": pl.Date,
        "recommended_source": pl.String,
        **{name: dtype for name, dtype in DATASET_COLUMNS.items() if name != "root"},
    }
)
"""A row of `product_status`: the root and its coverage, the first trade date of its catalog
history and the name of its first recommended source, none for an unlisted root, and the
columns of `DATASET_COLUMNS`, none for a missing product."""

_CATALOG_ORDER = "catalog_order"


def dataset_status(store: Store, reports_folder: Path) -> pl.DataFrame:
    """Every dataset of trades, TBBO, or bars the store holds, with the columns of
    `DATASET_COLUMNS`, sorted by provider, root, and schema; the quality reports are read from
    `reports_folder`."""
    manifest = store.raw_manifest()
    rows = [
        _dataset_row(dataset, coverage, store.dataset_metadata(dataset), reports_folder, manifest)
        for dataset in session_datasets(store)
        if (coverage := dataset_coverage(store, dataset)) is not None
    ]
    return pl.DataFrame(rows, schema=DATASET_COLUMNS, orient="row").sort(
        "provider", "root", "schema"
    )


def product_status(
    store: Store,
    reports_folder: Path,
    catalog: Catalog = CATALOG,
    guide: SourceGuide = SOURCE_GUIDE,
) -> pl.DataFrame:
    """Each product of `catalog` with its datasets, then the datasets of the roots it does not
    list, with the columns of `STATUS_COLUMNS`."""
    datasets = dataset_status(store, reports_folder)
    products = _products(catalog, guide)
    listed = products.join(datasets, on="root", how="left").with_columns(coverage=_coverage())
    unlisted = datasets.join(products, on="root", how="anti").with_columns(
        coverage=pl.lit(CoverageStatus.UNLISTED.value),
        history_from=pl.lit(None, dtype=pl.Date),
        recommended_source=pl.lit(None, dtype=pl.String),
        **{_CATALOG_ORDER: pl.lit(len(catalog.products), dtype=pl.UInt32)},
    )
    columns = [*STATUS_COLUMNS.names(), _CATALOG_ORDER]
    return (
        pl.concat([listed.select(columns), unlisted.select(columns)])
        .sort(_CATALOG_ORDER, "root", "provider", "schema")
        .drop(_CATALOG_ORDER)
    )


def _fidelity_text(dataset: Dataset) -> str:
    """The fidelity of a dataset of trades, TBBO, or bars, as its text."""
    if isinstance(dataset.schema_name, BarSchemaName):
        return str(dataset.schema_name.timeframe)
    if dataset.schema_name.kind is SchemaKind.TBBO:
        return str(TickFidelity.TBBO)
    return str(TickFidelity.TRADES)


def _dataset_row(
    dataset: Dataset,
    coverage: DatasetCoverage,
    metadata: DatasetMetadata,
    reports_folder: Path,
    manifest: RawManifest,
) -> tuple[object, ...]:
    standing = quality_verdict(
        quality_standing(reports_folder, dataset.provider, dataset.root),
        coverage.last_trade_date,
    )
    return (
        dataset.provider,
        dataset.root,
        str(dataset.schema_name),
        _fidelity_text(dataset),
        len(coverage.contracts),
        coverage.first_trade_date,
        coverage.last_trade_date,
        str(standing.status),
        standing.checked_through,
        str(metadata.origin),
        metadata.licence_scope,
        manifest.last_import(dataset.provider, dataset.root),
    )


def _products(catalog: Catalog, guide: SourceGuide) -> pl.DataFrame:
    """The catalog's products in order, with the first trade date of their history and the
    name of their first recommended source."""
    return pl.DataFrame(
        {
            "root": catalog.roots(),
            "history_from": [product.history_from for product in catalog.products],
            "recommended_source": [
                guide.source(product.sources[0]).name for product in catalog.products
            ],
            _CATALOG_ORDER: list(range(len(catalog.products))),
        },
        schema={
            "root": pl.String,
            "history_from": pl.Date,
            "recommended_source": pl.String,
            _CATALOG_ORDER: pl.UInt32,
        },
    )


def _coverage() -> pl.Expr:
    """A catalog product's coverage by its dataset: missing without one, complete when the
    dataset starts by the product's history, and partial when it starts after."""
    return (
        pl.when(pl.col("provider").is_null())
        .then(pl.lit(CoverageStatus.MISSING.value))
        .when(pl.col("first_trade_date") <= pl.col("history_from"))
        .then(pl.lit(CoverageStatus.COMPLETE.value))
        .otherwise(pl.lit(CoverageStatus.PARTIAL.value))
    )
