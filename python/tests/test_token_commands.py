"""`fefat token create` of step 4.2 (D-86): an API token for a notebook or a script, printed once
under its name, which the API accepts as a bearer token; a name in use refused."""

import os

import pytest

from fefat.config import Settings, resolve_paths
from fefat_app.cli import main
from fefat_app.container import build_container
from fefat_app.database.schema import opened_database
from fefat_app.services.identity import ApiTokenIdentity


def test_token_create_prints_a_token_once_that_identifies_its_name(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = main(["token", "create", "notebook"])

    lines = capsys.readouterr().out.splitlines()
    with opened_database(resolve_paths(os.environ).database_file) as engine:
        identity = build_container(
            engine, Settings(), resolve_paths(os.environ)
        ).api_tokens.identity_of_token(lines[-1])
    assert code == 0
    assert lines[0] == "Created the API token notebook; copy it now, it is not shown again:"
    assert lines[-1].startswith("fefat_")
    assert identity == ApiTokenIdentity(token_name="notebook")


def test_a_token_name_in_use_is_refused(capsys: pytest.CaptureFixture[str]) -> None:
    main(["token", "create", "notebook"])
    capsys.readouterr()

    code = main(["token", "create", "notebook"])

    assert code == 1
    assert capsys.readouterr().err == (
        "fefat: Expected a new token name, got 'notebook', which a token has.\n"
    )


def test_token_revoke_refuses_the_token_from_then_on(capsys: pytest.CaptureFixture[str]) -> None:
    main(["token", "create", "notebook"])
    token = capsys.readouterr().out.splitlines()[-1]

    code = main(["token", "revoke", "notebook"])

    printed = capsys.readouterr().out
    paths = resolve_paths(os.environ)
    with opened_database(paths.database_file) as engine:
        identity = build_container(engine, Settings(), paths).api_tokens.identity_of_token(token)
    assert code == 0
    assert printed == "Revoked the API token notebook; a request that sends it is refused.\n"
    assert identity is None


def test_revoking_a_token_that_is_not_live_is_refused(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["token", "revoke", "notebook"])

    assert code == 1
    assert capsys.readouterr().err == (
        "fefat: Expected the name of a live API token, got 'notebook'.\n"
    )
