"""`GET` and `PUT /v1/settings` of steps 4.2 and 4.3 (D-86): the settings of `config.toml`, the
data folder, the theme, and whether each secret is stored, a secret written to the credential
store and never read back, `null` removing one, and the theme kept in the database."""

import os

from fastapi.testclient import TestClient
from sqlalchemy import Engine

from fefat.config import resolve_paths
from fefat_app.chart_style import ChartStyle
from fefat_app.container import Container
from fefat_app.database.preferences import PreferenceRows
from fefat_app.ports import Theme
from local_server import logged_in
from memory_keyring import MemoryKeyring

THEMES_OWN = {"up": None, "down": None, "background": None, "grid": None, "text": None}
FEATS_CHART_STYLE = {
    "up_body": "hollow",
    "down_body": "hollow",
    "volume_shown": True,
    "volume_colouring": "neutral",
    "grid_shown": True,
    "sessions_shaded": True,
    "dark": THEMES_OWN,
    "light": THEMES_OWN,
}
"""Step 5.4, the builder's answers: hollow candles in the theme's sign colours, green up and red
down, with the volume pane, the grid, and the sessions' shading shown."""


def test_the_settings_show_config_toml_and_whether_each_secret_is_stored(
    client: TestClient, container: Container, keyring_backend: MemoryKeyring
) -> None:
    logged_in(client, container)
    keyring_backend.set_password("fefat", "databento", "a stored key")

    response = client.get("/v1/settings")

    assert response.json() == {
        "server": {
            "port": 8765,
            "bind_address": "127.0.0.1",
            "process_pool_size": container.settings.process_pool_size,
            "import_roots": [],
        },
        "data_dir": str(resolve_paths(os.environ).data_dir),
        "theme": "dark",
        "chart_style": FEATS_CHART_STYLE,
        "secrets": [
            {"name": "anthropic", "state": "missing"},
            {"name": "databento", "state": "stored"},
        ],
    }
    assert "a stored key" not in response.text


def test_the_theme_is_dark_until_the_trader_chooses_light_which_the_database_keeps(
    client: TestClient, container: Container, engine: Engine
) -> None:
    csrf = logged_in(client, container)

    changed = client.put("/v1/settings", json={"theme": "light"}, headers=csrf)
    unchanged = client.put("/v1/settings", json={}, headers=csrf)
    sepia = client.put("/v1/settings", json={"theme": "sepia"}, headers=csrf)

    assert changed.json()["theme"] == "light"
    assert unchanged.json()["theme"] == "light"
    assert sepia.status_code == 422
    assert PreferenceRows(engine).theme() is Theme.LIGHT


def test_the_chart_style_is_feats_until_the_trader_changes_it_which_the_database_keeps(
    client: TestClient, container: Container, engine: Engine
) -> None:
    # Step 5.4: the chart style drawer keeps the trader's style for every chart and browser.
    csrf = logged_in(client, container)
    chosen = {
        **FEATS_CHART_STYLE,
        "up_body": "filled",
        "volume_colouring": "direction",
        "sessions_shaded": False,
        "dark": {**THEMES_OWN, "up": "#26a69a", "background": "#000000"},
    }

    changed = client.put("/v1/settings", json={"chart_style": chosen}, headers=csrf)
    unchanged = client.put("/v1/settings", json={"theme": "light"}, headers=csrf)

    assert changed.json()["chart_style"] == chosen
    assert changed.json()["theme"] == "dark"
    assert unchanged.json()["chart_style"] == chosen
    assert client.get("/v1/settings").json()["chart_style"] == chosen
    assert PreferenceRows(engine).chart_style() == ChartStyle.model_validate(chosen)


def test_a_chart_style_with_a_colour_of_another_form_or_an_unknown_field_is_refused(
    client: TestClient, container: Container, engine: Engine
) -> None:
    csrf = logged_in(client, container)
    refusals = [
        {**FEATS_CHART_STYLE, "dark": {**THEMES_OWN, "up": "#26a69"}},
        {**FEATS_CHART_STYLE, "light": {**THEMES_OWN, "grid": "#26A69A"}},
        {**FEATS_CHART_STYLE, "light": {**THEMES_OWN, "grid": "teal"}},
        {**FEATS_CHART_STYLE, "wick_colour": "#ffffff"},
        {**FEATS_CHART_STYLE, "up_body": "outlined"},
    ]

    answers = [
        client.put("/v1/settings", json={"chart_style": style}, headers=csrf).status_code
        for style in refusals
    ]

    assert answers == [422] * len(refusals)
    assert PreferenceRows(engine).chart_style() == ChartStyle()


def test_a_secret_is_written_to_the_credential_store_and_null_removes_it(
    client: TestClient, container: Container, keyring_backend: MemoryKeyring
) -> None:
    csrf = logged_in(client, container)

    stored = client.put("/v1/settings", json={"secrets": {"anthropic": "first key"}}, headers=csrf)
    kept = dict(keyring_backend.passwords)
    removed = client.put("/v1/settings", json={"secrets": {"anthropic": None}}, headers=csrf)
    again = client.put("/v1/settings", json={"secrets": {"anthropic": None}}, headers=csrf)

    assert kept == {("fefat", "anthropic"): "first key"}
    assert stored.json()["secrets"][0] == {"name": "anthropic", "state": "stored"}
    assert "first key" not in stored.text
    assert keyring_backend.passwords == {}
    assert removed.json()["secrets"][0] == {"name": "anthropic", "state": "missing"}
    assert again.status_code == 200


def test_an_empty_secret_and_an_unknown_name_are_refused(
    client: TestClient, container: Container, keyring_backend: MemoryKeyring
) -> None:
    csrf = logged_in(client, container)

    empty = client.put("/v1/settings", json={"secrets": {"anthropic": ""}}, headers=csrf)
    unknown = client.put("/v1/settings", json={"secrets": {"openai": "a key"}}, headers=csrf)

    assert (empty.status_code, unknown.status_code) == (422, 422)
    assert keyring_backend.passwords == {}
