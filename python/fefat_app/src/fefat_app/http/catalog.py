"""The data catalog's routes (step 5.1, `01-architecture.md` section 7, D-93), behind the login,
a session's or an API token's, over `fefat_app.services.catalog`: `GET /v1/datasets`,
`GET /v1/datasets/{dataset_id}/quality`, `GET /v1/catalog`, `GET /v1/sources`, and
`GET /v1/instruments`, each reading the store in the data folder as it is asked."""

from fastapi import APIRouter, Depends, HTTPException

from fefat.market.sources import SourceGuide
from fefat_app.http.api_prefix import API_PREFIX
from fefat_app.http.dependencies import ContainerDependency, the_identity
from fefat_app.http.problems import problem_responses
from fefat_app.services.catalog import (
    CatalogStatus,
    DatasetQuality,
    InstrumentVersion,
    NoSuchDatasetError,
    StoredDataset,
)

router = APIRouter(prefix=API_PREFIX, tags=["data"], dependencies=[Depends(the_identity)])


@router.get("/datasets", responses=problem_responses(401))
def stored_datasets(container: ContainerDependency) -> tuple[StoredDataset, ...]:
    """Every dataset of trades, TBBO, or bars the store holds, by provider, root, and schema,
    with its trade dates, fidelity, and quality."""
    return container.catalog.datasets()


@router.get("/datasets/{dataset_id}/quality", responses=problem_responses(401, 404, 422))
def dataset_quality(dataset_id: str, container: ContainerDependency) -> DatasetQuality:
    """The quality of the dataset `dataset_id` names, `provider:schema:root` such as
    `databento:ohlcv-1m:MES`, with the findings of its root's report; refused with 404 where the
    store holds no such dataset."""
    try:
        return container.catalog.dataset_quality(dataset_id)
    except NoSuchDatasetError as refused:
        raise HTTPException(404, str(refused)) from refused


@router.get("/catalog", responses=problem_responses(401))
def catalog_status(container: ContainerDependency) -> CatalogStatus:
    """The products of the catalog, each with its history's first trade date, its first
    recommended source, and the datasets that cover it, complete or partial, none where it is
    missing; then the datasets of the roots the catalog does not list."""
    return container.catalog.catalog_status()


@router.get("/sources", responses=problem_responses(401))
def source_guide(container: ContainerDependency) -> SourceGuide:
    """The source guide: each source of market data with what it offers and costs, its terms
    and their page, whether a desktop app may use your own account or files, and the import
    presets that read its files."""
    return container.catalog.source_guide()


@router.get("/instruments", responses=problem_responses(401))
def instruments(container: ContainerDependency) -> tuple[InstrumentVersion, ...]:
    """Every version of every instrument's specification, FEAT's and those your imports saved,
    with its tick size, point value, lot step, currency, and session calendar."""
    return container.catalog.instruments()
