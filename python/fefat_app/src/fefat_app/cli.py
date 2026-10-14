"""The `fefat` command, what a trader runs in a terminal:

    fefat data import databento <folder-or-file>
    fefat data verify-bars <root> <trade-date>

The first imports a Databento batch download, or a single DBN file, into the store in
`FEFAT_DATA_DIR` (`fefat.config.resolve_paths`) and prints what it imported; the second
rebuilds a trade date's bars from the finer data in the store and prints how they compare with
the stored ones (`fefat.market.bars_check`). A command exits with 0 when it succeeds, and with 1
and the reason when it refuses its input; `verify-bars` also exits with 1 when it finds bars
that differ. A command line that names no command, or a date that is no date, exits with 2 and
the usage, as `argparse` does.
"""

import argparse
import os
import sys
from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path

from fefat.config import resolve_paths
from fefat.market.bars_check import verify_bars
from fefat.market.importers.databento import import_databento
from fefat.market.store import Store

EXIT_OK = 0
EXIT_REFUSED = 1


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command `argv` names (the process's arguments when `None`) and return its exit
    code."""
    arguments = build_parser().parse_args(argv)
    command: Callable[[argparse.Namespace], int] = arguments.run
    try:
        return command(arguments)
    except (ValueError, FileNotFoundError) as error:
        print(f"fefat: {error}", file=sys.stderr)
        return EXIT_REFUSED


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fefat", description="FEFAT: feature engineering for algorithmic trading."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    market_data = commands.add_parser("data", help="the market data in your store")
    data_commands = market_data.add_subparsers(dest="data_command", required=True)
    imports = data_commands.add_parser("import", help="bring your files into the store")
    sources = imports.add_subparsers(dest="source", required=True)
    databento = sources.add_parser(
        "databento", help="a Databento batch download folder or a DBN file (.dbn, .dbn.zst)"
    )
    databento.add_argument("path", type=Path, help="the batch folder or the DBN file")
    databento.set_defaults(run=import_databento_files)
    verify = data_commands.add_parser(
        "verify-bars",
        help="rebuild a trade date's bars from finer data and compare them with the stored ones",
    )
    verify.add_argument("root", help="the product, such as MES")
    verify.add_argument(
        "trade_date", type=date.fromisoformat, help="the trade date, such as 2026-09-21"
    )
    verify.set_defaults(run=verify_bars_of_a_trade_date)
    return parser


def import_databento_files(arguments: argparse.Namespace) -> int:
    paths = resolve_paths(os.environ)
    source: Path = arguments.path
    report = import_databento(source, Store(paths.data_dir), paths.cache_dir)
    print(report.summary())
    return EXIT_OK


def verify_bars_of_a_trade_date(arguments: argparse.Namespace) -> int:
    paths = resolve_paths(os.environ)
    root: str = arguments.root
    trade_date: date = arguments.trade_date
    report = verify_bars(Store(paths.data_dir), root, trade_date, paths.cache_dir)
    print(report.summary())
    return EXIT_REFUSED if report.difference_count() else EXIT_OK
