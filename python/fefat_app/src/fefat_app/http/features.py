"""The features' routes (step 5.2, `01-architecture.md` section 7, D-93), the strategies' mirror,
behind the login, a session's or an API token's, over `fefat_app.services.features`:
`GET /v1/features`; `POST /v1/features` and `POST /v1/features/{feature_id}/versions`, which save
a version in the executor, 201 where they wrote one and the second 200 where the same content was
saved; and the versions, a version, and the diff of two."""

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from fefat_app.http.api_prefix import API_PREFIX
from fefat_app.http.dependencies import ContainerDependency, the_identity
from fefat_app.http.problems import CodeRefused, code_refusal_responses, problem_responses
from fefat_app.library import (
    IndexedFeature,
    IndexedVersion,
    LibraryRefusedError,
    Saved,
    VersionDiff,
)
from fefat_app.services.code_runs import CodeRefusedError
from fefat_app.services.features import (
    FeatureNameInUseError,
    NoSuchFeatureError,
    SavedFeatureVersion,
)

router = APIRouter(prefix=API_PREFIX, tags=["features"], dependencies=[Depends(the_identity)])

FeatureId = Annotated[str, Path(description="A feature's id in the index, a UUIDv7.")]
VersionNumber = Annotated[int, Path(ge=1, description="A version's number, from 1.")]
SAVED_BEFORE = {
    200: {
        "model": SavedFeatureVersion,
        "description": "The code was saved before: its version, unchanged.",
    }
}


class FeatureCode(BaseModel):
    """A feature's code: one function under its `@ff.feature(...)` call."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str


class NewFeature(FeatureCode):
    """A new feature: its name, the name of the function its code defines, and its first
    version's code."""

    name: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")


@router.get("/features", responses=problem_responses(401))
def saved_features(container: ContainerDependency) -> tuple[IndexedFeature, ...]:
    """The saved features by name, each with its versions in order."""
    return container.features.features()


@router.post("/features", status_code=201, responses=code_refusal_responses(401, 403, 409, 422))
def create_feature(
    request: NewFeature, response: Response, container: ContainerDependency
) -> SavedFeatureVersion:
    """Create the feature `name` with its first version, saved in the executor; refused with 400
    and the line of the code where it defines no feature, or another, and with 409 where a saved
    feature has the name or the library holds files the index cannot follow."""
    return _answered(lambda: container.features.create(request.name, request.code), response)


@router.get("/features/{feature_id}/versions", responses=problem_responses(401, 404, 422))
def feature_versions(
    feature_id: FeatureId, container: ContainerDependency
) -> tuple[IndexedVersion, ...]:
    """The versions of the feature, in order."""
    try:
        return container.features.versions(feature_id)
    except NoSuchFeatureError as unknown:
        raise HTTPException(404, str(unknown)) from unknown


@router.post(
    "/features/{feature_id}/versions",
    status_code=201,
    responses={**SAVED_BEFORE, **code_refusal_responses(401, 403, 404, 409, 422)},
)
def save_feature_version(
    feature_id: FeatureId,
    request: FeatureCode,
    response: Response,
    container: ContainerDependency,
) -> SavedFeatureVersion:
    """Save the next version of the feature in the executor, or answer the version of the same
    content."""
    return _answered(lambda: container.features.save(feature_id, request.code), response)


@router.get(
    "/features/{feature_id}/versions/{number}", responses=problem_responses(401, 404, 409, 422)
)
def feature_version(
    feature_id: FeatureId, number: VersionNumber, container: ContainerDependency
) -> SavedFeatureVersion:
    """Version `number` of the feature as its file keeps it."""
    try:
        return container.features.version(feature_id, number)
    except NoSuchFeatureError as unknown:
        raise HTTPException(404, str(unknown)) from unknown
    except LibraryRefusedError as refused:
        raise HTTPException(409, str(refused)) from refused


@router.get("/features/{feature_id}/diff", responses=problem_responses(401, 404, 409, 422))
def feature_diff(
    feature_id: FeatureId,
    container: ContainerDependency,
    earlier: Annotated[int, Query(alias="from", ge=1, description="The earlier version.")],
    later: Annotated[int, Query(alias="to", ge=1, description="The later version.")],
) -> VersionDiff:
    """The unified diff of the code of versions `from` and `to` of the feature."""
    try:
        return container.features.diff(feature_id, earlier, later)
    except NoSuchFeatureError as unknown:
        raise HTTPException(404, str(unknown)) from unknown
    except LibraryRefusedError as refused:
        raise HTTPException(409, str(refused)) from refused


def _answered(
    save: Callable[[], Saved[SavedFeatureVersion]], response: Response
) -> SavedFeatureVersion:
    """The version `save` gives, 200 where it found it saved; its refusals as problems."""
    try:
        saved = save()
    except CodeRefusedError as refused:
        raise CodeRefused(refused.line, str(refused)) from refused
    except NoSuchFeatureError as unknown:
        raise HTTPException(404, str(unknown)) from unknown
    except (FeatureNameInUseError, LibraryRefusedError) as refused:
        raise HTTPException(409, str(refused)) from refused
    if not saved.created:
        response.status_code = 200
    return saved.version
