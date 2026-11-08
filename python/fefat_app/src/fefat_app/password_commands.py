"""`fefat password set`, the local server's password (step 4.2, D-86, `fefat_app.cli`):

    fefat password set

It reads the password twice at a prompt that does not echo it, keeps its Argon2 hash in the
app's database, and ends every login session; `fefat up` asks the same way on its first run."""

import argparse
import getpass
import os

from fefat.config import resolve_paths
from fefat_app.container import opened_container

EXIT_OK = 0


def add_the_password_commands(password: argparse.ArgumentParser) -> None:
    """The subcommands of `fefat password` (module docstring)."""
    password_commands = password.add_subparsers(dest="password_command", required=True)
    setting = password_commands.add_parser(
        "set", help="set the password, typed twice at a hidden prompt, ending every login session"
    )
    setting.set_defaults(run=set_the_password)


def set_the_password(arguments: argparse.Namespace) -> int:
    with opened_container(resolve_paths(os.environ)) as container:
        container.logins.set_password(typed_new_password())
    print("Set the password; every login session ended.")
    return EXIT_OK


def typed_new_password() -> str:
    """The password typed twice at a prompt that does not echo it; two that differ are refused."""
    password = getpass.getpass("New password for FEAT (not shown): ")
    if getpass.getpass("The same again: ") != password:
        raise ValueError("Expected the same password twice, got two that differ.")
    return password
