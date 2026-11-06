"""The built web app at `/` (step 4.2, D-86): the files that `pnpm --dir web build` writes to
`web/dist` (step 4.3), and for a page path a GET or HEAD asks for, one whose last part has no
dot, its `index.html`, so that a reload on a page of the app finds the app. The index is checked
again at each load, since a rebuild renames the scripts it names. A file that is not there, such
as a script of an older build, stays a 404; a path that Windows cannot name as a file counts as
one that is not there; a path under `/v1` is left to the API's routes, so that a wrong method on
one stays a 405; and Starlette refuses a file outside the folder."""

import os
from pathlib import Path, PurePosixPath

from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.routing import Match, Mount
from starlette.staticfiles import PathLike, StaticFiles
from starlette.types import Scope

from fefat_app.http.api_prefix import is_api_path

WEB_APP_DIR = Path(__file__).resolve().parents[5] / "web" / "dist"
"""Where a source checkout's web app is built."""
INDEX = "index.html"


def built_web_app_dir() -> Path | None:
    """`web/dist` where it holds a built web app, else None."""
    # shortcut: a source checkout's folder; Phase 14's installer ships the built app with the app.
    return WEB_APP_DIR if (WEB_APP_DIR / INDEX).is_file() else None


class BuiltWebApp(StaticFiles):
    """The files of a built web app, its `index.html` for every page path it does not hold."""

    def __init__(self, directory: Path) -> None:
        super().__init__(directory=directory, html=True)

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except OSError:
            missing = HTTPException(status_code=404)
        except HTTPException as refused:
            missing = refused
        if missing.status_code != 404 or "." in PurePosixPath(str(scope["path"])).name:
            raise missing
        return await super().get_response(INDEX, scope)

    def file_response(
        self, full_path: PathLike, stat_result: os.stat_result, scope: Scope, status_code: int = 200
    ) -> Response:
        response = super().file_response(full_path, stat_result, scope, status_code)
        if Path(full_path).name == INDEX:
            response.headers["Cache-Control"] = "no-cache"
        return response


class WebAppMount(Mount):
    """The built web app's mount at `/`, matching every path but the API's."""

    def __init__(self, directory: Path) -> None:
        super().__init__("/", app=BuiltWebApp(directory), name="web_app")

    def matches(self, scope: Scope) -> tuple[Match, Scope]:
        if scope["type"] == "http" and is_api_path(str(scope["path"])):
            return Match.NONE, {}
        return super().matches(scope)
