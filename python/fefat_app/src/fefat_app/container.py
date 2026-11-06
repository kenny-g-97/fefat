"""The adapters behind the app's ports, built once (`08-code-design.md` section 1, D-27):
`build_container` chooses each port's adapter, and the commands and, from step 4.2, the
server pass them on, so that nothing builds an adapter inside itself."""

from dataclasses import dataclass

import keyring

from fefat_app.credentials import KeyringCredentialStore
from fefat_app.ports import CredentialStore


@dataclass(frozen=True)
class Container:
    """The adapters of this machine, one for each port of `fefat_app.ports`."""

    credentials: CredentialStore


def build_container() -> Container:
    """The adapters of this machine: the credential store over the keyring backend that keyring
    finds, the Windows credential store here (`fefat_app.credentials`)."""
    return Container(credentials=KeyringCredentialStore(keyring.get_keyring()))
