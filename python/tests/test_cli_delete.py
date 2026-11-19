"""`fefat data delete` (step 5.18, ADR-0023, Done means 6): it prints what a delete of a provider's
data of a root removes, with the saved runs that read it, and deletes nothing without `--yes`;
with it, it deletes; a pair the store does not hold is refused with exit code 1."""

import os
import shutil

import pytest

import fefat as ff
from fefat.config import resolve_paths
from fefat.market.store import Store
from fefat_app.cli import main
from notebook_runs import breakout, store_with
from test_market_stored_deletion import tree

WINDOW = ("2026-03-05", "2026-03-09")


def test_a_delete_without_yes_prints_what_goes_and_deletes_nothing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    store_with("ohlcv-1m")
    run = ff.backtest.run(breakout(), *WINDOW)
    paths = resolve_paths(os.environ)
    before = tree(paths.home.parent)

    code = main(["data", "delete", "synthetic", "ES"])

    shown = capsys.readouterr()
    assert code == 0
    assert tree(paths.home.parent) == before
    assert shown.out.splitlines() == [
        "ES from synthetic: 2 partitions of ohlcv-1m.",
        "No raw copy goes.",
        "Its engine cache goes.",
        "1 saved run read this data: it keeps its record and results, but can no longer be "
        "explained or checked again.",
        "Nothing was deleted: run the command again with --yes to delete it.",
    ]
    assert (run.folder / "run.json").is_file()


def test_a_delete_with_yes_deletes_and_says_so(capsys: pytest.CaptureFixture[str]) -> None:
    # Every dataset of the pair, ES's bars and its trades, and none of BTCUSDT-PERP's.
    store_with("ohlcv-1m", "trades")
    paths = resolve_paths(os.environ)

    code = main(["data", "delete", "synthetic", "ES", "--yes"])

    shown = capsys.readouterr()
    pairs = {(dataset.provider, dataset.root) for dataset in Store(paths.data_dir).list_datasets()}
    assert code == 0
    assert pairs == {("synthetic", "BTCUSDT-PERP")}
    assert shown.out.splitlines()[-2:] == [
        "No saved run read this data.",
        "Deleted ES from synthetic.",
    ]


def test_a_delete_of_data_the_store_does_not_hold_is_refused_with_1(
    capsys: pytest.CaptureFixture[str],
) -> None:
    store_with("ohlcv-1m")

    code = main(["data", "delete", "synthetic", "MES", "--yes"])

    assert code == 1
    assert capsys.readouterr().err.startswith(
        "fefat: Expected stored data of MES from synthetic, got none"
    )


def test_a_run_folder_copied_by_hand_is_counted_once_and_the_delete_says_it_deleted(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The reviews: the runs are counted before the delete, from their records, so that a folder
    # the run list refuses neither stops the preview nor turns a done delete into a refusal.
    store_with("ohlcv-1m")
    run = ff.backtest.run(breakout(), *WINDOW)
    shutil.copytree(run.folder, run.folder.with_name("f" * 64))

    code = main(["data", "delete", "synthetic", "ES", "--yes"])

    assert code == 0
    assert capsys.readouterr().out.splitlines()[-2:] == [
        "1 saved run read this data: it keeps its record and results, but can no longer be "
        "explained or checked again.",
        "Deleted ES from synthetic.",
    ]
