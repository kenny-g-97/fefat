"""The FEFAT side of the cross-check against NautilusTrader and NinjaTrader 8 (step 2.14,
`scripts/xcheck.py`): the month cut of a Databento batch file, and the runs, tables, and record
the other engines' sides read, on the synthetic store."""

import json
from datetime import date
from pathlib import Path

import polars as pl

from fefat.market.importers.dbn import read_dbn
from notebook_runs import SYNTHETIC, store_with
from xcheck import (
    Comparison,
    CrossCheckStrategy,
    EntryKind,
    cut_month,
    export_fefat_side,
    instrument_id_of,
)

BATCH = SYNTHETIC / "databento-batch" / "GLBX-20260310-SYNTHETIC0"
RAW = BATCH / "glbx-mdp3-20260304-20260309.ohlcv-1m.dbn"
NANOSECONDS_PER_DAY = 86_400_000_000_000


def utc_day(day: date) -> int:
    return (day - date(1970, 1, 1)).days * NANOSECONDS_PER_DAY


STRATEGIES = (
    CrossCheckStrategy("market", EntryKind.MARKET, 0, None, 12, 12),
    CrossCheckStrategy("limit", EntryKind.LIMIT, 2, 1, 12, 12),
)
SYNTHETIC_ES = Comparison(
    name="nautilus",
    root="ES",
    contract="ESH2026",
    raw_symbol="ESH6",
    provider="synthetic",
    first=date(2026, 3, 5),
    last=date(2026, 3, 6),
    strategies=STRATEGIES,
)


def test_the_month_cut_keeps_one_contracts_records_of_the_window_as_zstd_dbn(
    tmp_path: Path,
) -> None:
    start, end = utc_day(date(2026, 3, 5)), utc_day(date(2026, 3, 7))
    instrument_id = instrument_id_of(RAW, "ESH6")
    _, frames = read_dbn(RAW)
    whole = pl.concat(frames)
    wanted = whole.filter(
        (pl.col("instrument_id") == instrument_id)
        & (pl.col("ts_event") >= start)
        & (pl.col("ts_event") < end)
    )

    cut = cut_month(RAW, instrument_id, start, end, tmp_path / "ESH2026.dbn.zst")

    metadata, cut_frames = read_dbn(cut)
    records = pl.concat(cut_frames)
    assert instrument_id == 1001
    assert str(metadata.schema_name) == "ohlcv-1m"
    assert metadata.dataset == "GLBX.MDP3"
    assert records.height == wanted.height
    assert records.height < whole.height
    assert records["instrument_id"].unique().to_list() == [instrument_id]
    assert records.filter(pl.col("ts_event") < start).height == 0
    assert records.filter(pl.col("ts_event") >= end).height == 0
    assert records.sort("ts_event").equals(wanted.sort("ts_event"))


def test_the_fefat_side_writes_its_tables_and_record(tmp_path: Path) -> None:
    store_with("ohlcv-1m")

    record = export_fefat_side(SYNTHETIC_ES, tmp_path)

    written = json.loads((tmp_path / "fefat" / "fefat.json").read_text(encoding="utf-8"))
    assert written == record
    assert set(written["versions"]) == {"engine", "fill_model", "artifact_schema"}
    assert written["engine_version"]
    assert written["profile"] == {
        "fidelity": "1m",
        "latency_ms": 0,
        "slippage_ticks": {"market": 0, "stop": 0},
        "limit_fill": "touch",
    }
    assert written["snapshot"]["sha256"]
    assert written["snapshot"]["dataset"] == "synthetic/ohlcv-1m/root=ES"
    assert written["snapshot"]["last"] == "2026-03-06"
    assert written["instrument"] == {
        "root": "ES",
        "contract": "ESH2026",
        "tick": 250_000_000,
        "point_value": "50",
    }
    assert [strategy["name"] for strategy in written["strategies"]] == ["market", "limit"]
    assert written["strategies"][1] == {
        "name": "limit",
        "entry": "limit",
        "offset_ticks": 2,
        "time_to_live_bars": 1,
        "stop_ticks": 12,
        "target_ticks": 12,
        "window": ["08:35", "14:30"],
        "flat_by": "15:00",
        "tz": "America/Chicago",
    }
    for name in ("market", "limit"):
        trades = pl.read_parquet(tmp_path / "fefat" / f"trades_{name}.parquet")
        assert trades["entry_contract"].unique().to_list() == ["ESH2026"]
        assert trades.filter(pl.col("entry_trade_date") < date(2026, 3, 5)).height == 0
        assert (tmp_path / "fefat" / f"fills_{name}.parquet").is_file()
        signals = pl.read_parquet(tmp_path / "fefat" / f"signals_{name}.parquet")
        assert {"ts_close", "signal_close", "empty_bucket", "long_entry", "stop_price"} <= set(
            signals.columns
        )
    bars = pl.read_parquet(tmp_path / "fefat" / "bars_1m.parquet")
    assert bars.columns == ["ts_open", "ts_close", "open", "high", "low", "close", "volume"]
    assert bars.height == 2 * 1380
