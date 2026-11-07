"""The API's OpenAPI document (step 4.2, D-86, `01-architecture.md` section 7), which `just gen-api`
writes to `web/openapi.json` before openapi-typescript writes the web app's types from it. It
is built without a container, so writing it opens no database:

    uv run python -m fefat_app.http.openapi_document web/openapi.json

Its keys are sorted, so that the file is the same wherever it is written."""

import json
import sys
from pathlib import Path
from typing import Any

from fefat_app.http.app import build_api

EXIT_OK = 0
EXIT_USAGE = 2


def openapi_document() -> dict[str, Any]:
    """The API's OpenAPI document."""
    return build_api().openapi()


def write_openapi_document(path: Path) -> None:
    """Write the document to `path` as JSON, with LF line endings."""
    text = json.dumps(openapi_document(), indent=2, sort_keys=True) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")


def main(arguments: list[str]) -> int:
    if len(arguments) != 1:
        print("Usage: python -m fefat_app.http.openapi_document <file>", file=sys.stderr)
        return EXIT_USAGE
    write_openapi_document(Path(arguments[0]))
    print(f"Wrote the API's OpenAPI document to {arguments[0]}.")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
