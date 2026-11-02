"""The counts of a strategy's trades on prints and on 1-minute bars once classified (step 2.16,
`fefat.backtest.fidelity_classes`): what the tick check's report tabulates."""

from collections import Counter
from dataclasses import dataclass

import polars as pl

from fefat.backtest.fidelity_classes import MATCH, FidelityClass


@dataclass(frozen=True)
class FidelitySummary:
    """One strategy's classified trades in numbers: each run's trades, the pairs matched by
    decision and side, the pairs whose two fills matched, those whose exits matched, the fills of
    the pairs (two a pair) and those equal, the differing trades by class, the differing fills by
    class, a pair's each and a lone trade's two, and the trades left unknown."""

    tick_trades: int
    minute_trades: int
    matched: int
    exact: int
    exits_alike: int
    fills_compared: int
    equal_fills: int
    trades_by_class: dict[str, int]
    fills_by_class: dict[str, int]
    unknown: int


def summarise(classified: pl.DataFrame) -> FidelitySummary:
    """The counts of one strategy's classified trades."""
    paired = classified.filter(pl.col("in_ticks") & pl.col("in_minutes"))
    alone = classified.filter(~(pl.col("in_ticks") & pl.col("in_minutes")))
    pair_fills = [*paired.get_column("entry_outcome"), *paired.get_column("exit_outcome")]
    fills = Counter(outcome for outcome in pair_fills if outcome != MATCH)
    for outcome in alone.get_column("outcome"):
        fills[outcome] += 2
    differing = classified.filter(pl.col("outcome") != str(MATCH)).get_column("outcome")
    return FidelitySummary(
        tick_trades=int(classified["in_ticks"].sum()),
        minute_trades=int(classified["in_minutes"].sum()),
        matched=paired.height,
        exact=paired.filter(pl.col("outcome") == str(MATCH)).height,
        exits_alike=paired.filter(pl.col("exit_outcome") == str(MATCH)).height,
        fills_compared=len(pair_fills),
        equal_fills=pair_fills.count(str(MATCH)),
        trades_by_class=dict(sorted(Counter(differing.to_list()).items())),
        fills_by_class=dict(sorted(fills.items())),
        unknown=int((differing == str(FidelityClass.UNKNOWN)).sum()),
    )
