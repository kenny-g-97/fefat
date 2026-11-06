"""`fefat db`, the app's database `<FEFAT_HOME>/fefat.sqlite` (`fefat_app.database`, step 4.1):

    fefat db upgrade
    fefat db downgrade base

`upgrade` migrates the database to the latest schema, making the file where there is none, and
prints the revision it is at; `downgrade base` runs every migration down, which drops every
table but Alembic's own, as `alembic downgrade base` does with the migrations that ship inside
the package.
"""

import argparse
import os

from fefat.config import resolve_paths
from fefat_app.database.schema import empty_schema, opened_database, upgrade_schema

EXIT_OK = 0
BASE = "base"


def add_the_database_commands(database: argparse.ArgumentParser) -> None:
    """The subcommands of `fefat db` (module docstring)."""
    database_commands = database.add_subparsers(dest="database_command", required=True)
    upgrade = database_commands.add_parser(
        "upgrade", help="migrate the app's database to the latest schema, making it if needed"
    )
    upgrade.set_defaults(run=upgrade_the_database)
    downgrade = database_commands.add_parser(
        "downgrade", help="run every migration down, dropping the app's tables"
    )
    downgrade.add_argument("target", choices=[BASE], help="base, before the first migration")
    downgrade.set_defaults(run=downgrade_the_database)


def upgrade_the_database(arguments: argparse.Namespace) -> int:
    database_file = resolve_paths(os.environ).database_file
    with opened_database(database_file) as engine:
        revision = upgrade_schema(engine)
    print(f"Upgraded {database_file} to revision {revision}.")
    return EXIT_OK


def downgrade_the_database(arguments: argparse.Namespace) -> int:
    database_file = resolve_paths(os.environ).database_file
    with opened_database(database_file) as engine:
        empty_schema(engine)
    print(f"Downgraded {database_file} to base: no table remains but Alembic's own.")
    return EXIT_OK
