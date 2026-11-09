"""The OpenAPI document of step 4.2 (D-86, `01-architecture.md` section 7): `just gen-api` writes
it to `web/openapi.json`, from which openapi-typescript writes the web app's types, and this
test, like CI's drift check, fails while the committed copy differs (Done means 3)."""

import json
from pathlib import Path

from fefat_app.http.openapi_document import openapi_document, write_openapi_document

REPOSITORY = Path(__file__).resolve().parents[3]


def test_the_committed_document_is_the_one_the_api_describes() -> None:
    # Done means 3: the schema `just gen-api` writes.
    committed = json.loads((REPOSITORY / "web" / "openapi.json").read_text(encoding="utf-8"))

    assert committed == openapi_document(), (
        "web/openapi.json differs from the API's document: run `just gen-api` and commit "
        "web/openapi.json and web/src/api/schema.d.ts"
    )


def test_the_document_is_written_whole_with_lf_line_endings(tmp_path: Path) -> None:
    written = tmp_path / "openapi.json"

    write_openapi_document(written)

    raw = written.read_bytes()
    assert bytes([13]) not in raw
    assert raw.endswith(b"}\n")
    assert json.loads(raw) == openapi_document()


def test_errors_are_documented_as_problem_json_and_the_docs_stay_out() -> None:
    document = openapi_document()

    login = document["paths"]["/v1/auth/login"]["post"]["responses"]
    assert {status: list(login[status]["content"]) for status in ("401", "422", "429")} == {
        "401": ["application/problem+json"],
        "422": ["application/problem+json"],
        "429": ["application/problem+json"],
    }
    assert "HTTPValidationError" not in document["components"]["schemas"]
    assert {"/docs", "/openapi.json"}.isdisjoint(document["paths"])


def test_every_error_of_every_route_is_documented_as_problem_json() -> None:
    # Step 4.4: an event stream's refusals too, which FastAPI files under its stream's media type.
    document = openapi_document()

    filed = {
        f"{method} {path} {status}": list(response["content"])
        for path, path_item in document["paths"].items()
        for method, operation in path_item.items()
        for status, response in operation["responses"].items()
        if status[0] in "45" and "content" in response
    }

    assert filed
    assert {
        route for route, media in filed.items() if media != ["application/problem+json"]
    } == set()
