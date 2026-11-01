"""Skip equals full over long generated sessions (step 2.15, the backlog's "long months in the
skip-equals-full test"): three sessions of ESH2026 with about 71,000 trades each, 1-second and
1-minute bars, three planted quiet stretches and price jumps, generated as the benchmarks' year
is, run through the Rust engine in full replay and skipping. The exit plan has two targets,
breakeven after the first, and an intrabar trailing stop from 8 ticks of profit, and the trades'
paths are recorded and not: every table the two replays give is the same. The property test of
step 2.7 draws tapes of a few dozen ticks; these hold the skipping engine to whole sessions."""

import os

import fefat_engine
import polars as pl
import pyarrow as pa
import pytest

import fefat as ff
import gen_fixtures
from fefat.backtest import RunConfig
from fefat.backtest.run_inputs import run_inputs
from fefat.config import resolve_paths
from fefat.strategy import TicksTrigger

FIRST, LAST = "2026-01-05", "2026-01-07"
ENTRIES = {
    "market": ff.Market(),
    "limit": ff.Limit(offset_ticks=4, time_to_live_bars=3),
}


def strategy(entry: ff.strategy.EntryOrder) -> ff.SignalStrategy:
    """A breakout both ways whose exit plan uses every rule that can refuse a skip."""
    close = pl.col("close")
    return ff.SignalStrategy(
        instrument="ES",
        timeframe="5m",
        features={
            "highest": close.rolling_max(12).shift(1),
            "lowest": close.rolling_min(12).shift(1),
        },
        long_entry=close > pl.col("highest"),
        short_entry=close < pl.col("lowest"),
        execution=ff.Execution(
            entry=entry,
            stop=ff.Stop(ticks=16),
            targets=[ff.Target(ticks=8, fraction=0.5), ff.Target(ticks=24)],
            breakeven=ff.Breakeven(after_target=1),
            trailing=ff.Trailing(ticks=6, activation=TicksTrigger(ticks=8)),
            sizing=ff.Fixed(2),
        ),
    )


@pytest.fixture(name="generated_sessions", scope="module")
def fixture_generated_sessions(tmp_path_factory: pytest.TempPathFactory) -> str:
    """The data folder of the three generated sessions."""
    data = tmp_path_factory.mktemp("sessions")
    dates = ["--dates", f"{FIRST}..{LAST}", "--contracts", "ESH2026", "--planted-gaps", "3"]
    assert gen_fixtures.main(["--out", str(data / "synthetic"), *dates]) == 0
    return str(data)


@pytest.mark.parametrize("entry", ENTRIES, ids=list(ENTRIES))
@pytest.mark.parametrize("trade_paths", [True, False], ids=["paths", "no_paths"])
def test_skipping_leaves_every_table_as_the_full_replay_gives_it(
    generated_sessions: str, entry: str, trade_paths: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FEFAT_DATA_DIR", generated_sessions)
    paths = resolve_paths(os.environ)
    inputs = run_inputs(strategy(ENTRIES[entry]), FIRST, LAST, RunConfig(contract="ESH2026"), paths)
    arguments = (
        inputs.spec_json(),
        inputs.signals,
        [str(folder) for folder in inputs.cache_paths(paths)],
        inputs.config_json(),
    )

    full, skipping = (
        fefat_engine.run_signal_backtest(*arguments, replay=replay, trade_paths=trade_paths)
        for replay in ("full", "skipping")
    )

    tables = sorted(name for name in full if name != "summary")
    assert pa.table(full["fills"]).num_rows > 100
    assert (pa.table(full["trade_paths"]).num_rows > 0) == trade_paths
    assert [
        name for name in tables if not pa.table(full[name]).equals(pa.table(skipping[name]))
    ] == []
    assert full["summary"] == skipping["summary"]
