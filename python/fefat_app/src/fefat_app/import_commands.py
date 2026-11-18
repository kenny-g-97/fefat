"""`fefat data import`, the commands that bring a trader's files into the store in
`FEFAT_DATA_DIR` (`fefat_app.cli`):

    fefat data import databento <folder-or-file> [--preview] [--differing {refuse,take-file}]
    fefat data import file <path> --profile <name> [--contract] [--root] [--time-zone]
        [--preview] [--differing {refuse,take-file}] [--bars-in-breaks {refuse,leave-out}]

`databento` imports a Databento batch download, or a single DBN file, and prints what it
imported (`fefat.market.importers.databento`). `file` brings in a bar or tick file of your own
through an import profile, a preset or your own profile's YAML file, which an import that
writes saves for later imports (`fefat.market.importers.file_import`), and writes its product's
quality report. Both merge a file into the data the store already holds (ADR-0021): records
the store lacks are added, and those it holds are left alone. With `--preview` a command reads
the file against the store, prints what its import would add, for a file of your own after its
first records as they would be stored and the problems found, and writes nothing; it exits
with 1 when the import would be refused. Records the store holds with other values refuse a
file, unless `--differing take-file` lets the file's stand. A file of bars whose breaks hold a
bar closing at the next open is refused, unless `--bars-in-breaks leave-out` leaves those out
with the sessions beside them (ADR-0022).
"""

import argparse
import os
from collections.abc import Callable
from datetime import UTC, datetime
from functools import partial
from pathlib import Path

from fefat.config import FefatPaths, resolve_paths
from fefat.market.calendar_breaks import BarsInBreaks
from fefat.market.importers.databento import import_databento, preview_databento
from fefat.market.importers.file_import import FileImportRequest, import_file, preview_file
from fefat.market.importers.file_report import FileImportReport
from fefat.market.importers.partition_merge import DifferingRecords
from fefat.market.importers.profiles import load_profile, save_profile
from fefat.market.saved_instruments import instrument_table
from fefat.market.store import Store

EXIT_OK = 0
EXIT_REFUSED = 1

type QualityReportWriter = Callable[[FefatPaths, str, str], object]
"""Writes the quality report of a provider's data of a root, and prints its summary, as
`fefat data quality` does."""


def add_the_import_commands(
    imports: argparse.ArgumentParser, write_the_report: QualityReportWriter
) -> None:
    """The subcommands of `fefat data import` (module docstring); a file import that wrote has
    `write_the_report` write its product's quality report."""
    import_sources = imports.add_subparsers(dest="source", required=True)
    databento = import_sources.add_parser(
        "databento", help="a Databento batch download folder or a DBN file (.dbn, .dbn.zst)"
    )
    databento.add_argument("path", type=Path, help="the batch folder or the DBN file")
    _add_the_merge_options(
        databento, "print what the import would add to the store, and write nothing"
    )
    databento.set_defaults(run=import_databento_files)
    exports = import_sources.add_parser(
        "file", help="your own bar or tick file through an import profile"
    )
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
    _add_the_merge_options(
        exports,
        "print the first records as they would be stored, the problems found, and what the "
        "import would add to the store, and write nothing",
    )
    exports.add_argument(
        "--bars-in-breaks",
        choices=[each.value for each in BarsInBreaks],
        default=BarsInBreaks.REFUSE.value,
        help="what to do where a break holds a bar closing at the next session's open, the edge "
        "of a stretch the platform stamped early: refuse the file, as without the option, or "
        "leave-out, and the file is imported without those bars and the sessions beside them",
    )
    exports.set_defaults(run=partial(import_a_file, write_the_report=write_the_report))


def _add_the_merge_options(command: argparse.ArgumentParser, preview_help: str) -> None:
    command.add_argument("--preview", action="store_true", help=preview_help)
    command.add_argument(
        "--differing",
        choices=[each.value for each in DifferingRecords],
        default=DifferingRecords.REFUSE.value,
        help="what to do where the store holds the file's records with other values: refuse "
        "the file, as when left out, or take-file, and the file's records stand",
    )


def import_databento_files(arguments: argparse.Namespace) -> int:
    """Preview or import a Databento batch download or DBN file."""
    paths = resolve_paths(os.environ)
    source: Path = arguments.path
    preview: bool = arguments.preview
    differing = DifferingRecords(arguments.differing)
    store = Store(paths.data_dir)
    instruments = instrument_table(store.folder)
    if preview:
        shown = preview_databento(
            source, store, paths.cache_dir, instruments=instruments, differing=differing
        )
        print(shown.summary())
        return EXIT_REFUSED if shown.refuses() else EXIT_OK
    report = import_databento(
        source,
        store,
        paths.cache_dir,
        imported_on=datetime.now(UTC).date(),
        instruments=instruments,
        differing=differing,
    )
    print(report.summary())
    return EXIT_OK


def import_a_file(arguments: argparse.Namespace, write_the_report: QualityReportWriter) -> int:
    """Preview or import a trader's file; after an import that wrote, save its profile, where a
    YAML file gave it, and write its product's quality report."""
    paths = resolve_paths(os.environ)
    store = Store(paths.data_dir)
    preview: bool = arguments.preview
    reference: str = arguments.profile
    differing = DifferingRecords(arguments.differing)
    request = FileImportRequest(
        path=arguments.path,
        profile=load_profile(reference, paths.profiles_dir),
        contract=arguments.contract,
        root=arguments.root,
        time_zone=arguments.time_zone,
        bars_in_breaks=BarsInBreaks(arguments.bars_in_breaks),
    )
    instruments = instrument_table(store.folder)
    if preview:
        shown = preview_file(request, store, instruments, paths.cache_dir, differing=differing)
        print(shown.summary())
        return EXIT_REFUSED if shown.refusals() else EXIT_OK
    report = import_file(
        request,
        store,
        paths.cache_dir,
        imported_on=datetime.now(UTC).date(),
        instruments=instruments,
        differing=differing,
    )
    print(report.summary())
    if isinstance(report, FileImportReport):
        save_profile(reference, paths.profiles_dir)
        dataset = report.reading.dataset
        write_the_report(paths, dataset.provider, dataset.root)
    return EXIT_OK
