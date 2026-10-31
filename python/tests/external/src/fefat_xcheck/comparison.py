"""Assembling the report from the xcheck folder: FEFAT's exports, NautilusTrader's results under
both bar paths, and NinjaTrader 8's export when the builder has saved one, each engine's trades
classified against FEFAT's over the 1-minute bars both filled on."""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import polars as pl

from fefat_xcheck.classify import TRADE_COLUMNS, classify
from fefat_xcheck.conventions import (
    NAUTILUS_ADAPTIVE,
    NAUTILUS_OHLC,
    NINJATRADER,
    EngineConventions,
)
from fefat_xcheck.nt8_export import read_export
from fefat_xcheck.report import (
    EngineReport,
    ReportInputs,
    StrategyReport,
    report_text,
    unknown_count,
)

NAUTILUS_FOLDER, NINJATRADER_FOLDER, EXPORT_FOLDER = "nautilus", "nt8", "export"
NAUTILUS_PATHS = (("ohlc", NAUTILUS_OHLC), ("adaptive", NAUTILUS_ADAPTIVE))
FEFAT_EXIT_REASONS = {"target_1": "target"}
"""FEFAT's exit roles (F-TAG-01) as the comparison names them; `stop` and `flat_by` are alike."""
MICRO_UNITS_PER_UNIT = 1_000_000
PRICE_COLUMNS = ("open", "high", "low", "close", "volume")


def write_report(xcheck: Path, out: Path) -> int:
    """Write the report of every comparison under `xcheck` to `out` and return the trades left
    `unknown`."""
    inputs = comparison_inputs(xcheck)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report_text(inputs), encoding="utf-8", newline="\n")
    return unknown_count(inputs)


def comparison_inputs(xcheck: Path) -> ReportInputs:
    nautilus_folder = xcheck / NAUTILUS_FOLDER
    fefat = _json(nautilus_folder / "fefat" / "fefat.json")
    cut = _json(nautilus_folder / "cut.json")
    exports = sorted((xcheck / NINJATRADER_FOLDER / EXPORT_FOLDER).glob("*.csv"))
    ninjatrader = ninjatrader_report(xcheck / NINJATRADER_FOLDER, exports[-1]) if exports else None
    pending = (
        f"No export found under `xcheck/{NINJATRADER_FOLDER}/{EXPORT_FOLDER}/` of FEFAT's home: "
        "run `FefatCrossCheck.cs` in the Strategy Analyzer and export its trades there, as "
        "`python/tests/external/README.md` describes, then `just xcheck` again."
    )
    return ReportInputs(
        written_on=date.today(),
        fefat=fefat,
        cut=cut,
        nautilus=nautilus_report(nautilus_folder, fefat),
        ninjatrader=ninjatrader,
        ninjatrader_pending=pending,
    )


def nautilus_report(folder: Path, fefat: dict[str, Any]) -> EngineReport:
    engine = _json(folder / "engine" / "nautilus.json")
    fefat_bars = pl.read_parquet(folder / "fefat" / "bars_1m.parquet")
    nautilus_bars = pl.read_parquet(folder / "engine" / "bars_1m.parquet")
    tick = int(fefat["instrument"]["tick"])
    strategies = []
    checks = [bars_check(fefat_bars, nautilus_bars, "NautilusTrader")]
    for strategy in fefat["strategies"]:
        ours = fefat_trades(folder / "fefat", strategy)
        signals = pl.read_parquet(folder / "fefat" / f"signals_{strategy['name']}.parquet")
        for order_name, conventions in NAUTILUS_PATHS:
            name = f"{strategy['name']}_{order_name}"
            theirs = pl.read_parquet(folder / "engine" / f"trades_{name}.parquet")
            decisions = pl.read_parquet(folder / "engine" / f"decisions_{name}.parquet")
            if order_name == NAUTILUS_PATHS[0][0]:
                checks.append(decisions_check(signals, decisions, strategy["name"]))
            strategies.append(
                _strategy_report(strategy, conventions, ours, theirs, fefat_bars, tick)
            )
    venue = engine["venue"]
    settings = (
        f"Venue {venue['name']}: OMS {venue['oms_type']}, {venue['account_type']} account, "
        f"`bar_execution` {venue['bar_execution']}, fill model `prob_fill_on_limit` "
        f"{venue['fill_model']['prob_fill_on_limit']} and `prob_slippage` "
        f"{venue['fill_model']['prob_slippage']}, fee model {venue['fee_model']}, no latency "
        f"model, `reject_stop_orders` {venue['reject_stop_orders']} (a stop through the market "
        "fills at once, as F-STP-05 fills it), `bar_adaptive_high_low_ordering` off and on.",
        f"Bars: the 1-minute bars of the cut as `{engine['bar_type']}`'s source, "
        f"{engine['bars']:,} loaded, with `time_bars_build_delay` "
        f"{engine['data_engine']['time_bars_build_delay']} µs so that the 1-minute bar stamped "
        "at a 5-minute boundary joins the 5-minute bar closing there, and "
        f"`time_bars_build_with_no_updates` {engine['data_engine']['time_bars_build_with_no_updates']}.",
        "Orders: each entry and its stop and target as one bracket list (OCO), the target not "
        "post-only, the flat-by a market order closing the position after every working order "
        "is cancelled; a resting entry is cancelled at the next decision.",
    )
    return EngineReport(
        engine=f"NautilusTrader {engine['nautilus_trader']}",
        settings=settings,
        data_checks=tuple(checks),
        strategies=tuple(strategies),
    )


def ninjatrader_report(folder: Path, export: Path) -> EngineReport:
    facts = _json(folder / "fefat" / "fefat.json")
    (strategy,) = facts["strategies"]
    tick = int(facts["instrument"]["tick"])
    bars = pl.read_parquet(folder / "fefat" / "bars_1m.parquet")
    signals = pl.read_parquet(folder / "fefat" / f"signals_{strategy['name']}.parquet")
    ours = fefat_trades(folder / "fefat", strategy)
    exported = read_export(export, point_value=Decimal(facts["instrument"]["point_value"]))
    theirs = (
        exported.join(
            signals.select("ts_close", "stop_price", "target_price"),
            left_on="entry_decision",
            right_on="ts_close",
            how="left",
        )
        .select(list(TRADE_COLUMNS))
        .cast(TRADE_COLUMNS)
    )
    on_grid = exported.filter(pl.col("entry_decision").is_in(signals["ts_close"])).height
    checks = (
        f"NinjaTrader 8's trades read from `{export.name}`: {exported.height:,} trades, of which "
        f"{on_grid:,} were decided on a 5-minute close of FEFAT's grid (a market fill stamped "
        "with the next minute, H1); commission as exported "
        f"{exported['commission'].sum():,.2f} USD, not compared.",
        f"Data: the store's NinjaTrader import of {facts['instrument']['contract']} "
        f"(`{facts['snapshot']['dataset']}`, snapshot `{facts['snapshot']['sha256']}` of the "
        f"request {facts['snapshot']['first']} to {facts['snapshot']['last']}), NinjaTrader's "
        "own history exported on 2026-10-13, which the Strategy Analyzer also reads.",
    )
    settings = (
        "Strategy Analyzer: `FefatCrossCheck.cs` on MNQ 09-26, a 5-minute series, order fill "
        "resolution High on 1-minute bars, slippage 0, limit orders filled on touch, exit on "
        "session close off, GTC; the strategy's stop and target are Set() orders at prices from "
        "the signal bar's close, its flat-by an exit at the market named `FlatBy`.",
    )
    report = _strategy_report(strategy, NINJATRADER, ours, theirs, bars, tick)
    return EngineReport(
        engine="NinjaTrader 8 (the builder's installed platform)",
        settings=settings,
        data_checks=checks,
        strategies=(report,),
    )


def _strategy_report(
    strategy: dict[str, Any],
    conventions: EngineConventions,
    ours: pl.DataFrame,
    theirs: pl.DataFrame,
    bars: pl.DataFrame,
    tick: int,
) -> StrategyReport:
    classified = classify(ours, theirs, bars, conventions, tick)
    return StrategyReport(
        strategy=strategy["name"],
        conventions=conventions,
        classified=classified,
        fefat_gross_pnl=float(ours["gross_pnl"].sum()),
        other_gross_pnl=float(theirs["gross_pnl"].sum()),
    )


def fefat_trades(folder: Path, strategy: dict[str, Any]) -> pl.DataFrame:
    """A FEFAT run's trades in the comparison's columns: the bracket's levels from the signal
    frame's row of the entry's decision, the exit's average price as the one lot's, and the
    gross profit and loss in the instrument's currency."""
    trades = pl.read_parquet(folder / f"trades_{strategy['name']}.parquet")
    signals = pl.read_parquet(folder / f"signals_{strategy['name']}.parquet")
    levels = signals.select("ts_close", "stop_price", "target_price")
    return (
        trades.join(levels, left_on="entry_decision", right_on="ts_close", how="left")
        .select(
            "entry_decision",
            "side",
            pl.lit(strategy["entry"]).alias("entry_kind"),
            "entry_ts",
            "entry_price",
            "exit_ts",
            pl.col("exit_price").round().cast(pl.Int64),
            pl.col("exit_reason").replace(FEFAT_EXIT_REASONS),
            "stop_price",
            "target_price",
            (pl.col("gross_pnl") / MICRO_UNITS_PER_UNIT).cast(pl.Float64),
        )
        .cast(TRADE_COLUMNS)
        .sort("entry_decision")
    )


def bars_check(fefat_bars: pl.DataFrame, other_bars: pl.DataFrame, engine: str) -> str:
    """Whether both engines filled on the same 1-minute bars: FEFAT's bars of the window against
    the other engine's as loaded, by close instant."""
    joined = fefat_bars.join(other_bars, on="ts_close", how="inner", suffix="_other")
    equal = joined.filter(
        pl.all_horizontal(pl.col(name) == pl.col(f"{name}_other") for name in PRICE_COLUMNS)
    ).height
    return (
        f"1-minute bars identical: {equal:,} of {fefat_bars.height:,} FEFAT bars of the window "
        f"equal {engine}'s by open, high, low, close, and volume ({other_bars.height:,} bars "
        f"loaded by {engine} over the cut's dates)."
    )


def decisions_check(signals: pl.DataFrame, decisions: pl.DataFrame, strategy: str) -> str:
    """Whether both engines decided on the same 5-minute closes: FEFAT's signal rows with a bar
    against the other engine's decisions."""
    with_bars = signals.filter(~pl.col("empty_bucket"))
    joined = with_bars.join(decisions, on="ts_close", how="inner")
    equal = joined.filter(pl.col("signal_close") == pl.col("close")).height
    empty = signals.height - with_bars.height
    return (
        f"5-minute closes identical ({strategy}): {equal:,} of {with_bars.height:,} FEFAT "
        f"decisions on a bar find NautilusTrader's decision at the same instant with the same "
        f"close; {empty:,} rows of FEFAT's grid are empty buckets without a bar, on which "
        "NautilusTrader builds no bar."
    )


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
