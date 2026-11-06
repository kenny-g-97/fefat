"""`fefat secrets` of step 4.1: the API keys in the operating system's credential store, set at a
prompt that does not echo them, listed by name, deleted, and never printed; and Done means 3, a
secret that round-trips through keyring and lands in no file."""

import getpass
import os
from pathlib import Path
from uuid import uuid4

import keyring
import pytest

from fefat.config import resolve_paths
from fefat_app.cli import main
from memory_keyring import MemoryKeyring

REPOSITORY = Path(__file__).resolve().parents[2]
UNREAD_FOLDERS = {".git", ".venv", "target", "node_modules"}
"""The repository's folders of git objects, installed packages, and build outputs, which no
command of FEFAT writes into."""


@pytest.fixture
def backend(monkeypatch: pytest.MonkeyPatch) -> MemoryKeyring:
    """A keyring in memory in place of the machine's credential store."""
    memory = MemoryKeyring()
    monkeypatch.setattr(keyring, "get_keyring", lambda: memory)
    return memory


def typed(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    """`value` as what the trader types at the prompt that does not echo it."""
    monkeypatch.setattr(getpass, "getpass", lambda prompt: value)


def files_under(folder: Path) -> list[Path]:
    """Every file under `folder`, but those in `UNREAD_FOLDERS`."""
    found: list[Path] = []
    for root, folders, files in os.walk(folder):
        folders[:] = [name for name in folders if name not in UNREAD_FOLDERS]
        found.extend(Path(root) / name for name in files)
    return found


def test_set_stores_a_secret_typed_at_a_hidden_prompt_and_prints_its_name_alone(
    backend: MemoryKeyring, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    value = "fefat-test-secret-" + uuid4().hex
    typed(monkeypatch, value)

    code = main(["secrets", "set", "anthropic"])

    printed = capsys.readouterr()
    assert code == 0
    assert backend.passwords == {("fefat", "anthropic"): value}
    assert printed.out == "Stored anthropic in the credential store.\n"
    assert value not in printed.out + printed.err


def test_list_shows_each_name_as_set_or_not_set_and_no_value(
    backend: MemoryKeyring, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    typed(monkeypatch, "fefat-test-value")
    main(["secrets", "set", "anthropic"])
    capsys.readouterr()

    code = main(["secrets", "list"])

    assert code == 0
    assert capsys.readouterr().out == "anthropic: set\ndatabento: not set\n"


def test_delete_removes_a_secret_and_refuses_one_not_stored(
    backend: MemoryKeyring, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    typed(monkeypatch, "fefat-test-value")
    main(["secrets", "set", "anthropic"])

    deleted = main(["secrets", "delete", "anthropic"])
    again = main(["secrets", "delete", "anthropic"])

    printed = capsys.readouterr()
    assert (deleted, again) == (0, 1)
    assert backend.passwords == {}
    assert "Deleted anthropic from the credential store.\n" in printed.out
    assert printed.err == (
        "fefat: Expected the secret anthropic in the credential store, got none to delete.\n"
    )


def test_a_name_off_the_list_or_an_empty_value_is_refused(
    backend: MemoryKeyring, monkeypatch: pytest.MonkeyPatch
) -> None:
    typed(monkeypatch, "")

    with pytest.raises(SystemExit) as usage:
        main(["secrets", "set", "openai"])
    empty = main(["secrets", "set", "anthropic"])

    assert usage.value.code == 2
    assert empty == 1
    assert backend.passwords == {}


def test_a_secret_round_trips_through_keyring_and_lands_in_no_file(
    backend: MemoryKeyring, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Done means 3 (from `BACKLOG.md`): the value is found in the credential store alone, in no
    # file of the repository's folder, ignored ones included, and in none under FEFAT_HOME.
    home = resolve_paths(os.environ).home
    home.mkdir(parents=True)
    (home / "config.toml").write_text("port = 8765\n", encoding="utf-8")
    secret = "fefat-test-secret-" + uuid4().hex
    typed(monkeypatch, secret)

    stored = main(["secrets", "set", "anthropic"])
    listed = main(["secrets", "list"])

    files = files_under(REPOSITORY) + files_under(home)
    holding = [path for path in files if secret.encode() in path.read_bytes()]
    assert (stored, listed) == (0, 0)
    assert backend.passwords == {("fefat", "anthropic"): secret}
    assert secret not in capsys.readouterr().out
    assert len(files) > 100
    assert holding == []


def test_without_a_usable_credential_store_the_command_fails_and_writes_no_file(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The step's "If it fails": the conftest gives keyring its `fail` backend, as on a machine
    # without a credential store; the command is refused, and no file is written in its place.
    typed(monkeypatch, "fefat-test-value")

    code = main(["secrets", "set", "anthropic"])

    assert code == 1
    assert "Expected a credential store that keyring can use" in capsys.readouterr().err
    assert not resolve_paths(os.environ).home.exists()
