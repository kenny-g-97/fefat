"""NautilusTrader's side of the cross-check on the synthetic Databento batch (ESH2026, 2026-03-04
to 2026-03-09): the cut loads through the Databento adapter, the 5-minute bars Nautilus builds
close on the same bars FEFAT's do, the three strategies run under both bar paths and
deterministically, and their trades come out in the comparison's columns."""

import io
import json
from pathlib import Path

import polars as pl
from databento_dbn import Compression, Encoding, Transcoder

from fefat_xcheck.classify import TRADE_COLUMNS
from fefat_xcheck.nautilus_side import run_nautilus_side

REPOSITORY = Path(__file__).resolve().parents[4]
RAW = (
    REPOSITORY
    / "fixtures"
    / "synthetic"
    / "databento-batch"
    / "GLBX-20260310-SYNTHETIC0"
    / "glbx-mdp3-20260304-20260309.ohlcv-1m.dbn"
)
MINUTE = 60_000_000_000
FIVE_MINUTES = 5 * MINUTE
TICK = 250_000_000


def strategy(name: str, entry: str, offset: int, ttl: int | None) -> dict[str, object]:
    return {
        "name": name,
        "entry": entry,
        "offset_ticks": offset,
        "time_to_live_bars": ttl,
        "stop_ticks": 12,
        "target_ticks": 12,
        "window": ["08:35", "14:30"],
        "flat_by": "15:00",
        "tz": "America/Chicago",
    }


def comparison_folder(tmp_path: Path) -> Path:
    """A comparison folder as `scripts/xcheck.py` leaves it: `fefat/fefat.json` and the cut,
    here the whole synthetic batch compressed, with `cut.json` beside it."""
    (tmp_path / "fefat").mkdir(parents=True)
    facts = {
        "window": {"first": "2026-03-05", "last": "2026-03-06"},
        "instrument": {"root": "ES", "contract": "ESH2026", "tick": TICK, "point_value": "50"},
        "strategies": [
            strategy("market", "market", 0, None),
            strategy("limit", "limit", 2, 1),
            strategy("stop", "stop", 2, 1),
        ],
    }
    (tmp_path / "fefat" / "fefat.json").write_text(json.dumps(facts), encoding="utf-8")
    compressed = io.BytesIO()
    transcoder = Transcoder(compressed, Encoding("dbn"), Compression("zstd"))
    transcoder.write(RAW.read_bytes())
    transcoder.finish()
    (tmp_path / "ESH2026.dbn.zst").write_bytes(compressed.getvalue())
    cut = {"cut": {"name": "ESH2026.dbn.zst", "raw_symbol": "ESH6"}}
    (tmp_path / "cut.json").write_text(json.dumps(cut), encoding="utf-8")
    return tmp_path


def five_minute_closes(bars: pl.DataFrame) -> pl.DataFrame:
    """The close of each 5-minute bucket of close-stamped 1-minute bars, stamped at its end;
    Nautilus builds a bucket when its timer fires, so the one closing at the data's last bar,
    after which no timer fires, is never built."""
    bucket = ((pl.col("ts_close") - 1) // FIVE_MINUTES + 1) * FIVE_MINUTES
    return (
        bars.sort("ts_close")
        .group_by(bucket.alias("ts_close"), maintain_order=True)
        .agg(pl.col("close").last())
    )


def test_nautilus_runs_the_strategies_on_the_cut_and_writes_its_tables(tmp_path: Path) -> None:
    folder = comparison_folder(tmp_path)

    facts = run_nautilus_side(folder)

    engine = folder / "engine"
    assert facts["nautilus_trader"] == "1.231.0"
    assert json.loads((engine / "nautilus.json").read_text(encoding="utf-8")) == facts
    bars = pl.read_parquet(engine / "bars_1m.parquet")
    assert bars.columns == ["ts_open", "ts_close", "open", "high", "low", "close", "volume"]
    assert bars.height == 4141
    for name in ("market", "limit", "stop"):
        for order in ("ohlc", "adaptive"):
            trades = pl.read_parquet(engine / f"trades_{name}_{order}.parquet")
            assert trades.schema == TRADE_COLUMNS, (name, order)
            assert trades.height > 0, (name, order)
            assert trades["entry_kind"].unique().to_list() == [name]
            assert set(trades["exit_reason"].unique().to_list()) <= {"stop", "target", "flat_by"}
            assert trades["entry_ts"].is_sorted()
    market = pl.read_parquet(engine / "trades_market_ohlc.parquet")
    assert market["entry_ts"].to_list() == market["entry_decision"].to_list()
    decisions = pl.read_parquet(engine / "decisions_market_ohlc.parquet")
    assert decisions.columns == ["ts_close", "close", "action"]
    assert set(decisions["action"].unique().to_list()) <= {"none", "long", "short", "flat_by"}


def test_nautilus_five_minute_closes_are_the_last_one_minute_close_of_each_bucket(
    tmp_path: Path,
) -> None:
    folder = comparison_folder(tmp_path)

    run_nautilus_side(folder)

    bars = pl.read_parquet(folder / "engine" / "bars_1m.parquet")
    decisions = pl.read_parquet(folder / "engine" / "decisions_market_ohlc.parquet")
    last_close = bars["ts_close"].max()
    expected = five_minute_closes(bars).filter(pl.col("ts_close") < last_close)
    assert decisions.select("ts_close", "close").equals(expected)


def test_nautilus_runs_are_deterministic(tmp_path: Path) -> None:
    first, second = comparison_folder(tmp_path / "first"), comparison_folder(tmp_path / "second")

    run_nautilus_side(first)
    run_nautilus_side(second)

    for name in ("trades_stop_adaptive", "trades_limit_ohlc", "decisions_market_adaptive"):
        once = pl.read_parquet(first / "engine" / f"{name}.parquet")
        again = pl.read_parquet(second / "engine" / f"{name}.parquet")
        assert once.equals(again), name
