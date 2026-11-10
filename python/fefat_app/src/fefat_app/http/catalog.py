"""The data catalog's routes (step 5.1, `01-architecture.md` section 7, D-93), behind the login,
a session's or an API token's, over `fefat_app.services.catalog`: `GET /v1/datasets`,
`GET /v1/datasets/{dataset_id}/quality`, `GET /v1/catalog`, `GET /v1/sources`,
`GET /v1/instruments`, and `GET /v1/market/bars`, each reading the store in the data folder as it
is asked."""

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query

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
from fefat_app.services.market_bars import (
    WINDOW_START,
    BarsPage,
    BarsRefusedError,
    BarsRequest,
    NoSuchInstrumentError,
)

router = APIRouter(prefix=API_PREFIX, tags=["data"], dependencies=[Depends(the_identity)])

TIMEFRAME = r"^[1-9][0-9]*[smhd]$"
"""A bar's timeframe: a count and a unit, such as `1s`, `5m`, `1h`, or `1d`."""


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


@router.get("/market/bars", responses=problem_responses(400, 401, 404, 422))
def market_bars(
    container: ContainerDependency,
    instrument: Annotated[
        str, Query(description="A root such as `ES`, or a contract such as `ESH2026`.")
    ],
    timeframe: Annotated[
        str, Query(pattern=TIMEFRAME, description="The bars' timeframe, such as `5m`.")
    ],
    start: Annotated[
        str,
        Query(
            alias="from",
            pattern=WINDOW_START,
            description="The trade date the window starts on, such as `2026-03-06`, or the "
            "instant a page opens at, a page's `next_from`, such as `2026-03-06T03:20:00Z`.",
        ),
    ],
    end: Annotated[date, Query(alias="to", description="The trade date the window ends on.")],
    continuous: Annotated[
        bool | None,
        Query(description="Whether a futures root's contracts are spliced, by default true."),
    ] = None,
    provider: Annotated[
        str | None,
        Query(
            description="The provider whose datasets the bars come from, by default the "
            "catalog's recommended source among those that hold the instrument."
        ),
    ] = None,
    origin: Annotated[
        Literal["import"] | None,
        Query(description="Only datasets of this origin; every dataset is an import for now."),
    ] = None,
) -> BarsPage:
    """A page of at most 20,000 of the instrument's bars on the trade dates from `from` to `to`,
    as `ff.market.load` gives them, column by column; `next_from` is the instant the next page
    opens at, to send as `from`, none on the last page. Refused with 404 for an instrument that
    names no root and no contract of one, and with 400, in the SDK's words, for a window it
    refuses, such as one a provider named does not hold."""
    request = BarsRequest(
        instrument=instrument,
        timeframe=timeframe,
        start=start,
        end=end,
        continuous=continuous,
        provider=provider,
        origin=origin,
    )
    try:
        return container.catalog.bars(request)
    except NoSuchInstrumentError as unknown:
        raise HTTPException(404, str(unknown)) from unknown
    except BarsRefusedError as refused:
        raise HTTPException(400, str(refused)) from refused
