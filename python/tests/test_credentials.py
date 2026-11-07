"""The credential store of step 4.1 (`01-architecture.md` sections 8 and 10, D-27): the
`CredentialStore` port, its adapter over keyring, and the container that builds it once."""

import re
from pathlib import Path

import keyring
import pytest
from keyring.backends import fail, null

from fefat.config import Settings
from fefat_app.container import build_container, credential_store
from fefat_app.credentials import KeyringCredentialStore
from fefat_app.database.schema import opened_database
from fefat_app.ports import CredentialStore, SecretName
from memory_keyring import MemoryKeyring


def test_a_secret_round_trips_through_keyring_under_fefats_service() -> None:
    backend = MemoryKeyring()
    store = KeyringCredentialStore(backend)

    store.set(SecretName.ANTHROPIC, "first")
    store.set(SecretName.ANTHROPIC, "second")

    assert store.get(SecretName.ANTHROPIC) == "second"
    assert store.get(SecretName.DATABENTO) is None
    assert backend.passwords == {("fefat", "anthropic"): "second"}
    store.delete(SecretName.ANTHROPIC)
    assert store.get(SecretName.ANTHROPIC) is None


def test_deleting_a_secret_that_is_not_stored_is_refused() -> None:
    store = KeyringCredentialStore(MemoryKeyring())
    expected = "Expected the secret databento in the credential store, got none to delete."

    with pytest.raises(ValueError, match=re.escape(expected)):
        store.delete(SecretName.DATABENTO)


def test_an_empty_secret_is_refused() -> None:
    backend = MemoryKeyring()
    expected = "Expected a value for the secret anthropic, got an empty one."

    with pytest.raises(ValueError, match=re.escape(expected)):
        KeyringCredentialStore(backend).set(SecretName.ANTHROPIC, "")
    assert backend.passwords == {}


def test_a_machine_without_a_usable_credential_store_is_refused_loudly() -> None:
    # The step's "If it fails": keyring's `fail` backend raises, and nothing falls back to a file.
    store = KeyringCredentialStore(fail.Keyring())
    expected = "Expected a credential store that keyring can use on this machine, got none"

    with pytest.raises(ValueError, match=re.escape(expected)):
        store.set(SecretName.ANTHROPIC, "a value")
    with pytest.raises(ValueError, match=re.escape(expected)):
        store.get(SecretName.ANTHROPIC)
    with pytest.raises(ValueError, match=re.escape(expected)):
        store.delete(SecretName.ANTHROPIC)


def test_a_backend_that_keeps_nothing_is_refused() -> None:
    # Keyring's `null` backend, which a PYTHON_KEYRING_BACKEND set for other tools may choose,
    # accepts every secret and keeps none.
    store = KeyringCredentialStore(null.Keyring())
    expected = (
        "Expected the credential store to give back the secret anthropic it was given, got "
        "nothing from keyring's backend keyring.backends.null"
    )

    with pytest.raises(ValueError, match=re.escape(expected)):
        store.set(SecretName.ANTHROPIC, "a value")
    with pytest.raises(ValueError, match="got none to delete"):
        store.delete(SecretName.ANTHROPIC)


def test_the_container_builds_the_store_over_the_keyring_of_this_machine(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    backend = MemoryKeyring()
    monkeypatch.setattr(keyring, "get_keyring", lambda: backend)

    with opened_database(tmp_path / "fefat.sqlite") as engine:
        credentials: CredentialStore = build_container(engine, Settings()).credentials
    credentials.set(SecretName.ANTHROPIC, "a value")

    assert backend.passwords == {("fefat", "anthropic"): "a value"}


def test_the_tests_reach_no_credential_store_of_their_machine() -> None:
    # The conftest points keyring at its `fail` backend, so that a test that gives keyring no
    # backend of its own is refused rather than writing to the machine's credential store.
    with pytest.raises(ValueError, match="got none"):
        credential_store().get(SecretName.ANTHROPIC)
