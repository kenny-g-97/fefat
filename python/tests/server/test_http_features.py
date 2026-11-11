"""The features' routes, step 5.2 (D-93), the strategies' mirror for the feature lab of Phase 6: a
feature created and given a second version through the API, each saved in the executor as
`ff.features.save` saves it, read back, and diffed; the same code answering its version; code
that defines another feature refused; and the routes behind the login."""

import os

from fastapi.testclient import TestClient

import fefat as ff
from fefat.config import resolve_paths
from fefat.features.versions import code_diff
from fefat_app.container import Container
from local_server import logged_in
from notebook_runs import features_of_cell

GAP = """\
@ff.feature(params={"n": 3}, warmup=lambda n: n, outputs={"gap": "price_distance"})
def gap(bars: pl.LazyFrame, n: int) -> pl.Expr:
    return pl.col("close") - pl.col("close").rolling_mean(n)
"""
"""A feature's code, as `ff.features.from_source` takes it."""
WIDER = GAP.replace('"n": 3', '"n": 5')


def test_two_versions_of_a_feature_are_created_and_diffed_through_the_api(
    client: TestClient, container: Container
) -> None:
    csrf = logged_in(client, container)
    created = client.post("/v1/features", json={"name": "gap", "code": GAP}, headers=csrf)
    feature_id = created.json()["feature_id"]

    second = client.post(f"/v1/features/{feature_id}/versions", json={"code": WIDER}, headers=csrf)
    again = client.post(f"/v1/features/{feature_id}/versions", json={"code": GAP}, headers=csrf)

    listed = client.get("/v1/features").json()
    first = client.get(f"/v1/features/{feature_id}/versions/1").json()
    diff = client.get(f"/v1/features/{feature_id}/diff", params={"from": 1, "to": 2}).json()
    assert (created.status_code, second.status_code, again.status_code) == (201, 201, 200)
    assert (second.json()["version"], again.json()["version"]) == (2, 1)
    assert [(each["name"], len(each["versions"])) for each in listed] == [("gap", 2)]
    assert first["code"] == GAP
    assert ff.features.load("gap", 2).hash == second.json()["hash"]
    assert diff == {
        "earlier": 1,
        "later": 2,
        "code_diff": code_diff(GAP, WIDER, ("gap v1", "gap v2")),
    }


def test_code_that_defines_another_feature_is_refused_and_a_taken_name_too(
    client: TestClient, container: Container
) -> None:
    csrf = logged_in(client, container)

    other = client.post("/v1/features", json={"name": "other", "code": GAP}, headers=csrf)
    ff.features.save(features_of_cell(GAP)["gap"])
    taken = client.post("/v1/features", json={"name": "gap", "code": GAP}, headers=csrf)

    assert other.status_code == 400
    assert (other.json()["line"], other.json()["detail"]) == (
        None,
        "Expected the code of feature other, got that of feature gap.",
    )
    assert taken.status_code == 409
    assert "which a saved feature has" in taken.json()["detail"]


def test_a_feature_version_file_replaced_by_hand_is_refused_rather_than_served(
    client: TestClient, container: Container
) -> None:
    # The step review: a version deleted by hand and saved again from a notebook takes its number
    # with other code, which the index, kept insert-only, cannot follow (D-11).
    csrf = logged_in(client, container)
    created = client.post("/v1/features", json={"name": "gap", "code": GAP}, headers=csrf)
    feature_id = created.json()["feature_id"]
    (resolve_paths(os.environ).features_dir / "gap" / "v1.json").unlink()
    ff.features.save(features_of_cell(WIDER)["gap"])

    answers = [
        client.get(f"/v1/features/{feature_id}/versions/1"),
        client.get(f"/v1/features/{feature_id}/diff", params={"from": 1, "to": 1}),
        client.post(f"/v1/features/{feature_id}/versions", json={"code": GAP}, headers=csrf),
    ]

    assert [answer.status_code for answer in answers] == [409, 409, 409]
    assert all("by hand" in answer.json()["detail"] for answer in answers)


def test_the_features_need_a_login_and_an_api_token_is_one(
    client: TestClient, container: Container
) -> None:
    bearer = {"Authorization": f"Bearer {container.api_tokens.create('notebook')}"}

    anonymous = [
        client.get("/v1/features"),
        client.post("/v1/features", json={"name": "gap", "code": GAP}),
    ]
    with_a_token = client.get("/v1/features", headers=bearer)

    assert [response.status_code for response in anonymous] == [401, 401]
    assert (with_a_token.status_code, with_a_token.json()) == (200, [])
