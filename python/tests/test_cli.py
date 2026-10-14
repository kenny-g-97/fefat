import os
import shutil
from importlib.metadata import entry_points
from pathlib import Path

import polars as pl
import pytest

from fefat.config import resolve_paths
from fefat.market.layout import Dataset, Partition, YearMonth
from fefat.market.schema import parse_schema_name
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


def test_verifying_bars_of_a_store_without_them_prints_the_reason_and_exits_with_1(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = main(["data", "verify-bars", "ES", "2026-03-06"])

    assert code == 1
    assert "fefat: Expected trades or bars of ES in the store, got none" in capsys.readouterr().err
