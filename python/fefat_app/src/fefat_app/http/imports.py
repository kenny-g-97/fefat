"""`GET /v1/import-profiles`, `POST /v1/imports/preview`, and `POST /v1/imports` (step 5.12,
`01-architecture.md` section 7, D-93): the import wizard's profiles, the preview of a file's
table or of what its import would do, which the executor reads while the request waits, and the
import, an `import` job, over `fefat_app.services.imports`. A file is an upload's id or a path
under the import roots; refused with 404 for an upload or a profile that is not kept, 403 for a
path outside the roots, and 409 for a profile given under another profile's name or a saved
profile's file that no longer reads as one."""

from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException

from fefat_app.http.api_prefix import API_PREFIX
from fefat_app.http.dependencies import ContainerDependency, the_identity
from fefat_app.http.problems import problem_responses
from fefat_app.imports import (
    BatchImportAsked,
    FileImportAsked,
    ImportPreviewAnswer,
    ListedProfile,
    NoSuchUploadError,
    PathRefusedError,
    ProfileRefusedError,
    TableAsked,
)
from fefat_app.job_models import Job
from fefat_app.services.imports import NoSuchProfileError

router = APIRouter(prefix=API_PREFIX, tags=["imports"], dependencies=[Depends(the_identity)])
REFUSALS = problem_responses(401, 403, 404, 409, 422)
REFUSED = (NoSuchUploadError, NoSuchProfileError, PathRefusedError, ProfileRefusedError)
"""What a preview and an import refuse before anything runs, each with its status (`_refusal`)."""


@router.get("/import-profiles", responses=problem_responses(401, 409))
def import_profiles(container: ContainerDependency) -> tuple[ListedProfile, ...]:
    """The presets, then the profiles saved under `profiles/`; refused with 409 where a saved
    profile's file is not a profile, which the refusal names."""
    try:
        return container.imports.profiles()
    except ValueError as refused:
        raise HTTPException(409, str(refused)) from refused


@router.post("/imports/preview", responses=REFUSALS)
def preview_import(
    asked: Annotated[TableAsked | FileImportAsked | BatchImportAsked, Body(discriminator="kind")],
    container: ContainerDependency,
) -> ImportPreviewAnswer:
    """The file's table, or what its import would do, read by the executor and nothing
    written; a file the SDK refuses is answered as refused, with why."""
    try:
        return container.imports.preview(asked)
    except REFUSED as refused:
        raise _refusal(refused) from refused


@router.post("/imports", status_code=202, responses=REFUSALS)
def start_import(
    asked: Annotated[FileImportAsked | BatchImportAsked, Body(discriminator="kind")],
    container: ContainerDependency,
) -> Job:
    """Queue the import as an `import` job, its file and its profile checked first; its stages
    and its end come with the job's stream."""
    try:
        return container.imports.start(asked)
    except REFUSED as refused:
        raise _refusal(refused) from refused


def _refusal(refused: ValueError) -> HTTPException:
    if isinstance(refused, PathRefusedError):
        return HTTPException(403, str(refused))
    if isinstance(refused, ProfileRefusedError):
        return HTTPException(409, str(refused))
    return HTTPException(404, str(refused))
