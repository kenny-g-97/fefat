"""`fefat data delete`, the command that deletes a provider's data of a root from the store in
`FEFAT_DATA_DIR` (step 5.18, ADR-0023, `fefat_app.cli`):

    fefat data delete <provider> <root> [--yes]

It prints what a delete removes, as `fefat.market.stored_deletion` plans it, and how many saved
runs read the data, which keep their records and results but can no longer be explained or
checked again; it deletes only with `--yes`. A delete held up by a file that another program holds
open is finished by running the command again once it is closed. The command does not see the
app's jobs: let a job of the app that reads the data end before deleting it from a terminal.
"""

import argparse
import os

from fefat.backtest.saved_runs import runs_that_read
from fefat.config import resolve_paths
from fefat.market.calendar import counted
from fefat.market.store import Store
from fefat.market.stored_deletion import delete_stored_data, planned_deletion

EXIT_OK = 0


def add_the_delete_command(delete: argparse.ArgumentParser) -> None:
    """The arguments of `fefat data delete` (module docstring)."""
    delete.add_argument(
        "provider",
        help="the provider the data came from, as `fefat data catalog` lists it, such as "
        "ninjatrader",
    )
    delete.add_argument("root", help="the product, such as ES")
    delete.add_argument(
        "--yes",
        action="store_true",
        help="delete the data; without it, print what a delete would remove and delete nothing",
    )
    delete.set_defaults(run=delete_a_provider_s_data)


def delete_a_provider_s_data(arguments: argparse.Namespace) -> int:
    """Print what a delete of the provider's data of the root removes, and the saved runs that
    read it, and delete it where `--yes` says to."""
    paths = resolve_paths(os.environ)
    store = Store(paths.data_dir)
    provider: str = arguments.provider
    root: str = arguments.root
    confirmed: bool = arguments.yes
    runs = len(runs_that_read(paths.runs_dir, provider, root))
    remove = delete_stored_data if confirmed else planned_deletion
    deletion = remove(store, paths.reports_dir, paths.cache_dir, provider, root)
    print(deletion.summary())
    print(_runs_line(runs))
    print(
        f"Deleted {root} from {provider}."
        if confirmed
        else "Nothing was deleted: run the command again with --yes to delete it."
    )
    return EXIT_OK


def _runs_line(runs: int) -> str:
    if runs == 0:
        return "No saved run read this data."
    keeps = "it keeps its record" if runs == 1 else "they keep their records"
    return (
        f"{counted(runs, 'saved run')} read this data: {keeps} and results, but can no longer be "
        "explained or checked again."
    )
