import hashlib
import os
import shutil
from datetime import UTC, date, datetime
from decimal import Decimal
from importlib.metadata import entry_points
from pathlib import Path, PurePosixPath

import polars as pl
import pytest

from fefat.config import resolve_paths
from fefat.market.layout import (
    Dataset,
    DatasetMetadata,
    DatasetOrigin,
    Partition,
    SizeUnit,
    YearMonth,
)
from fefat.market.schema import parse_schema_name, polars_schema
from fefat.market.sources import SOURCE_GUIDE
from fefat.market.store import Store
from fefat_app.cli import main

ROOT = Path(__file__).resolve().parents[2]
BATCH = ROOT / "fixtures" / "synthetic" / "databento-batch" / "GLBX-20260310-SYNTHETIC0"


def test_the_fefat_command_runs_the_cli() -> None:
    scripts = {script.name: script.value for script in entry_points(group="console_scripts")}

    assert scripts["fefat"] == "fefat_app.cli:main"


def test_a_databento_import_prints_its_summary_into_the_data_folder_and_exits_with_0(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = main(["data", "import", "databento", str(BATCH)])

    printed = capsys.readouterr().out
    assert code == 0
    assert printed.startswith(f"Imported 1 file from {BATCH}.\n")
    assert len(Store(resolve_paths(os.environ).data_dir).list_partitions()) == 1


def test_a_databento_import_records_today_as_the_import_date_of_its_files() -> None:
    before = datetime.now(UTC).date()

    main(["data", "import", "databento", str(BATCH)])

    after = datetime.now(UTC).date()
    files = Store(resolve_paths(os.environ).data_dir).raw_manifest().files
    assert len(files) == 4
    assert all(before <= file.imported_on <= after for file in files)


def test_a_second_import_of_the_same_batch_says_there_is_nothing_to_import(
    capsys: pytest.CaptureFixture[str],
) -> None:
    main(["data", "import", "databento", str(BATCH)])
    capsys.readouterr()

    code = main(["data", "import", "databento", str(BATCH)])

    assert code == 0
    assert capsys.readouterr().out.startswith(f"Nothing to import from {BATCH}")


def test_a_refused_import_prints_the_reason_and_exits_with_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["data", "import", "databento", str(tmp_path / "missing")])

    assert code == 1
    assert "fefat: Expected a Databento batch folder or DBN file" in capsys.readouterr().err


def test_verifying_imported_minute_bars_leaves_rebuilding_pending_and_exits_with_0(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The batch holds the vendor's 1-minute bars only, as the files on this PC do: rebuilding
    # them from trades waits for a trades file, and the resampling check runs on them.
    main(["data", "import", "databento", str(BATCH)])
    capsys.readouterr()

    code = main(["data", "verify-bars", "ES", "2026-03-06"])

    printed = capsys.readouterr().out.splitlines()
    assert code == 0
    assert printed[0] == "Bars of ES on 2026-03-06. Comparisons run: 1. Differences: none."
    assert printed[2] == (
        "databento: trades -> ohlcv-1m against ohlcv-1m: pending, without trades to rebuild from"
    )
    assert printed[-1].endswith("against ohlcv-1m -> ohlcv-1d: 1 compared, no differences")


def test_verifying_bars_that_differ_from_their_trades_prints_them_and_exits_with_1(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The fixtures in the data folder, with the 1-minute bar opening at 2026-03-06 14:30 UTC
    # one tick higher at its close than its trades say.
    data = resolve_paths(os.environ).data_dir
    shutil.copytree(ROOT / "fixtures" / "synthetic", data / "synthetic")
    store = Store(data)
    month = Partition(
        dataset=Dataset(provider="synthetic", schema_name=parse_schema_name("ohlcv-1m"), root="ES"),
        contract="ESH2026",
        key=YearMonth(year=2026, month=3),
    )
    changed = pl.col("ts_open") == 1_772_807_400_000_000_000
    bars = store.scan_partition(month).collect()
    store.write_partition(
        month,
        bars.with_columns(
            close=pl.when(changed).then(pl.col("close") + 250_000_000).otherwise(pl.col("close"))
        ),
    )

    code = main(["data", "verify-bars", "ES", "2026-03-06"])

    assert code == 1
    assert capsys.readouterr().out.splitlines()[0] == (
        "Bars of ES on 2026-03-06. Comparisons run: 4. Differences: 2."
    )


def test_verifying_a_day_without_bars_compares_nothing_and_exits_with_1(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The batch ends with Monday 2026-03-09: Tuesday 03-10 is a trade date without bars, so
    # nothing is compared, which is no pass.
    main(["data", "import", "databento", str(BATCH)])
    capsys.readouterr()

    code = main(["data", "verify-bars", "ES", "2026-03-10"])

    assert code == 1
    assert capsys.readouterr().out.splitlines()[0] == (
        "Bars of ES on 2026-03-10. Comparisons run: 0. Differences: none."
    )


def test_verifying_bars_of_a_store_without_them_prints_the_reason_and_exits_with_1(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = main(["data", "verify-bars", "ES", "2026-03-06"])

    assert code == 1
    assert "fefat: Expected trades or bars of ES in the store, got none" in capsys.readouterr().err


def fixtures_in_the_data_folder() -> Path:
    store_folder = resolve_paths(os.environ).data_dir
    shutil.copytree(ROOT / "fixtures" / "synthetic", store_folder / "synthetic")
    return store_folder


def test_the_data_catalog_prints_every_dataset_with_its_range_fidelity_and_quality(
    capsys: pytest.CaptureFixture[str],
) -> None:
    fixtures_in_the_data_folder()

    code = main(["data", "catalog"])

    btc = "synthetic BTCUSDT-PERP {}: 2026-03-07 to 2026-03-07, 1 contract, fidelity {}"
    es = "synthetic ES {}: 2026-03-05 to 2026-03-09, 2 contracts, fidelity {}"
    assert code == 0
    assert capsys.readouterr().out.splitlines() == [
        f"{dataset.format(schema, fidelity)}, quality unchecked"
        for dataset in (btc, es)
        for schema, fidelity in (("ohlcv-1m", "1m"), ("ohlcv-1s", "1s"), ("trades", "tick"))
    ]


def test_the_catalog_of_an_empty_store_says_so_and_exits_with_0(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = main(["data", "catalog"])

    assert code == 0
    assert capsys.readouterr().out == f"No datasets in {resolve_paths(os.environ).data_dir}.\n"


def test_quality_reports_of_clean_data_are_written_and_the_catalog_shows_them(
    capsys: pytest.CaptureFixture[str],
) -> None:
    store_folder = fixtures_in_the_data_folder()

    code = main(["data", "quality"])

    reports = store_folder / "reports" / "synthetic"
    assert code == 0
    assert capsys.readouterr().out.splitlines() == [
        "Quality of synthetic BTCUSDT-PERP, 2026-03-07 to 2026-03-07: clean.",
        f"Report: {reports / 'BTCUSDT-PERP' / 'quality.md'}",
        "Quality of synthetic ES, 2026-03-05 to 2026-03-09: clean.",
        f"Report: {reports / 'ES' / 'quality.md'}",
    ]
    main(["data", "catalog"])
    assert capsys.readouterr().out.splitlines()[-1].endswith("quality clean through 2026-03-09")


def test_a_quality_report_with_findings_prints_them_and_exits_with_1(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The 101st trade of ESH2026 on 2026-03-05 repeated right after itself.
    store = Store(fixtures_in_the_data_folder())
    trades = Partition(
        dataset=Dataset(provider="synthetic", schema_name=parse_schema_name("trades"), root="ES"),
        contract="ESH2026",
        key=date(2026, 3, 5),
    )
    rows = store.scan_partition(trades).collect()
    store.write_partition(trades, pl.concat([rows.head(101), rows.slice(100)]))

    code = main(["data", "quality", "ES"])

    assert code == 1
    assert capsys.readouterr().out.splitlines()[:2] == [
        "Quality of synthetic ES, 2026-03-05 to 2026-03-09: flagged, 1 finding.",
        "  2026-03-05 duplicates in trades ESH2026: 1",
    ]


def test_a_report_whose_columns_changed_is_written_again(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # A report of an older version, whose tables lack today's columns, is no reason to refuse
    # writing the new one.
    stale = fixtures_in_the_data_folder() / "reports" / "synthetic" / "ES"
    stale.mkdir(parents=True)
    for table in ("days.parquet", "findings.parquet"):
        pl.DataFrame({"trade_date": [date(2026, 3, 5)]}).write_parquet(stale / table)

    code = main(["data", "quality", "ES"])

    assert code == 0
    assert capsys.readouterr().out.splitlines()[0] == (
        "Quality of synthetic ES, 2026-03-05 to 2026-03-09: clean."
    )


def test_a_quality_report_of_a_product_without_data_is_refused_and_exits_with_1(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = main(["data", "quality", "ZZ"])

    assert code == 1
    assert "fefat: Expected trades or bars of ZZ in the store, got none" in capsys.readouterr().err


def test_the_source_guide_prints_each_source_with_its_offer_cost_terms_and_presets(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = main(["data", "sources"])

    header, *blocks = capsys.readouterr().out.rstrip("\n").split("\n\n")
    assert code == 0
    assert header == (
        f"Source guide, researched {SOURCE_GUIDE.researched_on}. Prices and terms change: "
        "check a source's own pages before you rely on them."
    )
    assert len(blocks) == len(SOURCE_GUIDE.sources)
    for block, source in zip(blocks, SOURCE_GUIDE.sources, strict=True):
        lines = block.splitlines()
        assert lines[:7] == [
            f"{source.name}, {source.kind.replace('-', ' ')}",
            f"  Offers: {source.offers}",
            f"  Cost: {source.cost}",
            f"  Terms: {source.terms}",
            f"  Terms page: {'none published' if source.terms_url is None else source.terms_url}",
            "  Your own account or files in a desktop app: "
            f"{source.desktop_use.verdict()}. {source.desktop_use_note}",
            f"  Licence scope: {source.licence_scope}",
        ]
        presets = [
            f"    {preset.id} ({preset.status}): {preset.name}. {preset.reads}"
            for preset in source.presets
        ]
        assert lines[7:] == (["  Presets:", *presets] if presets else ["  Presets: none yet"])


def test_the_source_guide_names_the_presets_of_databento_and_ninjatrader(
    capsys: pytest.CaptureFixture[str],
) -> None:
    main(["data", "sources"])

    printed = capsys.readouterr().out
    assert "\nDatabento, vendor\n" in f"\n{printed}"
    assert "    databento (available): Databento DBN batch download." in printed
    assert "    ninjatrader (planned): NinjaTrader 8 export." in printed


CATALOG_LINE = "Catalog version 1: MES, MNQ, MCL, MGC."
MISSING = [
    f"{root}: missing; Databento is its first recommended source"
    for root in ("MES", "MNQ", "MCL", "MGC")
]


def one_minute_bar_on(store: Store, root: str, contract: str, trade_date: date) -> None:
    """A dataset of `root` from Databento holding one 1-minute bar of `contract`."""
    dataset = Dataset(provider="databento", schema_name=parse_schema_name("ohlcv-1m"), root=root)
    store.write_dataset_metadata(
        dataset,
        DatasetMetadata(
            size_unit=SizeUnit(lot=Decimal(1), asset="contract"),
            origin=DatasetOrigin.IMPORT,
            licence_scope=SOURCE_GUIDE.source("databento").licence_scope,
        ),
    )
    bar = pl.DataFrame(
        {"ts_open": [0], "ts_close": [60_000_000_000], "trade_date": [trade_date], "instrument_id": [1], "open": [1], "high": [1], "low": [1], "close": [1], "volume": [1], "trade_count": [None], "vwap": [None]},
        schema=polars_schema(dataset.schema_name),
    )  # fmt: skip
    month = YearMonth(year=trade_date.year, month=trade_date.month)
    store.write_partition(Partition(dataset=dataset, contract=contract, key=month), bar)


def imported_on_october_13(store: Store, folder: Path, *roots: str) -> None:
    """A Databento file in the raw manifest, imported on 2026-10-13, that fed `roots`."""
    source = folder / "bars.dbn"
    source.write_bytes(b"bars")
    path = PurePosixPath("databento", "job", "bars.dbn")
    store.write_raw_file(path, source, hashlib.sha256(b"bars").hexdigest())
    store.record_raw_file(
        path,
        provider="databento",
        vendor_version="DBN 3",
        downloaded_on=date(2026, 9, 23),
        batch_job=None,
        imported_on=date(2026, 10, 13),
        roots=roots,
    )


def test_the_status_of_an_empty_store_lists_every_catalog_product_as_missing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = main(["data", "status"])

    assert code == 0
    assert capsys.readouterr().out.splitlines() == [CATALOG_LINE, *MISSING]


def test_the_status_reads_complete_at_1_minute_fidelity_for_bars_from_each_launch(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = Store(resolve_paths(os.environ).data_dir)
    launches = (
        ("MES", "MESM2019", date(2019, 5, 6)),
        ("MNQ", "MNQM2019", date(2019, 5, 6)),
        ("MCL", "MCLU2021", date(2021, 7, 12)),
        ("MGC", "MGCZ2010", date(2010, 10, 4)),
    )
    for root, contract, launch in launches:
        one_minute_bar_on(store, root, contract, launch)
    imported_on_october_13(store, tmp_path, "MCL", "MES", "MGC", "MNQ")

    code = main(["data", "status"])

    assert code == 0
    assert capsys.readouterr().out.splitlines() == [
        CATALOG_LINE,
        *(
            f"{root} databento ohlcv-1m: {launch} to {launch}, complete at 1-minute fidelity, "
            "last import 2026-10-13, quality unchecked"
            for root, _, launch in launches
        ),
    ]


def test_the_status_reads_partial_for_bars_from_after_a_launch(
    capsys: pytest.CaptureFixture[str],
) -> None:
    store = Store(resolve_paths(os.environ).data_dir)
    one_minute_bar_on(store, "MES", "MESU2019", date(2019, 6, 3))

    main(["data", "status"])

    assert capsys.readouterr().out.splitlines()[1] == (
        "MES databento ohlcv-1m: 2019-06-03 to 2019-06-03, partial at 1-minute fidelity, the "
        "history starts on 2019-05-06, no import record, quality unchecked"
    )


def test_the_status_lists_the_fixtures_as_unlisted_with_their_quality_verdicts(
    capsys: pytest.CaptureFixture[str],
) -> None:
    def unlisted(checked: bool) -> list[str]:
        return [
            f"{root} synthetic {schema}: {first} to {last}, not in the catalog, {fidelity} "
            f"fidelity, no import record, quality {f'clean through {last}' if checked else 'unchecked'}"
            for root, first, last in (
                ("BTCUSDT-PERP", "2026-03-07", "2026-03-07"),
                ("ES", "2026-03-05", "2026-03-09"),
            )
            for schema, fidelity in (
                ("ohlcv-1m", "1-minute"),
                ("ohlcv-1s", "1-second"),
                ("trades", "tick"),
            )
        ]

    fixtures_in_the_data_folder()

    main(["data", "status"])
    before = capsys.readouterr().out.splitlines()
    main(["data", "quality"])
    capsys.readouterr()
    main(["data", "status"])
    after = capsys.readouterr().out.splitlines()

    assert before == [CATALOG_LINE, *MISSING, *unlisted(checked=False)]
    assert after == [CATALOG_LINE, *MISSING, *unlisted(checked=True)]


def test_a_report_older_than_its_data_reads_stale_in_the_status_and_the_catalog(
    capsys: pytest.CaptureFixture[str],
) -> None:
    store = Store(fixtures_in_the_data_folder())
    main(["data", "quality", "ES"])
    trades = Dataset(provider="synthetic", schema_name=parse_schema_name("trades"), root="ES")
    march_9 = Partition(dataset=trades, contract="ESH2026", key=date(2026, 3, 9))
    march_10 = Partition(dataset=trades, contract="ESH2026", key=date(2026, 3, 10))
    store.write_partition(march_10, store.scan_partition(march_9).collect())
    capsys.readouterr()

    main(["data", "status"])
    status = capsys.readouterr().out.splitlines()
    main(["data", "catalog"])
    listed = capsys.readouterr().out.splitlines()

    stale = "quality stale, checked through 2026-03-09"
    assert status[-1].startswith("ES synthetic trades: 2026-03-05 to 2026-03-10")
    assert status[-1].endswith(stale)
    assert listed[-1].endswith(stale)
