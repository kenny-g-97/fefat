"""`fefat token create` and `fefat token revoke`, the API tokens of notebooks and scripts (steps
4.2 and 4.3, D-86, `fefat_app.cli`):

    fefat token create <name>
    fefat token revoke <name>

`create` prints the token once, under its name, for a request to send as `Authorization: Bearer
<token>`. The app's database keeps only the token's SHA-256, so a lost token is replaced by a
new one under another name; `revoke` makes every request refuse it from then on."""

import argparse
import os

from fefat.config import resolve_paths
from fefat_app.container import opened_container

EXIT_OK = 0


def add_the_token_commands(token: argparse.ArgumentParser) -> None:
    """The subcommands of `fefat token` (module docstring)."""
    token_commands = token.add_subparsers(dest="token_command", required=True)
    creation = token_commands.add_parser("create", help="make an API token, printed once")
    creation.add_argument(
        "name",
        help="the token's name, such as notebook: letters, digits, dots, dashes, underscores",
    )
    creation.set_defaults(run=create_a_token)
    revocation = token_commands.add_parser("revoke", help="refuse an API token from now on")
    revocation.add_argument("name", help="the name of a live token")
    revocation.set_defaults(run=revoke_a_token)


def create_a_token(arguments: argparse.Namespace) -> int:
    name: str = arguments.name
    with opened_container(resolve_paths(os.environ)) as container:
        token = container.api_tokens.create(name)
    print(f"Created the API token {name}; copy it now, it is not shown again:")
    print(token)
    return EXIT_OK


def revoke_a_token(arguments: argparse.Namespace) -> int:
    name: str = arguments.name
    with opened_container(resolve_paths(os.environ)) as container:
        container.api_tokens.revoke(name)
    print(f"Revoked the API token {name}; a request that sends it is refused.")
    return EXIT_OK
