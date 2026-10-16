"""The `fefat` command, what a trader runs in a terminal:

    fefat data import databento <folder-or-file>
    fefat data verify-bars <root> <trade-date>
    fefat data catalog
    fefat data quality [<root>]
    fefat data sources

The first imports a Databento batch download, or a single DBN file, into the store in
`FEFAT_DATA_DIR` (`fefat.config.resolve_paths`) and prints what it imported; the second
rebuilds a trade date's bars from the finer data in the store and prints how they compare with
the stored ones (`fefat.market.bars_check`); the third prints each dataset in the store with
its trade dates, contracts, fidelity, and quality (`fefat.market.api.catalog`); the fourth
writes the quality report of a product, or of every product, under `FEFAT_DATA_DIR/reports/`
and prints its summary (`fefat.market.quality`); the fifth prints the source guide, each
known source with what it offers, its cost and terms, and the presets that read its files
(`fefat.market.sources`). A command exits with 0 when it succeeds, and
with 1 and the reason when it refuses its input; `verify-bars` also exits with 1 when it finds
bars that differ, or nothing to compare, and `quality` when a report holds findings. A command
line that names no command, or a date that is no date, exits with 2 and the usage, as
`argparse` does.
"""

import argparse
import os
import sys
from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path
from typing import Any

from fefat.config import FefatPaths, resolve_paths
from fefat.market.api import catalog
from fefat.market.bars_check import verify_bars
from fefat.market.coverage import session_datasets
from fefat.market.importers.databento import import_databento
from fefat.market.quality import assess_quality
from fefat.market.quality_report import MARKDOWN_FILE_NAME, QualityStatus, write_quality_report
from fefat.market.sources import SOURCE_GUIDE, Source
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
    import_sources = imports.add_subparsers(dest="source", required=True)
    databento = import_sources.add_parser(
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
    listing = data_commands.add_parser(
        "catalog", help="list each dataset in the store with its coverage and quality"
    )
    listing.set_defaults(run=print_the_catalog)
    quality = data_commands.add_parser(
        "quality", help="write the quality report of a product, or of every product"
    )
    quality.add_argument(
        "root", nargs="?", help="the product, such as MES; every product when left out"
    )
    quality.set_defaults(run=report_the_quality)
    guide = data_commands.add_parser(
        "sources", help="list the known data sources, their costs and terms, and their presets"
    )
    guide.set_defaults(run=print_the_source_guide)
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
    verified = report.comparisons_run() > 0 and report.difference_count() == 0
    return EXIT_OK if verified else EXIT_REFUSED


def print_the_catalog(arguments: argparse.Namespace) -> int:
    lines = [_catalog_line(row) for row in catalog().iter_rows(named=True)]
    if not lines:
        lines = [f"No datasets in {resolve_paths(os.environ).data_dir}."]
    print("\n".join(lines))
    return EXIT_OK


def _catalog_line(row: dict[str, Any]) -> str:
    contracts: int = row["contracts"]
    held = "1 contract" if contracts == 1 else f"{contracts:,} contracts"
    quality = f"quality {row['quality']}"
    if row["checked_through"] is not None:
        quality = f"{quality} through {row['checked_through']}"
    dataset = f"{row['provider']} {row['root']} {row['schema']}"
    dates = f"{row['first_trade_date']} to {row['last_trade_date']}"
    return f"{dataset}: {dates}, {held}, fidelity {row['fidelity']}, {quality}"


def report_the_quality(arguments: argparse.Namespace) -> int:
    paths = resolve_paths(os.environ)
    root: str | None = arguments.root
    datasets = session_datasets(Store(paths.data_dir))
    held = sorted(
        {
            (dataset.provider, dataset.root)
            for dataset in datasets
            if root is None or dataset.root == root
        }
    )
    if not held:
        named = "any product" if root is None else root
        raise ValueError(f"Expected trades or bars of {named} in the store, got none.")
    statuses = [_write_the_report(paths, provider, held_root) for provider, held_root in held]
    clean = all(status is QualityStatus.CLEAN for status in statuses)
    return EXIT_OK if clean else EXIT_REFUSED


def _write_the_report(paths: FefatPaths, provider: str, root: str) -> QualityStatus:
    report = assess_quality(Store(paths.data_dir), provider, root, paths.cache_dir)
    folder = write_quality_report(report, paths.reports_dir)
    print(report.summary())
    print(f"Report: {folder / MARKDOWN_FILE_NAME}")
    return report.status()


def print_the_source_guide(arguments: argparse.Namespace) -> int:
    header = (
        f"Source guide, researched {SOURCE_GUIDE.researched_on}. Prices and terms change: "
        "check a source's own pages before you rely on them."
    )
    print("\n\n".join([header, *(_source_block(source) for source in SOURCE_GUIDE.sources)]))
    return EXIT_OK


def _source_block(source: Source) -> str:
    presets = [
        f"    {preset.id} ({preset.status}): {preset.name}. {preset.reads}"
        for preset in source.presets
    ]
    lines = [
        f"{source.name}, {source.kind.replace('-', ' ')}",
        f"  Offers: {source.offers}",
        f"  Cost: {source.cost}",
        f"  Terms: {source.terms}",
        f"  Terms page: {source.terms_url}",
        "  Your own account or files in a desktop app: "
        f"{source.desktop_use.verdict()}. {source.desktop_use_note}",
        f"  Licence scope: {source.licence_scope}",
        *(["  Presets:", *presets] if presets else ["  Presets: none yet"]),
    ]
    return "\n".join(lines)
