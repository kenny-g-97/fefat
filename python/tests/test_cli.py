import os
from importlib.metadata import entry_points
from pathlib import Path

import pytest

from fefat.config import resolve_paths
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
