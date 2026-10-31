"""The comparison report (step 2.14, Done means 1 and 3): match rates and difference classes per
strategy, the versions of both engines and the data snapshot hash in its header, and a refusal
to pass while any difference is `unknown`."""

from datetime import date

import polars as pl

from fefat_xcheck.classify import TRADE_COLUMNS, classify
from fefat_xcheck.conventions import NAUTILUS_OHLC
from fefat_xcheck.report import (
    EngineReport,
    ReportInputs,
    StrategyReport,
    report_text,
    unknown_count,
)

MINUTE = 60_000_000_000
DECISION = 1_000_000 * MINUTE
POINT = 1_000_000_000
TICK = 250_000_000
FEFAT_FACTS = {
    "versions": {"engine": 8, "fill_model": 1, "artifact_schema": 2},
    "engine_version": "0.1.0",
    "sdk_version": "0.0.1",
    "window": {"first": "2026-08-03", "last": "2026-08-31"},
    "snapshot": {
        "dataset": "databento/ohlcv-1m/root=MES",
        "first": "2026-07-31",
        "last": "2026-08-31",
        "sha256": "76404e438da6c161b37d913aae048a74867f6270ef87c9bfdf080deeaa2f3c58",
    },
    "profile": {
        "fidelity": "1m",
        "latency_ms": 0,
        "slippage_ticks": {"market": 0, "stop": 0},
        "limit_fill": "touch",
    },
    "fee_table": {"name": "retail-default", "schedules": [["2026-07-20", "0.94 USD a side"]]},
    "instrument": {"root": "MES", "contract": "MESU2026", "tick": TICK, "point_value": "5"},
    "strategies": [
        {
            "name": "market",
            "entry": "market",
            "offset_ticks": 0,
            "time_to_live_bars": None,
            "stop_ticks": 12,
            "target_ticks": 12,
            "window": ["08:35", "14:30"],
            "flat_by": "15:00",
            "tz": "America/Chicago",
        }
    ],
}
CUT_FACTS = {
    "raw_file": {
        "name": "glbx-mdp3-20100606-20260922.ohlcv-1m.dbn",
        "sha256": "a" * 64,
        "vendor_sha256": "b" * 64,
        "vendor_version": "DBN 3",
    },
    "cut": {
        "name": "MESU2026.dbn.zst",
        "sha256": "c" * 64,
        "from": "2026-07-30",
        "to": "2026-09-01",
    },
}


def trade(entry_minutes: int, entry: float) -> dict[str, object]:
    return {
        "entry_decision": DECISION,
        "side": "long",
        "entry_kind": "market",
        "entry_ts": DECISION + entry_minutes * MINUTE,
        "entry_price": round(entry * POINT),
        "exit_ts": DECISION + 5 * MINUTE,
        "exit_price": 103 * POINT,
        "exit_reason": "target",
        "stop_price": 97 * POINT,
        "target_price": 103 * POINT,
        "gross_pnl": 13.75,
    }


BARS = pl.DataFrame(
    {
        "ts_close": [DECISION, DECISION + MINUTE, DECISION + 5 * MINUTE],
        "open": [100 * POINT, round(100.25 * POINT), round(102.5 * POINT)],
        "high": [round(100.25 * POINT), round(100.5 * POINT), round(103.25 * POINT)],
        "low": [round(99.75 * POINT), 100 * POINT, round(102.25 * POINT)],
        "close": [100 * POINT, round(100.25 * POINT), 103 * POINT],
    }
)


def strategy_report(other_entry: float) -> StrategyReport:
    fefat = pl.DataFrame([trade(1, 100.25)], schema=TRADE_COLUMNS)
    other = pl.DataFrame([trade(0, other_entry)], schema=TRADE_COLUMNS)
    classified = classify(fefat, other, BARS, NAUTILUS_OHLC, TICK)
    return StrategyReport("market", NAUTILUS_OHLC, classified, 13.75, 15.0)


def inputs(other_entry: float, ninjatrader: EngineReport | None = None) -> ReportInputs:
    nautilus = EngineReport(
        engine="NautilusTrader 1.231.0",
        settings=("bar_execution on",),
        data_checks=("1-minute bars identical: 28,980 of 28,980",),
        strategies=(strategy_report(other_entry),),
    )
    return ReportInputs(
        written_on=date(2026, 10, 31),
        fefat=FEFAT_FACTS,
        cut=CUT_FACTS,
        nautilus=nautilus,
        ninjatrader=ninjatrader,
        ninjatrader_pending="No export under xcheck/nt8/export: run the strategy in the Strategy Analyzer.",
    )


def test_the_report_states_both_engines_versions_and_the_snapshot_hash() -> None:
    text = report_text(inputs(100.0))

    assert "NautilusTrader 1.231.0" in text
    assert "engine 8, fill model 1, artifact schema 2" in text
    assert "crate 0.1.0" in text
    assert "2026-07-31 to 2026-08-31" in text
    assert "76404e438da6c161b37d913aae048a74867f6270ef87c9bfdf080deeaa2f3c58" in text
    assert "a" * 64 in text
    assert "c" * 64 in text
    assert "1-minute bars identical: 28,980 of 28,980" in text


def test_the_report_counts_matches_and_classes_per_strategy() -> None:
    text = report_text(inputs(100.0))

    assert (
        "| market | NautilusTrader, open-high-low-close | 1 | 1 | 1 | 0 | 1 | 0 | 0 | 0 | 0 |"
        in text
    )
    assert "bar_boundary" in text
    assert "No export under xcheck/nt8/export" in text


def test_an_unknown_difference_is_counted_and_refuses_the_report() -> None:
    assert unknown_count(inputs(100.0)) == 0
    assert unknown_count(inputs(100.5)) == 1
    assert "unknown: 1" in report_text(inputs(100.5))
