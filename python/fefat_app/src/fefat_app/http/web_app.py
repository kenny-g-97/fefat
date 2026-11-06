"""The built web app at `/` (step 4.2, D-86): the files that `pnpm --dir web build` writes to
`web/dist` (step 4.3), and for any other path a GET or HEAD asks for, its `index.html`, so that
a reload on a page of the app finds the app; never a path under `/v1/`, which stays the API's,
and never a file outside the folder, which Starlette refuses."""

from pathlib import Path

from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
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
        if is_api_path(str(scope["path"])):
            raise HTTPException(status_code=404)
        try:
            return await super().get_response(path, scope)
        except HTTPException as missing:
            if missing.status_code != 404:
                raise
            return await super().get_response(INDEX, scope)
