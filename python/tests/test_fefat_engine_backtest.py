"""The engine through its Python bindings (step 2.10): `run_signal_backtest` returns the tables
`fefat-cli run` writes for the same case, `run_batch` runs many cases over one shared cache on
several cores with the interpreter released (Done means 3), and `run_key` and `table_hash` key a
run, a setting or a value of the signal frame changing the key."""

import io
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

import fefat_engine
import polars as pl
import pytest

import fefat as ff
from fefat.config import resolve_paths
from fefat.market import instruments
from fefat.market.engine_cache import build_engine_cache
from fefat.market.fidelity import TickFidelity
from fefat.market.store import Store
from fefat.reference.hours import AlwaysOpen
from fefat.reference.run_documents import run_document, with_engine_columns
from fefat.reference.rust_batch import CacheCase, Replay, write_cache_batch
from fefat.reference.rust_run import default_binary
from fefat.reference.settings import RunSettings, SlippageTicks
from fefat.reference.units import CAPITAL, instrument_parameters
from notebook_runs import breakout, store_with

TABLES = ("fills", "orders", "log", "costs", "trades", "equity")
CASES = 100


@pytest.fixture(name="cached_month")
def fixture_cached_month() -> tuple[Path, pl.DataFrame]:
    """The fixtures' ES in the engine cache, and ESH2026's 5-minute signal bars."""
    store_with("trades", "ohlcv-1s", "ohlcv-1m")
    paths = resolve_paths(os.environ)
    build_engine_cache(Store(paths.data_dir), paths.cache_dir, "ES", 2026)
    folder = paths.cache_dir / "engine" / "synthetic" / "ES" / "ESH2026"
    bars = ff.market.load("ESH2026", "5m", "2026-03-05", "2026-03-09").collect()
    return folder, bars


def config_json(settings: RunSettings) -> str:
    """The run's config as `fefat.reference.rust_batch` writes a cached case's."""
    document = run_document(
        fidelity=TickFidelity.TRADES,
        instrument=instrument_parameters(instruments.get("ES")),
        settings=settings,
        hours=AlwaysOpen(),
        capital=CAPITAL,
        position=None,
        fees=None,
        funding=(),
        rolls=(),
    )
    return json.dumps(document)


def engine_frame(strategy: ff.SignalStrategy, bars: pl.DataFrame) -> pl.DataFrame:
    signals = strategy.signals(bars).collect()
    return with_engine_columns(strategy.to_spec(), signals, None)


def cli_tables(case: CacheCase) -> dict[str, pl.DataFrame]:
    """Each table `fefat-cli run` writes for `case`, without the `case` column."""
    with tempfile.TemporaryDirectory(prefix="fefat-cli-bindings-") as folder:
        batch, outputs = Path(folder) / "input", Path(folder) / "output"
        write_cache_batch([case], batch)
        command = [str(default_binary()), "run", str(batch), str(outputs)]
        subprocess.run(command, check=True, capture_output=True, timeout=300)
        return {
            name: pl.read_ipc(io.BytesIO((outputs / f"{name}.arrow").read_bytes())).drop("case")
            for name in TABLES
        }


def test_the_bindings_return_the_tables_fefat_cli_writes_for_the_same_case(
    cached_month: tuple[Path, pl.DataFrame],
) -> None:
    folder, bars = cached_month
    strategy = breakout(12)
    settings = RunSettings.for_fidelity(TickFidelity.TRADES)
    signals = strategy.signals(bars).collect()
    case = CacheCase(
        id="breakout",
        folder=folder,
        fidelity=TickFidelity.TRADES,
        instrument=instrument_parameters(instruments.get("ES")),
        settings=settings,
        strategy=strategy.to_spec(),
        signals=signals,
        replay=Replay.SKIPPING,
    )
    spec_json = strategy.to_spec().document_json()

    run = fefat_engine.run_signal_backtest(
        spec_json, engine_frame(strategy, bars), [str(folder)], config_json(settings), "skipping"
    )

    expected = cli_tables(case)
    assert not expected["trades"].is_empty()
    for name in TABLES:
        assert pl.DataFrame(run[name]).equals(expected[name]), name


def test_a_batch_of_100_runs_shares_the_cache_and_uses_more_than_one_core(
    cached_month: tuple[Path, pl.DataFrame],
) -> None:
    # Done means 3: CPU time well above wall time, printed for the pull request. The runs replay
    # in full, so that each takes long enough to measure: Windows charges CPU time in ticks.
    # The tables are the same as skipping gives (the skip-equals-full property).
    folder, bars = cached_month
    config = config_json(RunSettings.for_fidelity(TickFidelity.TRADES))
    cases = []
    for ticks in range(4, 4 + CASES):
        strategy = breakout(ticks)
        frame = engine_frame(strategy, bars)
        cases.append((strategy.to_spec().document_json(), frame, [str(folder)], config))

    cpu, wall = time.process_time(), time.perf_counter()
    runs = fefat_engine.run_batch(cases, "full")
    cpu, wall = time.process_time() - cpu, time.perf_counter() - wall

    print(f"run_batch of {CASES} runs: {cpu:.2f} s of CPU time in {wall:.2f} s of wall time")
    assert len(runs) == CASES
    assert len({pl.DataFrame(run["fills"]).height for run in runs}) > 1
    if (os.cpu_count() or 1) > 1:
        assert cpu > 1.3 * wall


def test_a_case_of_a_batch_that_cannot_be_read_is_named_by_its_place(
    cached_month: tuple[Path, pl.DataFrame],
) -> None:
    # Step 2.10's review: a sweep's bad case is found by its place, as a case that fails to run is.
    folder, bars = cached_month
    strategy = breakout(12)
    frame = engine_frame(strategy, bars)
    config = config_json(RunSettings.for_fidelity(TickFidelity.TRADES))
    spec_json = strategy.to_spec().document_json()
    case = (spec_json, frame, [str(folder)], config)
    undated = (spec_json, frame.drop("trade_date"), [str(folder)], config)

    with pytest.raises(ValueError, match=r"Expected case 1 of the batch to run, got: .*trade_date"):
        fefat_engine.run_batch([case, undated])


def test_a_setting_or_a_value_of_the_signal_frame_changes_the_run_key(
    cached_month: tuple[Path, pl.DataFrame],
) -> None:
    _, bars = cached_month
    strategy = breakout(12)
    frame = engine_frame(strategy, bars)
    spec_json = strategy.to_spec().document_json()
    one_tick = RunSettings.for_fidelity(TickFidelity.TRADES)
    two_ticks = one_tick.model_copy(update={"slippage_ticks": SlippageTicks(market=2, stop=1)})
    frame_hash = fefat_engine.table_hash(frame)
    partitions = ["a" * 64]

    key = fefat_engine.run_key(spec_json, frame_hash, partitions, config_json(one_tick))

    assert len(key) == 64
    assert fefat_engine.run_key(spec_json, frame_hash, partitions, config_json(one_tick)) == key
    assert fefat_engine.run_key(spec_json, frame_hash, partitions, config_json(two_ticks)) != key
    assert fefat_engine.table_hash(frame.clone()) == frame_hash
    changed = frame.with_columns(pl.col("long_entry").not_())
    assert fefat_engine.table_hash(changed) != frame_hash
    assert fefat_engine.table_hash(frame.select(reversed(frame.columns))) != frame_hash
