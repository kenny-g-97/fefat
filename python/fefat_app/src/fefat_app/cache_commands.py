"""`fefat cache`, the commands of the caches FEFAT keeps in `FEFAT_HOME/cache/`, which can be
deleted at any time and are built again (`fefat_app.cli`):

    fefat cache build --root <root> --year <year> [--provider <provider>]
    fefat cache status [--root <root>]
    fefat cache features [--prune [--older-than <days>]]

`build` builds the engine's cache of a product's trade dates in a year from the store, in
`FEFAT_HOME/cache/engine/`: each contract-month whose partitions changed since it was cached,
or that has none, from the provider that `load` reads or the one `--provider` names, and prints
what it built (`fefat.market.engine_cache`). `status` lists each cached contract-month with the
levels of its trade dates and its size. `features` lists the feature cache that
`ff.features.compute` and backtests keep in `FEFAT_HOME/cache/features/`, a line for the signal
bars and for each feature with its parameters of each product and timeframe, with its partitions,
the dates they span, their size, and when one was last used (`fefat.features.cache_index`); with
`--prune`, it removes the partitions unused for 30 days, or for the days `--older-than` names,
and prints what it removed and what remains, exiting with 1 where another program holds a
file open, which it names.
"""

import argparse
import os
from datetime import UTC, datetime, timedelta
from typing import Any

from fefat.config import resolve_paths
from fefat.features.cache_index import (
    FEATURE_CACHE_FOLDER_NAME,
    feature_cache_status,
    prune_feature_cache,
)
from fefat.market.calendar import counted
from fefat.market.engine_cache import build_engine_cache
from fefat.market.engine_cache_index import engine_cache_status, size_text
from fefat.market.store import Store

EXIT_OK = 0
EXIT_REFUSED = 1
PRUNED_AFTER_DAYS = 30
"""The days a partition of the feature cache may go unused before `--prune` removes it."""


def add_the_cache_commands(cache: argparse.ArgumentParser) -> None:
    """The subcommands of `fefat cache` (module docstring)."""
    cache_commands = cache.add_subparsers(dest="cache_command", required=True)
    build = cache_commands.add_parser(
        "build", help="cache a product's trade dates of a year for the engine"
    )
    build.add_argument("--root", required=True, help="the product, such as MES")
    build.add_argument("--year", required=True, type=int, help="the year, such as 2025")
    build.add_argument(
        "--provider", help="the provider whose data to cache, where several hold the product"
    )
    build.set_defaults(run=build_the_engine_cache)
    status = cache_commands.add_parser(
        "status", help="list each cached contract-month with its levels and size"
    )
    status.add_argument("--root", help="the product, such as MES; every product when left out")
    status.set_defaults(run=print_the_engine_cache_status)
    features = cache_commands.add_parser(
        "features", help="list the cached features, or prune those unused for a while"
    )
    features.add_argument(
        "--prune", action="store_true", help="remove the partitions unused for a while"
    )
    features.add_argument(
        "--older-than",
        type=int,
        metavar="DAYS",
        help=f"with --prune, the days a partition went unused; {PRUNED_AFTER_DAYS} when left out",
    )
    features.set_defaults(run=manage_the_feature_cache)


def build_the_engine_cache(arguments: argparse.Namespace) -> int:
    paths = resolve_paths(os.environ)
    root: str = arguments.root
    year: int = arguments.year
    provider: str | None = arguments.provider
    build = build_engine_cache(Store(paths.data_dir), paths.cache_dir, root, year, provider)
    print(build.summary())
    return EXIT_REFUSED if build.refused else EXIT_OK


def print_the_engine_cache_status(arguments: argparse.Namespace) -> int:
    paths = resolve_paths(os.environ)
    root: str | None = arguments.root
    lines = [month.summary() for month in engine_cache_status(paths.cache_dir, root)]
    if not lines:
        lines = [
            f"No engine cache in {paths.cache_dir}; build one with "
            "fefat cache build --root <root> --year <year>."
        ]
    print("\n".join(lines))
    return EXIT_OK


def manage_the_feature_cache(arguments: argparse.Namespace) -> int:
    paths = resolve_paths(os.environ)
    prune: bool = arguments.prune
    older_than: int | None = arguments.older_than
    if not prune:
        if older_than is not None:
            raise ValueError(f"Expected --older-than with --prune, got --older-than {older_than}.")
        print(_feature_cache_lines(feature_cache_status(paths.cache_dir).rows(named=True)))
        return EXIT_OK
    days = PRUNED_AFTER_DAYS if older_than is None else older_than
    if days < 0:
        raise ValueError(f"Expected --older-than at 0 days or more, got {days}.")
    pruned = prune_feature_cache(paths.cache_dir, timedelta(days=days), datetime.now(UTC))
    print(
        f"Removed {counted(pruned.removed, 'partition')} of {size_text(pruned.removed_bytes)} "
        f"unused for {counted(days, 'day')}; {counted(pruned.kept, 'partition')} of "
        f"{size_text(pruned.kept_bytes)} remain."
    )
    if not pruned.held:
        return EXIT_OK
    print(
        f"Kept {counted(len(pruned.held), 'file')} another program holds open; close it and "
        "prune again:"
    )
    for held in pruned.held:
        print(f"  {held}")
    return EXIT_REFUSED


def _feature_cache_lines(rows: list[dict[str, Any]]) -> str:
    """A line for each folder of the feature cache, or where it is empty, how to fill it."""
    if not rows:
        folder = resolve_paths(os.environ).cache_dir / FEATURE_CACHE_FOLDER_NAME
        return f"No feature cache in {folder}; ff.features.compute writes one."
    return "\n".join(_feature_cache_line(row) for row in rows)


def _feature_cache_line(row: dict[str, Any]) -> str:
    """`<provider> <instrument> <timeframe> <feature>(<parameters>) <key>: <partitions>,
    <first> to <last>, <size>, last used <date>`."""
    feature = row["feature"] if not row["key"] else f"{row['feature']}({row['parameters']})"
    key = f" {row['key'][:8]}" if row["key"] else ""
    place = f"{row['provider']} {row['instrument']} {row['timeframe']} {feature}{key}"
    spans = f"{row['first']} to {row['last']}"
    used = f"last used {row['last_used']:%Y-%m-%d}"
    return f"{place}: {counted(row['partitions'], 'partition')}, {spans}, {size_text(row['size_bytes'])}, {used}"
