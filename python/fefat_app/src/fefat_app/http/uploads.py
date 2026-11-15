"""`POST /v1/uploads` (step 5.12, D-93, D-101): a file the import wizard chose, sent as the request's
body, `application/octet-stream`, with its name in the query, and kept in a folder of the
workspace's uploads until its import has written (`fefat_app.uploads`). The route declares no
body, so that FastAPI reads none before the login is checked: the bytes come from the request's
stream once `the_identity` has passed, each chunk written as it comes, within `config.toml`'s
`upload_megabytes` (`fefat_app.http.body_limits`). The server's log keeps a request's path alone,
never its query, so a file's name stays out of it."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from fefat_app.http.api_prefix import API_PREFIX
from fefat_app.http.dependencies import ContainerDependency, the_identity
from fefat_app.http.problems import problem_responses
from fefat_app.imports import UploadedFile, UploadRefusedError

UPLOAD_MEDIA_TYPE = "application/octet-stream"
UPLOADS_PATH = f"{API_PREFIX}/uploads"
NAME_CHARS = 255
"""The longest name the query takes; the name's own rule is shorter, in bytes
(`fefat_app.services.uploads`)."""

router = APIRouter(prefix=API_PREFIX, tags=["imports"], dependencies=[Depends(the_identity)])


@router.post(
    "/uploads",
    status_code=201,
    responses=problem_responses(400, 401, 403, 413, 415, 422),
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {UPLOAD_MEDIA_TYPE: {"schema": {"type": "string", "format": "binary"}}},
        }
    },
)
async def upload_file(
    request: Request,
    name: Annotated[str, Query(min_length=1, max_length=NAME_CHARS)],
    container: ContainerDependency,
) -> UploadedFile:
    """Keep the file the body holds under `name`, for the import wizard to preview and import.
    Refused with 415 for a body of another media type, 400 for a name the server does not keep
    or an empty file, and 413 for a file past `config.toml`'s `upload_megabytes`."""
    media_type = request.headers.get("content-type", "")
    if media_type.partition(";")[0].strip().lower() != UPLOAD_MEDIA_TYPE:
        raise HTTPException(
            415, f"Expected the file as {UPLOAD_MEDIA_TYPE}, got {media_type or 'no media type'}."
        )
    try:
        return await container.imports.keep_upload(name, request.stream())
    except UploadRefusedError as refused:
        raise HTTPException(400, str(refused)) from refused
