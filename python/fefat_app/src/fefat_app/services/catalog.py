"""The data catalog over the API (step 5.1, `01-architecture.md` section 7, D-93): what the store
in the data folder holds, read through the SDK each time it is asked, with nothing kept in the
database until a step writes state of its own there (D-83): the datasets with their quality, a
dataset's findings, the catalog's products with the datasets that cover them, the source guide,
the instruments, and the bars of a window, a page at a time (`fefat_app.services.market_bars`);
and the catalog sync, the quality report of a product, or of every product, as a job of the pool
(`fefat_app.jobs.catalog_sync`), which a product's Update starts until the connectors (D-38).

A dataset's id names its provider, schema, and root, `provider:schema:root`, such as
`databento:ohlcv-1m:MES`, none of which holds a colon (`fefat.market.layout.FolderName`)."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal

import polars as pl
from pydantic import BaseModel, ConfigDict

from fefat.market.catalog import CATALOG
from fefat.market.coverage import SESSION_KINDS, DatasetCoverage, dataset_coverage
from fefat.market.instruments import STATIC_TABLE, Currency, Instrument, InstrumentKind
from fefat.market.layout import Dataset, DatasetOrigin
from fefat.market.quality import NothingToReportError, reported_products
from fefat.market.quality_report import QualityFinding, QualityStatus, stored_findings
from fefat.market.saved_instruments import instrument_table
from fefat.market.schema import parse_schema_name
from fefat.market.sources import SOURCE_GUIDE, SourceGuide
from fefat.market.status import (
    DATASET_COLUMNS,
    CoverageStatus,
    dataset_standing,
    dataset_status,
    product_status,
)
from fefat.market.store import ListedStore, Store
from fefat_app.ports import Job, JobKind
from fefat_app.services.jobs import Jobs
from fefat_app.services.market_bars import BarsPage, BarsRequest, bars_page

FINDINGS_SHOWN = 200
"""How many of a report's findings a dataset's quality lists, beside how many there are."""


class StoredDataset(BaseModel):
    """A dataset of trades, TBBO, or bars the store holds (`fefat.market.status`): its id; its
    provider, root, schema, and fidelity, `trades`, `tbbo`, or the timeframe of its bars; how
    many contracts it holds and its first and last trade date; the quality of its root's report
    from its provider, with the last trade date the report checked, none while unchecked; its
    origin and the licence scope of its source; and the last day a file of its provider that fed
    its root was imported, none without a record of one."""

    model_config = ConfigDict(frozen=True)

    id: str
    provider: str
    root: str
    schema_name: str
    fidelity: str
    contracts: int
    first_trade_date: date
    last_trade_date: date
    quality: QualityStatus
    checked_through: date | None
    origin: DatasetOrigin
    licence_scope: str
    last_import: date | None


class CoveringDataset(StoredDataset):
    """A dataset of a catalog product: complete when it starts by the first trade date of the
    product's history, partial when it starts after it."""

    coverage: Literal[CoverageStatus.COMPLETE, CoverageStatus.PARTIAL]


class CatalogProductStatus(BaseModel):
    """A product of the catalog: its root, the first trade date of its history, the name of its
    first recommended source, and the datasets of it the store holds, none while it is missing."""

    model_config = ConfigDict(frozen=True)

    root: str
    history_from: date
    recommended_source: str
    datasets: tuple[CoveringDataset, ...]


class CatalogStatus(BaseModel):
    """The catalog at its version: its products in its order, then the datasets of the roots it
    does not list."""

    model_config = ConfigDict(frozen=True)

    version: int
    products: tuple[CatalogProductStatus, ...]
    unlisted: tuple[StoredDataset, ...]


class ReportedFinding(BaseModel):
    """A finding of a quality report: its trade date, its kind, the schema and the contract it
    was found in, none for a gap, which no contract fills, and how many records or bars it
    counts."""

    model_config = ConfigDict(frozen=True)

    trade_date: date
    kind: QualityFinding
    schema_name: str
    contract: str | None
    count: int


class DatasetQuality(BaseModel):
    """A dataset's quality: the verdict of its root's report from its provider, as the dataset
    reads it, and the last trade date the report checked; and the report's findings, those of
    every schema of the root, which one verdict covers, the first `FINDINGS_SHOWN` with how many
    there are."""

    model_config = ConfigDict(frozen=True)

    id: str
    quality: QualityStatus
    checked_through: date | None
    findings: tuple[ReportedFinding, ...]
    findings_total: int


class InstrumentVersion(BaseModel):
    """A version of an instrument's specification (`fefat.market.instruments`): its root and
    kind; its tick size, what a point is worth, and its lot step, in its currency's units; the
    name of its session calendar; the trade dates it is in force, from `valid_from` to the day
    before `valid_to`; and whether an import saved it, where FEAT does not know the product."""

    model_config = ConfigDict(frozen=True)

    root: str
    kind: InstrumentKind
    tick_size: float
    point_value: float
    lot_step: float
    currency: Currency
    calendar: str
    valid_from: date
    valid_to: date | None
    saved: bool


class NoSuchDatasetError(ValueError):
    """An id that names no dataset of trades, TBBO, or bars the store holds."""

    def __init__(self, dataset_id: str) -> None:
        super().__init__(
            "Expected the id of a dataset the store holds, provider:schema:root such as "
            f"synthetic:trades:ES, got {dataset_id!r}."
        )


class NothingToSyncError(ValueError):
    """A catalog sync of a product, or of every product, that the store holds no trades, TBBO,
    or bars of, in the words of the quality report's refusal (`NothingToReportError`)."""


@dataclass(frozen=True)
class MarketCatalog:
    """What `store` holds, read at each call (module docstring), with its quality reports in
    `reports_folder` and the session tables cached in `cache_folder`, and the catalog syncs it
    starts through `jobs`."""

    store: Store
    reports_folder: Path
    cache_folder: Path
    jobs: Jobs

    def datasets(self) -> tuple[StoredDataset, ...]:
        """Every dataset of trades, TBBO, or bars the store holds, by provider, root, and
        schema."""
        status = dataset_status(self.store, self.reports_folder)
        return tuple(_stored(row) for row in status.iter_rows(named=True))

    def dataset_quality(self, dataset_id: str) -> DatasetQuality:
        """The quality of the dataset `dataset_id` names; `NoSuchDatasetError` where the store
        holds no such dataset."""
        listed = ListedStore(self.store.folder)
        dataset, coverage = _held(listed, dataset_id)
        standing = dataset_standing(listed, dataset, coverage.last_trade_date, self.reports_folder)
        findings = stored_findings(self.reports_folder, dataset.provider, dataset.root)
        shown = findings.head(FINDINGS_SHOWN).iter_rows(named=True)
        return DatasetQuality(
            id=dataset_id,
            quality=standing.status,
            checked_through=standing.checked_through,
            findings=tuple(_finding(row) for row in shown),
            findings_total=findings.height,
        )

    def catalog_status(self) -> CatalogStatus:
        """The catalog's products, each with the datasets that cover it, then the datasets of
        the roots it does not list."""
        status = product_status(self.store, self.reports_folder)
        unlisted = pl.col("coverage") == CoverageStatus.UNLISTED.value
        products = status.filter(~unlisted).group_by("root", maintain_order=True)
        return CatalogStatus(
            version=CATALOG.version,
            products=tuple(_product(rows) for _, rows in products),
            unlisted=tuple(_stored(row) for row in status.filter(unlisted).iter_rows(named=True)),
        )

    def source_guide(self) -> SourceGuide:
        """The source guide FEAT ships (`fefat.market.sources`), as it is: no connection state
        until the connectors (D-38)."""
        return SOURCE_GUIDE

    def instruments(self) -> tuple[InstrumentVersion, ...]:
        """Every version of every instrument, FEAT's and those imports saved, by root and the day
        each starts."""
        versions = instrument_table(self.store.folder).versions
        known = STATIC_TABLE.roots()
        ordered = sorted(versions, key=lambda version: (version.root, version.valid_from))
        return tuple(_instrument_version(each, each.root not in known) for each in ordered)

    def bars(self, request: BarsRequest) -> BarsPage:
        """The page of bars `request` asks for (`fefat_app.services.market_bars`)."""
        return bars_page(self.store, self.cache_folder, request)

    def start_sync(self, root: str | None) -> Job:
        """Queue the catalog sync of `root`, or of every product where it is None, which writes
        each of its quality reports as `fefat data quality` does, or give the queued or running
        sync that covers it, of `root` or of every product, not asked to stop, since two would
        write the same reports at once; `NothingToSyncError` where the store holds nothing to
        report, so that no job is queued to fail."""
        try:
            reported_products(self.store, root)
        except NothingToReportError as refused:
            raise NothingToSyncError(str(refused)) from refused
        for job in self.jobs.active(JobKind.CATALOG_SYNC):
            if job.cancel_requested_at is None and job.payload["root"] in (None, root):
                return job
        return self.jobs.start(JobKind.CATALOG_SYNC, {"root": root})


def dataset_id(provider: str, schema: str, root: str) -> str:
    """The id of a dataset: its provider, schema, and root, `provider:schema:root`."""
    return f"{provider}:{schema}:{root}"


def _held(store: Store, named: str) -> tuple[Dataset, DatasetCoverage]:
    """The dataset of trades, TBBO, or bars that `named`, its id, names, with its coverage;
    `NoSuchDatasetError` where the store holds none with a partition."""
    try:
        provider, schema, root = named.split(":")
        dataset = Dataset(provider=provider, schema_name=parse_schema_name(schema), root=root)
    except ValueError as malformed:
        raise NoSuchDatasetError(named) from malformed
    if dataset.schema_name.kind not in SESSION_KINDS or not store.has_dataset_metadata(dataset):
        raise NoSuchDatasetError(named)
    coverage = dataset_coverage(store, dataset)
    if coverage is None:
        raise NoSuchDatasetError(named)
    return dataset, coverage


def _dataset_fields(row: Mapping[str, Any]) -> dict[str, Any]:
    """A dataset's fields from its row of `fefat.market.status`, with its id."""
    fields = {name: row[name] for name in DATASET_COLUMNS.names() if name != "schema"}
    named = dataset_id(row["provider"], row["schema"], row["root"])
    return {"id": named, "schema_name": row["schema"], **fields}


def _stored(row: Mapping[str, Any]) -> StoredDataset:
    return StoredDataset.model_validate(_dataset_fields(row))


def _product(rows: pl.DataFrame) -> CatalogProductStatus:
    """A catalog product from its rows of `product_status`: a row that says it is missing, or a
    row for each dataset that covers it."""
    first = rows.row(0, named=True)
    covering = rows.filter(pl.col("coverage") != CoverageStatus.MISSING.value)
    return CatalogProductStatus(
        root=first["root"],
        history_from=first["history_from"],
        recommended_source=first["recommended_source"],
        datasets=tuple(
            CoveringDataset.model_validate({**_dataset_fields(row), "coverage": row["coverage"]})
            for row in covering.iter_rows(named=True)
        ),
    )


def _finding(row: Mapping[str, Any]) -> ReportedFinding:
    return ReportedFinding(
        trade_date=row["trade_date"],
        kind=row["kind"],
        schema_name=row["schema"],
        contract=row["contract"],
        count=row["count"],
    )


def _instrument_version(version: Instrument, saved: bool) -> InstrumentVersion:
    return InstrumentVersion(
        root=version.root,
        kind=version.kind,
        tick_size=float(version.tick_size),
        point_value=float(version.point_value),
        lot_step=float(version.lot_step),
        currency=version.currency,
        calendar=version.session_calendar().name,
        valid_from=version.valid_from,
        valid_to=version.valid_to,
        saved=saved,
    )
