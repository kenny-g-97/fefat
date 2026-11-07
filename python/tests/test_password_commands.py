"""`fefat password set` of step 4.2 (D-86): the password typed twice at a prompt that does not echo
it replaces the one set, and every login session ends."""

import getpass
import os
import re

import pytest

from fefat.config import Settings, resolve_paths
from fefat_app.cli import main
from fefat_app.container import build_container
from fefat_app.database.schema import opened_database
from fefat_app.services.logins import WrongPasswordError

PASSWORD = "horse battery"
NEW_PASSWORD = "staple correct"


def typed(monkeypatch: pytest.MonkeyPatch, *answers: str) -> None:
    remaining = iter(answers)
    monkeypatch.setattr(getpass, "getpass", lambda prompt: next(remaining))


def test_password_set_replaces_the_password_and_ends_every_session(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    database_file = resolve_paths(os.environ).database_file
    typed(monkeypatch, PASSWORD, PASSWORD, NEW_PASSWORD, NEW_PASSWORD)
    main(["password", "set"])
    with opened_database(database_file) as engine:
        token = build_container(engine, Settings()).logins.login(PASSWORD).token

    code = main(["password", "set"])

    with opened_database(database_file) as engine:
        logins = build_container(engine, Settings()).logins
        ended = logins.identity_of_session(token.get_secret_value())
        with pytest.raises(WrongPasswordError):
            logins.login(PASSWORD)
        logins.login(NEW_PASSWORD)
    assert (code, ended) == (0, None)
    assert capsys.readouterr().out == "Set the password; every login session ended.\n" * 2


def test_a_password_too_short_is_refused(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    typed(monkeypatch, "short", "short")

    code = main(["password", "set"])

    assert code == 1
    assert re.fullmatch(
        r"fefat: Expected a password of 8 to 1024 characters, got 5\.\n", capsys.readouterr().err
    )
