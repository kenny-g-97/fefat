"""A saved run made again (step 5.10, D-126): a run reproduced on the data it read matches its
trades' hash and leaves no folder behind (Done means 2, the SDK's half); data changed since the run
is refused before the engine runs, naming the file written since (D-99), and data changed while it
ran after it; a strategy of another saved version, features of other code, another specification,
another engine, moved rolls, another signal frame, a part of the engine's config, and another run
key are refused in words that say which; trades that differ keep their folder with both hashes,
which a later reproduction replaces, as one a file held open stopped halfway; a match stays a match
where its folder cannot be removed; and a folder holding anything else, the trader's own file
beside a kept reproduction or a damaged record, is refused and left as it is."""

import os
import re
from collections.abc import Callable
from datetime import date
from pathlib import Path

import fefat_engine
import polars as pl
import pytest

import fefat as ff
import fefat.backtest.reproductions as reproductions
from fefat.backtest import ReproductionDiffered, ReproductionMatched, Run
from fefat.backtest.record import EngineVersions, FeaturePin, RunRecord, StrategyRecord
from fefat.backtest.run_inputs import RunInputs
from fefat.backtest.runs import engine_run
from fefat.config import resolve_paths
from fefat.strategy.signal_strategy import StrategyPin
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
    ("part", "words"),
    [
        ("hours", "calendar"),
        ("fees", "fee table"),
        ("funding", "funding rates"),
        ("instrument", "instrument's specification"),
    ],
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


def test_a_strategy_of_another_saved_version_is_refused_before_anything_loads(
    saved: Run, tmp_path: Path
) -> None:
    pin = StrategyPin(name="demo", version=1, hash="0" * 64, parameters={"lookback": 12})
    strategy = saved.record.strategy.model_copy(update={"saved_version": pin})

    built = "Expected the strategy the run was built from, demo version 1 with {'lookback': 12}"
    with pytest.raises(ValueError, match=re.escape(built)):
        ff.backtest.reproduce(held_as(saved, strategy=strategy), breakout(), tmp_path / "again")


def test_features_of_other_code_are_refused_before_anything_loads(
    saved: Run, tmp_path: Path
) -> None:
    pin = FeaturePin(slot="trend", name="trend", version=3, hash="0" * 64, parameters={})
    strategy = saved.record.strategy.model_copy(update={"feature_versions": (pin,)})

    with pytest.raises(ValueError, match="the run's slots read, trend version 3, got features of"):
        ff.backtest.reproduce(held_as(saved, strategy=strategy), breakout(), tmp_path / "again")


def test_another_run_key_is_refused(saved: Run, tmp_path: Path) -> None:
    held = held_as(saved, run_key="0" * 64, run_id="0" * 64)

    with pytest.raises(ValueError, match="Expected the run key 000000000000, got another"):
        ff.backtest.reproduce(held, breakout(), tmp_path / "again")


def test_data_changed_while_the_engine_ran_is_refused_and_writes_no_folder(
    saved: Run, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    into = tmp_path / "reproduced"
    with monkeypatch.context() as planted:
        planted.setattr(reproductions, "engine_run", changing_the_data)
        with pytest.raises(ValueError, match="the data changed since the run"):
            ff.backtest.reproduce(saved, breakout(), into)

    assert not into.exists()


def test_a_kept_reproduction_beside_a_file_of_the_traders_is_refused_and_left_as_it_is(
    saved: Run, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    into = tmp_path / "reproduced"
    with monkeypatch.context() as planted:
        planted.setattr(reproductions, "engine_run", without_its_last_trade)
        ff.backtest.reproduce(saved, breakout(), into)
    (into / "notes.md").write_text("mine", encoding="utf-8")

    with pytest.raises(ValueError, match="holds something else"):
        ff.backtest.reproduce(saved, breakout(), into)
    assert (into / "notes.md").read_text(encoding="utf-8") == "mine"
    assert (into / "trades.parquet").is_file()


def test_an_earlier_reproduction_held_open_is_refused_and_removed_by_the_next(
    saved: Run, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    into = tmp_path / "reproduced"
    with monkeypatch.context() as planted:
        planted.setattr(reproductions, "engine_run", without_its_last_trade)
        ff.backtest.reproduce(saved, breakout(), into)
    with monkeypatch.context() as held:
        held.setattr(Path, "unlink", refusing("trades.parquet"))
        with pytest.raises(ValueError, match="got a file of it that could not be removed"):
            ff.backtest.reproduce(saved, breakout(), into)

    assert (into / "run.json").is_file()
    assert isinstance(ff.backtest.reproduce(saved, breakout(), into), ReproductionMatched)
    assert not into.exists()


def test_a_match_whose_folder_is_held_open_stays_a_match(
    saved: Run, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    into = tmp_path / "reproduced"
    with monkeypatch.context() as held:
        held.setattr(Path, "unlink", refusing("trades.parquet"))
        matched = ff.backtest.reproduce(saved, breakout(), into)

    assert isinstance(matched, ReproductionMatched)
    assert (into / "run.json").is_file()
    assert isinstance(ff.backtest.reproduce(saved, breakout(), into), ReproductionMatched)
    assert not into.exists()


def test_a_damaged_earlier_record_reads_as_a_folder_holding_something_else(
    saved: Run, tmp_path: Path
) -> None:
    into = tmp_path / "reproduced"
    into.mkdir()
    (into / "run.json").write_text("[", encoding="utf-8")

    with pytest.raises(ValueError, match="holds something else"):
        ff.backtest.reproduce(saved, breakout(), into)
    assert (into / "run.json").read_text(encoding="utf-8") == "["


def changing_the_data(
    inputs: RunInputs,
    cache_paths: tuple[Path, ...],
    strategy: StrategyRecord,
    key: str,
    frame_hash: str,
) -> tuple[dict[str, pl.DataFrame], RunRecord]:
    """The engine's run, an import merging into a partition the run read while it ran."""
    ran = engine_run(inputs, cache_paths, strategy, key, frame_hash)
    bars = resolve_paths(os.environ).data_dir / "synthetic" / "ohlcv-1m" / "root=ES"
    part = bars / "contract=ESH2026" / "month=2026-03" / "part.parquet"
    part.write_bytes(part.read_bytes() + b"changed")
    return ran


def refusing(name: str) -> Callable[..., None]:
    """`Path.unlink` refusing the file `name`, as Windows refuses one another program holds open."""
    unlink = Path.unlink

    def refused(self: Path, missing_ok: bool = False) -> None:
        if self.name == name:
            raise PermissionError(13, "The file is being used by another process", str(self))
        unlink(self, missing_ok=missing_ok)

    return refused


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
