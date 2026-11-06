"""A keyring backend in memory, which the tests give `fefat_app.credentials` in place of the
machine's credential store (step 4.1). It declares no priority, so keyring's own search for a
backend never picks it."""

from keyring.backend import KeyringBackend
from keyring.errors import PasswordDeleteError


class MemoryKeyring(KeyringBackend):
    """Passwords by service and user name, in a dictionary."""

    def __init__(self) -> None:
        super().__init__()
        self.passwords: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.passwords.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.passwords[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        if (service, username) not in self.passwords:
            raise PasswordDeleteError(f"Expected a password of {username} for {service}, got none.")
        del self.passwords[(service, username)]
