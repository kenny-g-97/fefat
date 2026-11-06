"""`fefat secrets`, the API keys FEFAT keeps in the operating system's credential store
(`fefat_app.credentials`), whose values no command prints (`fefat_app.cli`):

    fefat secrets set <name>
    fefat secrets list
    fefat secrets delete <name>

`set` reads the value at a prompt that does not echo it, so that it never sits in a command
line or the shell's history, and stores it under its name, one of `SecretName`; `list` prints
each name with whether a value is stored; `delete` removes one, refused where none is stored.
"""

import argparse
import getpass

from fefat_app.container import build_container
from fefat_app.ports import SecretName

EXIT_OK = 0
NAMES = [name.value for name in SecretName]


def add_the_secret_commands(secrets: argparse.ArgumentParser) -> None:
    """The subcommands of `fefat secrets` (module docstring)."""
    secret_commands = secrets.add_subparsers(dest="secrets_command", required=True)
    store = secret_commands.add_parser("set", help="store a secret, typed at a hidden prompt")
    store.add_argument("name", choices=NAMES, help="the secret's name")
    store.set_defaults(run=store_a_secret)
    listing = secret_commands.add_parser(
        "list", help="list each secret's name and whether it is stored, never its value"
    )
    listing.set_defaults(run=list_the_secrets)
    removal = secret_commands.add_parser("delete", help="remove a stored secret")
    removal.add_argument("name", choices=NAMES, help="the secret's name")
    removal.set_defaults(run=delete_a_secret)


def store_a_secret(arguments: argparse.Namespace) -> int:
    name = SecretName(_name(arguments))
    value = getpass.getpass(f"Value of {name} (not shown): ")
    build_container().credentials.set(name, value)
    print(f"Stored {name} in the credential store.")
    return EXIT_OK


def list_the_secrets(arguments: argparse.Namespace) -> int:
    credentials = build_container().credentials
    for name in SecretName:
        stored = "not set" if credentials.get(name) is None else "set"
        print(f"{name}: {stored}")
    return EXIT_OK


def delete_a_secret(arguments: argparse.Namespace) -> int:
    name = SecretName(_name(arguments))
    build_container().credentials.delete(name)
    print(f"Deleted {name} from the credential store.")
    return EXIT_OK


def _name(arguments: argparse.Namespace) -> str:
    name: str = arguments.name
    return name
