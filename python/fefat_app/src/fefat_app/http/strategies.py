"""The strategies' routes (step 5.2, `01-architecture.md` section 7, D-93), behind the login, a
session's or an API token's, over `fefat_app.services.strategies`: `GET /v1/strategies` and the
templates, `POST /v1/strategies/validate`, which builds the code in the executor and answers its
verdict, `POST /v1/strategies` and `POST /v1/strategies/{strategy_id}/versions`, which save a
version in the executor, 201 where they wrote one and 200 where the same code was saved with the
same words, and the versions, a version, and the diff of two. The literal routes come before
those of a strategy's id, so that no id is read from `templates` or `validate`."""

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from fefat.strategy.starting_points import StrategyTemplate
from fefat.strategy.versions import STRATEGY_NAME
from fefat_app.execution import RefusedCode, ValidStrategy
from fefat_app.http.api_prefix import API_PREFIX
from fefat_app.http.dependencies import ContainerDependency, the_identity
from fefat_app.http.problems import CodeRefused, code_refusal_responses, problem_responses
from fefat_app.library import (
    IndexedStrategy,
    IndexedStrategyVersion,
    LibraryRefusedError,
    Saved,
    VersionDiff,
)
from fefat_app.services.code_runs import CodeRefusedError
from fefat_app.services.strategies import (
    NewStrategyVersion,
    NoSuchStrategyError,
    SavedStrategyVersion,
    StrategyNameInUseError,
)

router = APIRouter(prefix=API_PREFIX, tags=["strategies"], dependencies=[Depends(the_identity)])

StrategyId = Annotated[str, Path(description="A strategy's id in the index, a UUIDv7.")]
VersionNumber = Annotated[int, Path(ge=1, description="A version's number, from 1.")]
SAVED_BEFORE = {
    200: {
        "model": SavedStrategyVersion,
        "description": "The code was saved before with the same words: its version, unchanged.",
    }
}


class StrategyCode(BaseModel):
    """A strategy's code, a module whose function `strategy` gives the `SignalStrategy`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str


class NewStrategyVersionRequest(StrategyCode):
    """A version to save: its code, its hypothesis, one sentence on one line stating the edge,
    and its changelog."""

    hypothesis: str
    changelog: str = ""


class NewStrategy(NewStrategyVersionRequest):
    """A new strategy: its name, a lower-case identifier of at most 64 characters, and its first
    version."""

    name: str = Field(pattern=STRATEGY_NAME)


@router.get("/strategies", responses=problem_responses(401))
def saved_strategies(container: ContainerDependency) -> tuple[IndexedStrategy, ...]:
    """The saved strategies by name, each with its versions in order."""
    return container.strategies.strategies()


@router.get("/strategies/templates", responses=problem_responses(401))
def strategy_templates(container: ContainerDependency) -> tuple[StrategyTemplate, ...]:
    """The strategies to start from, each with its hypothesis and its code: the engine guide's
    breakout, a mean reversion reading the RSI, and a breakout in an entry window."""
    return container.strategies.templates()


@router.post("/strategies/validate", responses=problem_responses(401, 403, 422))
def validate_strategy(
    request: StrategyCode, container: ContainerDependency
) -> Annotated[ValidStrategy | RefusedCode, Field(discriminator="verdict")]:
    """Build the code in the executor as a version's is, with its signal frame on bars that hold
    no rows: `valid`, with the instrument and the timeframe it names, its parameters' schema,
    and the lint's findings, or `refused`, with the line of the code the refusal is at."""
    return container.strategies.validate(request.code)


@router.post(
    "/strategies",
    status_code=201,
    responses={**SAVED_BEFORE, **code_refusal_responses(401, 403, 409, 422)},
)
def create_strategy(
    request: NewStrategy, response: Response, container: ContainerDependency
) -> SavedStrategyVersion:
    """Create the strategy `name` with its first version, saved in the executor; refused with
    400 and the line of the code where the code gives no strategy, and with 409 where a saved
    strategy has the name or the library holds files the index cannot follow."""
    first = NewStrategyVersion(
        code=request.code, hypothesis=request.hypothesis, changelog=request.changelog
    )
    return _answered(lambda: container.strategies.create(request.name, first), response)


@router.get("/strategies/{strategy_id}/versions", responses=problem_responses(401, 404, 422))
def strategy_versions(
    strategy_id: StrategyId, container: ContainerDependency
) -> tuple[IndexedStrategyVersion, ...]:
    """The versions of the strategy, in order, with their hypotheses and changelogs."""
    try:
        return container.strategies.versions(strategy_id)
    except NoSuchStrategyError as unknown:
        raise HTTPException(404, str(unknown)) from unknown


@router.post(
    "/strategies/{strategy_id}/versions",
    status_code=201,
    responses={**SAVED_BEFORE, **code_refusal_responses(401, 403, 404, 409, 422)},
)
def save_strategy_version(
    strategy_id: StrategyId,
    request: NewStrategyVersionRequest,
    response: Response,
    container: ContainerDependency,
) -> SavedStrategyVersion:
    """Save the next version of the strategy in the executor, or answer the version of the same
    code saved with the same words; the same code with other words is refused with 400, since a
    version never changes."""
    new = NewStrategyVersion(
        code=request.code, hypothesis=request.hypothesis, changelog=request.changelog
    )
    return _answered(lambda: container.strategies.save(strategy_id, new), response)


@router.get(
    "/strategies/{strategy_id}/versions/{number}",
    responses=problem_responses(401, 404, 409, 422),
)
def strategy_version(
    strategy_id: StrategyId, number: VersionNumber, container: ContainerDependency
) -> SavedStrategyVersion:
    """Version `number` of the strategy as its file keeps it, with the lint's findings in its
    code."""
    try:
        return container.strategies.version(strategy_id, number)
    except NoSuchStrategyError as unknown:
        raise HTTPException(404, str(unknown)) from unknown
    except LibraryRefusedError as refused:
        raise HTTPException(409, str(refused)) from refused


@router.get("/strategies/{strategy_id}/diff", responses=problem_responses(401, 404, 409, 422))
def strategy_diff(
    strategy_id: StrategyId,
    container: ContainerDependency,
    earlier: Annotated[int, Query(alias="from", ge=1, description="The earlier version.")],
    later: Annotated[int, Query(alias="to", ge=1, description="The later version.")],
) -> VersionDiff:
    """The unified diff of the code of versions `from` and `to` of the strategy."""
    try:
        return container.strategies.diff(strategy_id, earlier, later)
    except NoSuchStrategyError as unknown:
        raise HTTPException(404, str(unknown)) from unknown
    except LibraryRefusedError as refused:
        raise HTTPException(409, str(refused)) from refused


def _answered(
    save: Callable[[], Saved[SavedStrategyVersion]], response: Response
) -> SavedStrategyVersion:
    """The version `save` gives, 200 where it found it saved; its refusals as problems."""
    try:
        saved = save()
    except CodeRefusedError as refused:
        raise CodeRefused(refused.line, str(refused)) from refused
    except NoSuchStrategyError as unknown:
        raise HTTPException(404, str(unknown)) from unknown
    except (StrategyNameInUseError, LibraryRefusedError) as refused:
        raise HTTPException(409, str(refused)) from refused
    if not saved.created:
        response.status_code = 200
    return saved.version
