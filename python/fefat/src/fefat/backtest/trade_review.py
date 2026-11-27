"""A run's trades on a window of its chart (step 5.9, D-93): the trade review of the app, and of
a notebook, reads a page of bars and asks which of the run's trades show on it, with their fills
placed on the bars they belong to, their stop and target levels, and the strategy's features
beside the bars.

    window = review_window(run, bars)  # bars with ts_open and ts_close, as `load` gives them
    window.trades; window.fills; window.features; window.distances

A fill belongs on the bar its time falls in by F-BAR-06 (`fills_on_bars`); a trade shows when one
of its fills lies on the window, or when it spans it; and a feature is read at each bar's close,
when it is known (D-12). A feature the strategy's exit rules read as a distance, such as the ATR
of an ATR stop, is in the instrument's units; every other feature is as the signals hold it."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import polars as pl

from fefat.backtest.artifacts import scan_artifact
from fefat.market.engine_units import instrument_parameters, price_in_units
from fefat.market.fidelity import TickFidelity

if TYPE_CHECKING:
    from fefat.backtest.runs import Run

_PRINTS = tuple(str(fidelity) for fidelity in TickFidelity)
_DISTANCE = "atr"


@dataclass(frozen=True)
class ReviewWindow:
    """The run's trades on a window of bars: `trades`, its trades' rows with `trade`, their row
    in the trades artifact, and their levels, `stop_first`, `stop_last`, and `targets`, in 1e-9
    units; `fills`, every fill of those trades with `trade` and `bar_open`, the open of the bar
    it lies on, null off the window; `features`, one row a bar, its `ts_close` and each feature;
    and `distances`, the features in the instrument's units, the others as the signals hold
    them; `left_out`, the features no chart can draw, by name."""

    trades: pl.DataFrame
    fills: pl.DataFrame
    features: pl.DataFrame
    distances: tuple[str, ...]
    left_out: tuple[str, ...]


def fills_on_bars(fills: pl.DataFrame, bars: pl.DataFrame) -> pl.DataFrame:
    """`fills` with `bar_open`, the open of the bar of `bars` each lies on, null for a fill before
    the first, after the last, or in a break (F-BAR-06): a fill on a bar carries that bar's close,
    so a fill of a finer bar lies on the bar with `ts_open < ts <= ts_close`, and a trade print,
    at its own instant, on the bar with `ts_open <= ts < ts_close`. `bars` holds `ts_open` and
    `ts_close`; the fills keep their order."""
    on_a_print = pl.col("fidelity").is_in(_PRINTS)
    keyed = fills.with_row_index("_row").with_columns(
        _key=pl.when(on_a_print).then(pl.col("ts")).otherwise(pl.col("ts") - 1)
    )
    candles = bars.select(_open="ts_open", _close="ts_close").sort("_open")
    placed = keyed.sort("_key").join_asof(
        candles, left_on="_key", right_on="_open", strategy="backward"
    )
    return (
        placed.with_columns(
            bar_open=pl.when(pl.col("_key") < pl.col("_close")).then(pl.col("_open"))
        )
        .sort("_row")
        .drop("_row", "_key", "_open", "_close")
    )


def distance_features(spec: Mapping[str, Any]) -> tuple[str, ...]:
    """The features the exit rules of the strategy's `spec` read as a distance in the bars' 1e-9
    units of price (F-RND-01): those of an ATR stop, ATR targets, and an ATR trail, once each."""
    execution = spec.get("execution", {})
    rules = [execution.get("stop")]
    rules += [target.get("price") for target in execution.get("targets", [])]
    trailing = execution.get("trailing")
    rules.append(None if trailing is None else trailing.get("by"))
    named = [rule["feature"] for rule in rules if rule is not None and rule["kind"] == _DISTANCE]
    return tuple(dict.fromkeys(named))


def review_window(run: "Run", bars: pl.DataFrame) -> ReviewWindow:
    """The trades of `run` on the window of `bars`, which hold `ts_open` and `ts_close` and are
    in order (module docstring)."""
    fills = fills_on_bars(_traded_fills(run), bars)
    trades = run.trades.with_row_index("trade").with_columns(pl.col("trade").cast(pl.Int64))
    if bars.is_empty():
        shown = trades.clear()
    else:
        first, last = bars.item(0, "ts_open"), bars.item(-1, "ts_close")
        on_it = fills.filter(pl.col("bar_open").is_not_null()).get_column("trade")
        spanning = (pl.col("entry_ts") < first) & (pl.col("exit_ts") > last)
        shown = trades.filter(pl.col("trade").is_in(on_it.implode()) | spanning)
    features, left_out = _features(run, bars)
    return ReviewWindow(
        trades=_with_levels(run, shown),
        fills=fills.filter(pl.col("trade").is_in(shown.get_column("trade").implode())),
        features=features,
        distances=distance_features(run.record.strategy.spec),
        left_out=left_out,
    )


def _traded_fills(run: "Run") -> pl.DataFrame:
    """Each fill of each trade, with the trade's row: the trade paths' fill points, read without
    their minute marks, joined to the fills on their order and instant, a fill that reverses a
    position under both of its trades (S-fill-042), by trade and then by instant."""
    # shortcut: every page reads the fill points of the whole run, a scan of the paths' minute
    # marks too; keep them per run folder if a profile of a run of multi-day holds shows it.
    points = (
        scan_artifact(run.folder, "trade_paths")
        .filter(pl.col("kind") == "fill")
        .select("trade", "order", "ts")
        .collect()
    )
    return points.join(run.fills, on=["order", "ts"], how="inner").sort("trade", "ts", "order")


def _with_levels(run: "Run", trades: pl.DataFrame) -> pl.DataFrame:
    """`trades` with their stop's first level, `entry_price` less the initial risk for a long
    and plus it for a short, null without a stop; their stop's last level and their targets',
    each leg's last order of its role by id, as the orders artifact holds its last state."""
    tick = instrument_parameters(run.record.instrument).tick
    risk = pl.col("initial_risk_ticks") * tick
    first = pl.when(pl.col("side") == "long").then(pl.col("entry_price") - risk)
    legs = (
        run.orders.filter(pl.col("bracket_of").is_in(trades.get_column("entry_order").implode()))
        .sort("id")
        .group_by("bracket_of", "role")
        .agg(pl.col("price").last())
        .sort("role")
        .group_by("bracket_of")
        .agg(
            stop_last=pl.col("price").filter(pl.col("role") == "stop").first(),
            targets=pl.col("price").filter(pl.col("role").str.starts_with("target_")),
        )
    )
    return trades.with_columns(stop_first=first.otherwise(pl.col("entry_price") + risk)).join(
        legs, left_on="entry_order", right_on="bracket_of", how="left", maintain_order="left"
    )


def _features(run: "Run", bars: pl.DataFrame) -> tuple[pl.DataFrame, tuple[str, ...]]:
    """The strategy's features at each bar's close, null where the signals hold none, each a
    number: a distance in the instrument's units, any other as the signals hold it; and the
    features of another type, which no chart draws, by name."""
    names = run.record.strategy.features
    closes = bars.select("ts_close")
    if bars.is_empty() or not names:
        return closes, ()
    signals = scan_artifact(run.folder, "signals")
    schema = signals.collect_schema()
    missing = [name for name in names if name not in schema]
    if missing:
        raise ValueError(
            f"Expected the features {', '.join(names)} among the signals of run "
            f"{run.hash[:12]}, got none of {', '.join(missing)}."
        )
    drawn = tuple(name for name in names if schema[name].is_numeric() or schema[name] == pl.Boolean)
    rows = (
        signals.select("ts_close", *drawn)
        .filter(pl.col("ts_close").is_between(bars.item(0, "ts_close"), bars.item(-1, "ts_close")))
        .collect()
    )
    distances = distance_features(run.record.strategy.spec)
    aligned = closes.join(rows, on="ts_close", how="left", maintain_order="left")
    values = [
        price_in_units(name) if name in distances else pl.col(name).cast(pl.Float64)
        for name in drawn
    ]
    left_out = tuple(name for name in names if name not in drawn)
    return aligned.select("ts_close", *values), left_out
