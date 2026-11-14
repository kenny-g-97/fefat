"""`fefat db` of step 4.1: `upgrade` makes or migrates the app's database under `FEFAT_HOME`,
`downgrade base` runs every migration down (Done means 1), and `import-workspace` indexes the
files the SDK saved (D-84)."""

import os

import pytest
from sqlalchemy import inspect

import fefat as ff
from fefat.config import resolve_paths
from fefat_app.cli import main
from fefat_app.database.schema import opened_database
from notebook_runs import features_of_cell
from strategy_code import BREAKOUT, HYPOTHESIS

GAP = """\
@ff.feature(params={"n": 3}, warmup=lambda n: n, outputs={"gap": "price_distance"})
def gap(bars: pl.LazyFrame, n: int) -> pl.Expr:
    return pl.col("close") - pl.col("close").rolling_mean(n)
"""


def test_db_upgrade_makes_the_database_under_fefat_home(
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_file = resolve_paths(os.environ).database_file

    code = main(["db", "upgrade"])

    assert code == 0
    assert database_file.is_file()
    assert capsys.readouterr().out == f"Upgraded {database_file} to revision 0006.\n"
    with opened_database(database_file) as engine:
        assert "feature_versions" in inspect(engine).get_table_names()


def test_db_downgrade_base_drops_every_table_but_alembics_own(
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_file = resolve_paths(os.environ).database_file
    main(["db", "upgrade"])
    capsys.readouterr()

    code = main(["db", "downgrade", "base"])

    assert code == 0
    assert capsys.readouterr().out == (
        f"Downgraded {database_file} to base: no table remains but Alembic's own.\n"
    )
    with opened_database(database_file) as engine:
        assert inspect(engine).get_table_names() == ["alembic_version"]


def test_db_downgrade_takes_base_alone() -> None:
    with pytest.raises(SystemExit) as usage:
        main(["db", "downgrade", "head"])

    assert usage.value.code == 2


def test_db_import_workspace_makes_the_database_and_indexes_what_the_sdk_saved(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The step's prompt: on the first run too, before any `fefat db upgrade`.
    empty = main(["db", "import-workspace"])
    printed_empty = capsys.readouterr().out
    ff.features.save(features_of_cell(GAP)["gap"])

    saved = main(["db", "import-workspace"])

    assert (empty, saved) == (0, 0)
    assert printed_empty == (
        "Indexed 0 new feature versions, 0 new strategy versions, 0 new validation reports, "
        "0 new import profiles, and 0 new runs.\n"
    )
    assert capsys.readouterr().out == (
        "Indexed 1 new feature version, 0 new strategy versions, 0 new validation reports, "
        "0 new import profiles, and 0 new runs.\n"
    )


def test_db_import_workspace_indexes_the_strategy_versions_a_notebook_saved(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Step 5.2 (D-93): the strategies' versions are files the command indexes too.
    ff.strategy.save("breakout", BREAKOUT, hypothesis=HYPOTHESIS)

    code = main(["db", "import-workspace"])

    assert code == 0
    assert capsys.readouterr().out == (
        "Indexed 0 new feature versions, 1 new strategy version, 0 new validation reports, "
        "0 new import profiles, and 0 new runs.\n"
    )


def test_db_import_workspace_rebuild_indexes_the_files_as_they_are(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The Phase 4 exit (`BACKLOG.md`, rebuild the index tables alone).
    ff.features.save(features_of_cell(GAP)["gap"])
    main(["db", "import-workspace"])
    (resolve_paths(os.environ).features_dir / "gap" / "v1.json").unlink()
    ff.features.save(features_of_cell(GAP.replace('"n": 3', '"n": 4'))["gap"])
    capsys.readouterr()

    refused = main(["db", "import-workspace"])
    refusal = capsys.readouterr().err
    rebuilt = main(["db", "import-workspace", "--rebuild"])

    assert (refused, rebuilt) == (1, 0)
    assert "fefat db import-workspace --rebuild" in refusal
    assert capsys.readouterr().out == (
        "Rebuilt the index from the files as they are: 1 feature version, 0 strategy versions, "
        "0 validation reports, 0 import profiles, and 0 runs.\n"
    )


def test_db_import_workspace_names_a_file_it_refuses(capsys: pytest.CaptureFixture[str]) -> None:
    ff.features.save(features_of_cell(GAP)["gap"])
    path = resolve_paths(os.environ).features_dir / "gap" / "v1.json"
    path.write_text("{}", encoding="utf-8")

    code = main(["db", "import-workspace"])

    assert code == 1
    assert capsys.readouterr().err.startswith(f"fefat: Expected {path} to hold a FeatureVersion")
