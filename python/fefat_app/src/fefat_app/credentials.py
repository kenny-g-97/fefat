"""The credential store over keyring (step 4.1, `01-architecture.md` sections 8 and 10): each
secret under the service `fefat` and its name, in the Windows credential store on this machine,
the keychain on macOS, and the secret service on Linux, whichever keyring finds.

Where keyring finds no store it can use, its `fail` backend raises, and the store refuses with
the reason; nothing falls back to a file, so no secret lands on disk in plain text."""

from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Protocol

from keyring.errors import NoKeyringError, PasswordDeleteError

from fefat_app.ports import SecretName

SERVICE = "fefat"
"""The service keyring keeps FEFAT's secrets under."""


class KeyringBackendCalls(Protocol):
    """The calls the store makes of a keyring backend (`keyring.backend.KeyringBackend`), typed
    here since keyring's metaclass wraps `set_password` in a function without types."""

    def get_password(self, service: str, username: str, /) -> str | None: ...

    def set_password(self, service: str, username: str, password: str, /) -> None: ...

    def delete_password(self, service: str, username: str, /) -> None: ...


@dataclass(frozen=True)
class KeyringCredentialStore:
    """A `CredentialStore` over the keyring backend `backend`, which `fefat_app.container`
    chooses."""

    backend: KeyringBackendCalls

    def get(self, name: SecretName) -> str | None:
        """The secret `name`, or None where none is stored."""
        with _usable_store():
            return self.backend.get_password(SERVICE, name.value)

    def set(self, name: SecretName, value: str) -> None:
        """Store `value` as the secret `name`, refused when empty."""
        if not value:
            raise ValueError(f"Expected a value for the secret {name}, got an empty one.")
        with _usable_store():
            self.backend.set_password(SERVICE, name.value, value)

    def delete(self, name: SecretName) -> None:
        """Remove the secret `name`, refused where none is stored."""
        with _usable_store():
            try:
                self.backend.delete_password(SERVICE, name.value)
            except PasswordDeleteError as error:
                raise ValueError(
                    f"Expected the secret {name} in the credential store, got none to delete."
                ) from error


@contextmanager
def _usable_store() -> Generator[None]:
    """Refuse a machine where keyring finds no credential store it can use (module docstring)."""
    try:
        yield
    except NoKeyringError as error:
        raise ValueError(
            f"Expected a credential store that keyring can use on this machine, got none: {error}"
        ) from error
