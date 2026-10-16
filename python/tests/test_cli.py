import os
import shutil
from datetime import UTC, date, datetime
from importlib.metadata import entry_points
from pathlib import Path

import polars as pl
import pytest

from fefat.config import resolve_paths
from fefat.market.layout import Dataset, Partition, YearMonth
from fefat.market.schema import parse_schema_name
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
            f"  Terms page: {source.terms_url}",
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
