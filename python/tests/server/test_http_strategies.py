"""The strategies' routes, step 5.2 (D-93): a strategy created and given a second version through
the API, each saved in the executor as a notebook saves it, and their diff (Done means 1); a
version with a syntax error refused with its line (Done means 2); the templates listed (Done
means 3); a version never changed through the API; a feature version never saved refused at its
line; and validation run in a runner, never in the server's process (the step's Prompt and If it
fails)."""

import os
from pathlib import Path

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

import fefat as ff
from fefat.config import resolve_paths
from fefat_app.container import Container
from fefat_app.database.models import StrategyVersionRow
from fefat_app.http import strategies
from fefat_app.http.problems import PROBLEM_MEDIA_TYPE
from local_server import logged_in
from strategy_code import BREAKOUT, HYPOTHESIS, WITH_A_SLOT

WIDER_STOP = BREAKOUT.replace("stop_atr: float = 1.5", "stop_atr: float = 2.0")
FIRST = {"name": "breakout", "code": BREAKOUT, "hypothesis": HYPOTHESIS, "changelog": "Guide's."}


def created(client: TestClient, csrf: dict[str, str]) -> str:
    """The id of the strategy `breakout`, created through the API with its first version."""
    response = client.post("/v1/strategies", json=FIRST, headers=csrf)
    assert response.status_code == 201, response.text
    return response.json()["strategy_id"]


def test_two_versions_are_created_and_diffed_through_the_api(
    client: TestClient, container: Container
) -> None:
    # Done means 1: through the API, and read by the SDK as a notebook reads it.
    csrf = logged_in(client, container)
    strategy_id = created(client, csrf)
    second = {"code": WIDER_STOP, "hypothesis": HYPOTHESIS, "changelog": "A wider stop."}

    saved = client.post(f"/v1/strategies/{strategy_id}/versions", json=second, headers=csrf)

    listed = client.get("/v1/strategies").json()
    versions = client.get(f"/v1/strategies/{strategy_id}/versions").json()
    read = client.get(f"/v1/strategies/{strategy_id}/versions/2").json()
    diff = client.get(f"/v1/strategies/{strategy_id}/diff", params={"from": 1, "to": 2})
    assert (saved.status_code, saved.json()["version"]) == (201, 2)
    assert [(each["name"], len(each["versions"])) for each in listed] == [("breakout", 2)]
    assert [(each["version"], each["changelog"]) for each in versions] == [
        (1, "Guide's."),
        (2, "A wider stop."),
    ]
    assert read == saved.json()
    assert (read["code"], read["hypothesis"], read["lint"]) == (WIDER_STOP, HYPOTHESIS, [])
    assert ff.strategy.load("breakout", 2).hash == read["hash"]
    assert diff.status_code == 200
    assert diff.json() == {
        "earlier": 1,
        "later": 2,
        "code_diff": ff.strategy.diff("breakout", 1, 2),
    }
    assert "+def strategy(lookback: int = 12, stop_atr: float = 2.0)" in diff.json()["code_diff"]


def test_a_version_with_a_syntax_error_is_refused_with_its_line(
    client: TestClient, container: Container
) -> None:
    # Done means 2: the line, for the editor of step 5.5 to underline.
    csrf = logged_in(client, container)
    broken = {**FIRST, "code": BREAKOUT.replace('pl.col("close")', 'pl.col("close") +')}

    refused = client.post("/v1/strategies", json=broken, headers=csrf)

    assert refused.status_code == 400
    assert refused.headers["content-type"] == PROBLEM_MEDIA_TYPE
    assert (refused.json()["line"], refused.json()["detail"]) == (7, "SyntaxError: invalid syntax")
    assert client.get("/v1/strategies").json() == []
    assert not resolve_paths(os.environ).strategies_dir.exists()


def test_the_templates_are_listed_with_their_code(client: TestClient, container: Container) -> None:
    # Done means 3, and the step's Prompt: the literal route resolves.
    logged_in(client, container)

    listed = client.get("/v1/strategies/templates")

    assert listed.status_code == 200
    assert listed.json() == [
        template.model_dump(mode="json") for template in ff.strategy.templates()
    ]
    assert [each["name"] for each in listed.json()] == [
        "breakout",
        "mean_reversion",
        "entry_window",
    ]


def test_every_literal_route_of_the_strategies_precedes_those_of_an_id() -> None:
    # The step's Prompt: a route `/strategies/{strategy_id}` declared before `templates` would
    # read "templates" as an id, since a router matches its routes in the order they were
    # declared, and the app keeps each router whole.
    paths = [route.path for route in strategies.router.routes if isinstance(route, APIRoute)]
    with_an_id = [index for index, path in enumerate(paths) if "{" in path]

    assert with_an_id
    assert {"/v1/strategies/templates", "/v1/strategies/validate"} <= set(paths[: with_an_id[0]])
    assert all("{" in path for path in paths[with_an_id[0] :])


def test_a_version_is_never_changed_through_the_api(
    client: TestClient, container: Container, engine: Engine
) -> None:
    # The step's Prompt: insert-only through the API. The same code with the same words is the
    # version already saved, other words are refused, and no route changes or deletes one.
    csrf = logged_in(client, container)
    strategy_id = created(client, csrf)
    file = resolve_paths(os.environ).strategies_dir / "breakout" / "v1.json"
    before = file.read_bytes()
    same = {"code": BREAKOUT, "hypothesis": HYPOTHESIS, "changelog": "Guide's."}
    reworded = {**same, "changelog": "Another word."}
    version = f"/v1/strategies/{strategy_id}/versions/1"

    again = client.post(f"/v1/strategies/{strategy_id}/versions", json=same, headers=csrf)
    other_words = client.post(f"/v1/strategies/{strategy_id}/versions", json=reworded, headers=csrf)
    changes = [
        client.put(version, json=same, headers=csrf),
        client.patch(version, json=same, headers=csrf),
        client.delete(version, headers=csrf),
    ]

    assert (again.status_code, again.json()["version"]) == (200, 1)
    assert other_words.status_code == 400
    assert "a version never changes" in other_words.json()["detail"]
    assert [response.status_code for response in changes] == [405, 405, 405]
    assert file.read_bytes() == before
    with Session(engine) as session:
        assert session.execute(select(func.count()).select_from(StrategyVersionRow)).scalar() == 1


def test_a_version_file_replaced_by_hand_is_refused_rather_than_served(
    client: TestClient, container: Container
) -> None:
    # The step review: a version deleted by hand and saved again from a notebook takes its number
    # with other code, which the index, kept insert-only, cannot follow (D-11).
    csrf = logged_in(client, container)
    strategy_id = created(client, csrf)
    (resolve_paths(os.environ).strategies_dir / "breakout" / "v1.json").unlink()
    ff.strategy.save("breakout", WIDER_STOP, hypothesis=HYPOTHESIS)
    second = {"code": WIDER_STOP, "hypothesis": HYPOTHESIS, "changelog": ""}

    answers = [
        client.get(f"/v1/strategies/{strategy_id}/versions/1"),
        client.get(f"/v1/strategies/{strategy_id}/diff", params={"from": 1, "to": 1}),
        client.post(f"/v1/strategies/{strategy_id}/versions", json=second, headers=csrf),
    ]

    assert [answer.status_code for answer in answers] == [409, 409, 409]
    assert all("by hand" in answer.json()["detail"] for answer in answers)


def test_the_lint_warns_through_the_api_and_the_version_is_saved(
    client: TestClient, container: Container
) -> None:
    # The lint warns and never refuses (D-95): its findings come back with a validation and with
    # the version saved.
    csrf = logged_in(client, container)
    reads_ahead = BREAKOUT.replace(".shift(1)", ".shift(-1)")

    validated = client.post("/v1/strategies/validate", json={"code": reads_ahead}, headers=csrf)
    saved = client.post("/v1/strategies", json={**FIRST, "code": reads_ahead}, headers=csrf)

    findings = [(each["rule"], each["line"]) for each in validated.json()["lint"]]
    assert findings == [("negative_shift", 12)]
    assert saved.status_code == 201
    assert saved.json()["lint"] == validated.json()["lint"]


def test_a_strategy_reading_a_feature_version_never_saved_is_refused_at_its_line(
    client: TestClient, container: Container
) -> None:
    # The step's Prompt: validation rejects a strategy that references a missing feature version.
    csrf = logged_in(client, container)
    reads_gap = WITH_A_SLOT.format(
        feature='ff.features.ref("gap", version=3)', entry='pl.col("read") > 0'
    )

    validated = client.post("/v1/strategies/validate", json={"code": reads_gap}, headers=csrf)

    assert validated.status_code == 200
    assert (validated.json()["verdict"], validated.json()["line"]) == ("refused", 10)
    assert "Expected version 3 of feature gap" in validated.json()["message"]


def test_validation_runs_in_a_runner_never_in_the_servers_process(
    client: TestClient, container: Container, tmp_path: Path
) -> None:
    # If it fails: the code runs in the executor's subprocess, which records its process here.
    csrf = logged_in(client, container)
    process = tmp_path / "process"
    code = f"import os\nfrom pathlib import Path\n\nPath({str(process)!r}).write_text(str(os.getpid()))\n"

    validated = client.post("/v1/strategies/validate", json={"code": code + BREAKOUT}, headers=csrf)

    assert validated.status_code == 200
    assert validated.json()["verdict"] == "valid"
    assert validated.json()["parameter_schema"]["properties"]["lookback"]["default"] == 12
    assert int(process.read_text()) != os.getpid()


def test_the_strategies_need_a_login_and_an_api_token_is_one(
    client: TestClient, container: Container
) -> None:
    bearer = {"Authorization": f"Bearer {container.api_tokens.create('notebook')}"}

    anonymous = [
        client.get("/v1/strategies"),
        client.get("/v1/strategies/templates"),
        client.post("/v1/strategies/validate", json={"code": BREAKOUT}),
        client.post("/v1/strategies", json=FIRST),
    ]
    with_a_token = client.get("/v1/strategies", headers=bearer)

    assert [response.status_code for response in anonymous] == [401] * 4
    assert (with_a_token.status_code, with_a_token.json()) == (200, [])


def test_a_strategy_a_notebook_saved_is_seen_by_the_api_before_a_create(
    client: TestClient, container: Container
) -> None:
    # The SDK and the app agree on what a version is: a save indexes the library first.
    csrf = logged_in(client, container)
    ff.strategy.save("breakout", BREAKOUT, hypothesis=HYPOTHESIS, changelog="From a notebook.")

    taken = client.post("/v1/strategies", json=FIRST, headers=csrf)

    listed = client.get("/v1/strategies").json()
    assert taken.status_code == 409
    assert "which a saved strategy has" in taken.json()["detail"]
    assert [(each["name"], each["versions"][0]["changelog"]) for each in listed] == [
        ("breakout", "From a notebook.")
    ]


def test_an_unknown_strategy_or_version_answers_404(
    client: TestClient, container: Container
) -> None:
    csrf = logged_in(client, container)
    strategy_id = created(client, csrf)

    unknown = [
        client.get("/v1/strategies/not-an-id/versions"),
        client.get(f"/v1/strategies/{strategy_id}/versions/2"),
        client.get(f"/v1/strategies/{strategy_id}/diff", params={"from": 1, "to": 2}),
    ]

    assert [response.status_code for response in unknown] == [404, 404, 404]
