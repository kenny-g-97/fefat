"""`GET` and `PUT /v1/settings` of steps 4.2 and 4.3 (D-86): the settings of `config.toml`, the
data folder, the theme, and whether each secret is stored, a secret written to the credential
store and never read back, `null` removing one, and the theme kept in the database."""

import os

from fastapi.testclient import TestClient
from sqlalchemy import Engine

from fefat.config import resolve_paths
from fefat_app.container import Container
from fefat_app.database.preferences import PreferenceRows
from fefat_app.ports import Theme
from local_server import logged_in
from memory_keyring import MemoryKeyring


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
