"""`GET`, `POST`, and `DELETE /v1/api-tokens` (step 4.3, from `BACKLOG.md`, D-86): the settings
page lists, makes, and revokes the API tokens of notebooks and scripts, as `fefat token` does,
over `fefat_app.services.api_tokens`. A login session alone manages them (`the_session`), and a
token is shown once, in the response that makes it."""

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field

from fefat_app.http.api_prefix import API_PREFIX
from fefat_app.http.dependencies import ContainerDependency, the_session
from fefat_app.http.problems import problem_responses
from fefat_app.ports import ApiToken, TokenNameInUseError
from fefat_app.services.api_tokens import TOKEN_NAME, NoSuchApiTokenError

router = APIRouter(prefix=API_PREFIX, tags=["api tokens"], dependencies=[Depends(the_session)])


class ApiTokenRequest(BaseModel):
    """The name of a new API token, such as `notebook`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(pattern=f"^{TOKEN_NAME.pattern}$")


class IssuedApiToken(BaseModel):
    """A new API token under its name, which this response alone carries."""

    model_config = ConfigDict(frozen=True)

    name: str
    token: str


@router.get("/api-tokens", responses=problem_responses(401, 403))
def live_api_tokens(container: ContainerDependency) -> tuple[ApiToken, ...]:
    """The API tokens not revoked, by when they were made, with when each was last used, never
    a token."""
    return container.api_tokens.live_tokens()


@router.post("/api-tokens", status_code=201, responses=problem_responses(401, 403, 409, 422))
def create_api_token(request: ApiTokenRequest, container: ContainerDependency) -> IssuedApiToken:
    """Make an API token, shown in this response alone; refused with 409 for a name a live
    token has, while a revoked token's name is free."""
    try:
        token = container.api_tokens.create(request.name)
    except TokenNameInUseError as refused:
        raise HTTPException(409, str(refused)) from refused
    return IssuedApiToken(name=request.name, token=token)


@router.delete(
    "/api-tokens/{name}", status_code=204, responses=problem_responses(401, 403, 404, 422)
)
def revoke_api_token(name: str, container: ContainerDependency) -> Response:
    """Revoke the live API token `name`, which every request refuses from then on; refused with
    404 where no live token has the name."""
    try:
        container.api_tokens.revoke(name)
    except NoSuchApiTokenError as refused:
        raise HTTPException(404, str(refused)) from refused
    return Response(status_code=204)
