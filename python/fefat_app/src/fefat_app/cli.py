"""The `fefat` command, what a trader runs in a terminal:

    fefat data import databento <folder-or-file>
    fefat data verify-bars <root> <trade-date>
    fefat data catalog
    fefat data quality [<root>]
    fefat data sources
    fefat data status
    fefat data import file <path> --profile <name> [--contract] [--root] [--time-zone]
        [--preview]
    fefat data profiles [<name>]
    fefat cache build --root <root> --year <year> [--provider <provider>]
    fefat cache status [--root <root>]
    fefat cache features [--prune [--older-than <days>]]

The first imports a Databento batch download, or a single DBN file, into the store in
`FEFAT_DATA_DIR` (`fefat.config.resolve_paths`) and prints what it imported; the second
rebuilds a trade date's bars from the finer data in the store and prints how they compare with
the stored ones (`fefat.market.bars_check`); the third prints each dataset in the store with
its trade dates, contracts, fidelity, and quality (`fefat.market.api.datasets`); the fourth
writes the quality report of a product, or of every product, under `FEFAT_DATA_DIR/reports/`
and prints its summary (`fefat.market.quality`); the fifth prints the source guide, each
known source with what it offers, its cost and terms, and the presets that read its files
(`fefat.market.sources`); the sixth prints each product of the catalog with its datasets,
their coverage and fidelity, last import, and quality, then the datasets of other products
(`fefat.market.status`). `import file` brings in a bar or tick file of your own through an
import profile, a preset or your own profile's YAML file, which an import that writes saves
for later imports
(`fefat.market.importers.file_import`): with `--preview` it prints the first records as they
would be stored and the problems found, and writes nothing; else it imports the file and
writes its product's quality report. `profiles` lists the presets and your saved profiles,
or prints one as YAML to copy into a profile of your own.

`cache build` builds the engine's cache of a product's trade dates in a year, `cache status`
lists it, and `cache features` lists the feature cache or prunes what was not used for a while
(`fefat_app.cache_commands`).

A command exits with 0 when it succeeds, and with 1 and the reason when it refuses its input,
a preview too when it would refuse the file; `verify-bars` also exits with 1 when it finds
bars that differ, or nothing to compare, and `quality` when a report holds findings. A command
line that names no command, or a date that is no date, exits with 2 and the usage, as
`argparse` does.
"""

import argparse
import os
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from fefat.config import FefatPaths, resolve_paths
from fefat.market.api import datasets
from fefat.market.bars_check import verify_bars
from fefat.market.catalog import CATALOG
from fefat.market.coverage import session_datasets
from fefat.market.fidelity import fidelity_in_words
from fefat.market.importers.databento import import_databento
from fefat.market.importers.file_import import (
    FileImportReport,
    FileImportRequest,
    import_file,
    preview_file,
)
from fefat.market.importers.profiles import (
    load_profile,
    preset_profiles,
    profile_yaml,
    save_profile,
    saved_profiles,
)
from fefat.market.quality import assess_quality
from fefat.market.quality_report import MARKDOWN_FILE_NAME, QualityStatus, write_quality_report
from fefat.market.saved_instruments import instrument_table
from fefat.market.sources import SOURCE_GUIDE, Source
from fefat.market.status import CoverageStatus, product_status
from fefat.market.store import Store
from fefat_app.cache_commands import add_the_cache_commands

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
    exports = import_sources.add_parser(
        "file", help="your own bar or tick file through an import profile"
    )
    _add_the_file_import_arguments(exports)
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
    status = data_commands.add_parser(
        "status", help="list each catalog product with its coverage, last import, and quality"
    )
    status.set_defaults(run=print_the_status)
    profiles = data_commands.add_parser(
        "profiles", help="list the import presets and your saved profiles, or print one"
    )
    profiles.add_argument("name", nargs="?", help="a preset or saved profile to print as YAML")
    profiles.set_defaults(run=print_the_profiles)
    cache = commands.add_parser("cache", help="the engine's and the features' caches")
    add_the_cache_commands(cache)
    return parser


def _add_the_file_import_arguments(exports: argparse.ArgumentParser) -> None:
    exports.add_argument(
        "path", type=Path, help="the file: CSV, TSV, text, or Parquet, or a .gz or .zip of one"
    )
    exports.add_argument(
        "--profile",
        required=True,
        help="a preset (fefat data profiles lists them), a saved profile, or a profile's YAML file",
    )
    exports.add_argument(
        "--contract", help="the file's contract, such as ESH2026, where its name does not say"
    )
    exports.add_argument(
        "--root", help="the product, such as ES, of a continuous series or a perpetual"
    )
    exports.add_argument(
        "--time-zone",
        help="the time zone of the file's times, such as America/New_York, where the "
        "profile leaves it to the import",
    )
    exports.add_argument(
        "--preview",
        action="store_true",
        help="print the first records as they would be stored and the problems found, and "
        "write nothing",
    )
    exports.set_defaults(run=import_a_file)


def import_databento_files(arguments: argparse.Namespace) -> int:
    paths = resolve_paths(os.environ)
    source: Path = arguments.path
    today = datetime.now(UTC).date()
    store = Store(paths.data_dir)
    instruments = instrument_table(store.folder)
    report = import_databento(
        source, store, paths.cache_dir, imported_on=today, instruments=instruments
    )
    print(report.summary())
    return EXIT_OK


def import_a_file(arguments: argparse.Namespace) -> int:
    """Preview or import a trader's file; after an import that wrote, save its profile, where a
    YAML file gave it, and write its product's quality report."""
    paths = resolve_paths(os.environ)
    store = Store(paths.data_dir)
    preview: bool = arguments.preview
    reference: str = arguments.profile
    request = FileImportRequest(
        path=arguments.path,
        profile=load_profile(reference, paths.profiles_dir),
        contract=arguments.contract,
        root=arguments.root,
        time_zone=arguments.time_zone,
    )
    instruments = instrument_table(store.folder)
    if preview:
        shown = preview_file(request, instruments, paths.cache_dir)
        print(shown.summary())
        return EXIT_REFUSED if shown.reading.refusals() else EXIT_OK
    today = datetime.now(UTC).date()
    report = import_file(
        request, store, paths.cache_dir, imported_on=today, instruments=instruments
    )
    print(report.summary())
    if isinstance(report, FileImportReport):
        save_profile(reference, paths.profiles_dir)
        dataset = report.reading.dataset
        _write_the_report(paths, dataset.provider, dataset.root)
    return EXIT_OK


def print_the_profiles(arguments: argparse.Namespace) -> int:
    profiles_dir = resolve_paths(os.environ).profiles_dir
    name: str | None = arguments.name
    if name is not None:
        print(profile_yaml(load_profile(name, profiles_dir)), end="")
        return EXIT_OK
    saved = saved_profiles(profiles_dir)
    lines = [
        "Import presets (fefat data sources names the source each reads):",
        *(f"  {profile.name}: {profile.description}" for profile in preset_profiles().values()),
        f"Your saved profiles, in {profiles_dir}:",
        *(f"  {profile.name}: {profile.description}" for profile in saved.values()),
        *([] if saved else ["  none yet: give --profile a profile's YAML file to save one"]),
    ]
    print("\n".join(lines))
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
    lines = [_catalog_line(row) for row in datasets().iter_rows(named=True)]
    if not lines:
        lines = [f"No datasets in {resolve_paths(os.environ).data_dir}."]
    print("\n".join(lines))
    return EXIT_OK


def _catalog_line(row: dict[str, Any]) -> str:
    contracts: int = row["contracts"]
    held = "1 contract" if contracts == 1 else f"{contracts:,} contracts"
    dataset = f"{row['provider']} {row['root']} {row['schema']}"
    dates = f"{row['first_trade_date']} to {row['last_trade_date']}"
    return f"{dataset}: {dates}, {held}, fidelity {row['fidelity']}, {_quality(row)}"


def _quality(row: dict[str, Any]) -> str:
    if row["quality"] == QualityStatus.STALE:
        return f"quality stale, checked through {row['checked_through']}"
    if row["checked_through"] is None:
        return f"quality {row['quality']}"
    return f"quality {row['quality']} through {row['checked_through']}"


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
        f"  Terms page: {'none published' if source.terms_page is None else source.terms_page}",
        "  Your own account or files in a desktop app: "
        f"{source.desktop_use.verdict()}. {source.desktop_use_note}",
        f"  Licence scope: {source.licence_scope}",
        *(["  Presets:", *presets] if presets else ["  Presets: none yet"]),
    ]
    return "\n".join(lines)


def print_the_status(arguments: argparse.Namespace) -> int:
    paths = resolve_paths(os.environ)
    status = product_status(Store(paths.data_dir), paths.reports_dir, CATALOG)
    header = f"Catalog version {CATALOG.version}: {', '.join(CATALOG.roots())}."
    print("\n".join([header, *(_status_line(row) for row in status.iter_rows(named=True))]))
    return EXIT_OK


def _status_line(row: dict[str, Any]) -> str:
    coverage = CoverageStatus(row["coverage"])
    if coverage is CoverageStatus.MISSING:
        source: str = row["recommended_source"]
        return f"{row['root']}: missing; {source} is its first recommended source"
    fidelity = f"{fidelity_in_words(row['fidelity'])} fidelity"
    held = {
        CoverageStatus.COMPLETE: f"complete at {fidelity}",
        CoverageStatus.PARTIAL: f"partial at {fidelity}, the history starts on "
        f"{row['history_from']}",
        CoverageStatus.UNLISTED: f"not in the catalog, {fidelity}",
    }[coverage]
    last_import = row["last_import"]
    imported = "no import record" if last_import is None else f"last import {last_import}"
    dataset = f"{row['root']} {row['provider']} {row['schema']}"
    dates = f"{row['first_trade_date']} to {row['last_trade_date']}"
    return f"{dataset}: {dates}, {held}, {imported}, {_quality(row)}"
