"""A saved run made again (step 5.10, D-126): a run reproduced on the data it read matches its
trades' hash and leaves no folder behind (Done means 2, the SDK's half); data changed since the run
is refused before the engine runs, naming the file written since (D-99); a strategy other than
the run's, another engine, moved rolls, another signal frame, and another fee table or calendar
are refused in words that say which; trades that differ keep their folder with both hashes, which
a later reproduction replaces; and a folder holding anything else is refused and left as it is."""

import os
from datetime import date
from pathlib import Path

import fefat_engine
import polars as pl
import pytest

import fefat as ff
import fefat.backtest.reproductions as reproductions
from fefat.backtest import ReproductionDiffered, ReproductionMatched, Run
from fefat.backtest.record import EngineVersions, RunRecord, StrategyRecord
from fefat.backtest.run_inputs import RunInputs
from fefat.backtest.runs import engine_run
from fefat.config import resolve_paths
from notebook_runs import breakout, store_with

WINDOW = ("2026-03-05", "2026-03-09")


@pytest.fixture(autouse=True)
def fixture_store() -> None:
    store_with("ohlcv-1m")


@pytest.fixture
def saved() -> Run:
    return ff.backtest.run(breakout(), *WINDOW)


def test_a_run_reproduced_on_the_data_it_read_matches_and_leaves_no_folder(
    saved: Run, tmp_path: Path
) -> None:
    into = tmp_path / "reproduced"

    reproduced = ff.backtest.reproduce(saved, breakout(), into)

    assert isinstance(reproduced, ReproductionMatched)
    assert reproduced.trades_hash == fefat_engine.table_hash(saved.trades)
    assert saved.trades.height > 0
    assert not into.exists()


def test_data_changed_since_the_run_is_refused_naming_the_file_before_the_engine_runs(
    saved: Run, tmp_path: Path
) -> None:
    bars = resolve_paths(os.environ).data_dir / "synthetic" / "ohlcv-1m" / "root=ES"
    part = bars / "contract=ESH2026" / "month=2026-03" / "part.parquet"
    part.write_bytes(part.read_bytes() + b"changed")
    into = tmp_path / "reproduced"

    written = (
        r"the data changed since the run\. By the files' times, written since the run was "
        r"saved: synthetic/ohlcv-1m/root=ES/contract=ESH2026/month=2026-03/part\.parquet\. "
    )
    with pytest.raises(ValueError, match=written):
        ff.backtest.reproduce(saved, breakout(), into)
    assert not into.exists()


def test_a_strategy_other_than_the_runs_is_refused(saved: Run, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Expected the strategy's specification as the run's"):
        ff.backtest.reproduce(saved, breakout(stop_ticks=8), tmp_path / "reproduced")


def test_a_run_of_another_engine_is_refused(saved: Run, tmp_path: Path) -> None:
    versions = EngineVersions(engine=1, fill_model=1, artifact_schema=1)

    with pytest.raises(ValueError, match="Expected a run of this engine"):
        ff.backtest.reproduce(held_as(saved, versions=versions), breakout(), tmp_path / "again")


def test_rolls_that_moved_since_the_run_are_refused_by_their_dates(
    saved: Run, tmp_path: Path
) -> None:
    (crossed,) = saved.record.rolls
    earlier = crossed.model_copy(update={"trade_date": date(2026, 3, 6)})
    held = held_as(saved, rolls=(earlier,))

    moved = (
        "Expected the rolls of ES the run crossed, ESH2026 to ESM2026 on 2026-03-06, got "
        "ESH2026 to ESM2026 on 2026-03-09: data imported since the run moved a roll"
    )
    with pytest.raises(ValueError, match=moved):
        ff.backtest.reproduce(held, breakout(), tmp_path / "again")


def test_a_signal_frame_that_differs_is_refused(saved: Run, tmp_path: Path) -> None:
    held = held_as(saved, signal_frame_hash="0" * 64)

    with pytest.raises(
        ValueError, match="Expected the signal frame the run read, hash 000000000000, got"
    ):
        ff.backtest.reproduce(held, breakout(), tmp_path / "again")


@pytest.mark.parametrize(
    ("part", "words"), [("hours", "calendar"), ("fees", "fee table"), ("funding", "funding rates")]
)
def test_a_part_of_the_engines_config_that_changed_is_refused_by_name(
    saved: Run, tmp_path: Path, part: str, words: str
) -> None:
    config = {**saved.record.engine_config, part: {"changed": True}}

    with pytest.raises(ValueError, match=f"got another: the {words} of ES changed since the run"):
        ff.backtest.reproduce(held_as(saved, engine_config=config), breakout(), tmp_path / "again")


def test_trades_that_differ_keep_their_folder_with_both_hashes_until_a_match_replaces_it(
    saved: Run, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    into = tmp_path / "reproduced"
    with monkeypatch.context() as planted:
        planted.setattr(reproductions, "engine_run", without_its_last_trade)
        differed = ff.backtest.reproduce(saved, breakout(), into)

    assert isinstance(differed, ReproductionDiffered)
    assert differed.saved_trades_hash == fefat_engine.table_hash(saved.trades)
    assert differed.reproduced_trades_hash != differed.saved_trades_hash
    assert differed.folder == into
    assert pl.read_parquet(into / "trades.parquet").height == saved.trades.height - 1

    assert isinstance(ff.backtest.reproduce(saved, breakout(), into), ReproductionMatched)
    assert not into.exists()


def test_a_folder_holding_anything_else_is_refused_and_left_as_it_is(
    saved: Run, tmp_path: Path
) -> None:
    into = tmp_path / "notes"
    into.mkdir()
    (into / "notes.txt").write_text("mine", encoding="utf-8")

    with pytest.raises(ValueError, match="holds something else"):
        ff.backtest.reproduce(saved, breakout(), into)
    with pytest.raises(ValueError, match="apart from the run's own"):
        ff.backtest.reproduce(saved, breakout(), saved.folder)
    assert (into / "notes.txt").read_text(encoding="utf-8") == "mine"
    assert (saved.folder / "run.json").is_file()


def without_its_last_trade(
    inputs: RunInputs,
    cache_paths: tuple[Path, ...],
    strategy: StrategyRecord,
    key: str,
    frame_hash: str,
) -> tuple[dict[str, pl.DataFrame], RunRecord]:
    """The engine's run, its trades short of the last: an engine that fills otherwise."""
    artifacts, record = engine_run(inputs, cache_paths, strategy, key, frame_hash)
    trades = artifacts["trades"]
    return {**artifacts, "trades": trades.head(trades.height - 1)}, record


def held_as(run: Run, **changed: object) -> Run:
    """`run` as if its record held `changed`."""
    return Run(folder=run.folder, record=run.record.model_copy(update=changed))
