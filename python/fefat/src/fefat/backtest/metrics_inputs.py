"""What a run's metrics read (step 2.11, `fefat_metrics::inputs`), from its artifacts and its
inputs, as the JSON `fefat_engine.metrics` takes: each trade's money, lots, initial risk, and
excursions, the trade date of its entry's fill, that fill's hour in the exchange's time zone and
its fidelity, and the role of the fill that left it flat; the account after each decision with
its trade date; the capital, the instrument's tick and point value, the window, one trial, the
share of the capital a large daily loss loses, the profit and loss of the rerun at one more tick,
the strategy's parameters, and whether the run pays friction. Money is in micro-units and prices
in 1e-9 units, as the artifacts hold them."""

import json
from collections.abc import Mapping
from decimal import Decimal

import polars as pl

from fefat.backtest.record import Window
from fefat.market.engine_units import InstrumentParameters
from fefat.reference.run_documents import rate_units
from fefat.strategy.spec import Execution

LARGE_DAILY_LOSS = Decimal("0.02")
"""The share of the capital a day must lose to be a large daily loss (D-63): 1,000 of 50,000."""
TRIALS = 1
"""The trials behind a run on its own; sweeps count theirs from Phase 3 (`02` §9)."""


def metrics_inputs_json(
    artifacts: Mapping[str, pl.DataFrame],
    *,
    capital: int,
    instrument: InstrumentParameters,
    window: Window,
    time_zone: str,
    pnl_at_plus_one_tick: int,
    parameters: int,
    friction_tested: bool,
) -> str:
    """The metrics' inputs of the run whose artifacts are `artifacts`, its capital in
    micro-units, on `instrument`, over `window`, its exchange keeping `time_zone`."""
    return json.dumps(
        {
            "capital": capital,
            "instrument": {
                "tick_size": instrument.tick,
                "money_per_point": instrument.money_per_point,
            },
            "trials": TRIALS,
            "large_daily_loss": rate_units(LARGE_DAILY_LOSS),
            "pnl_at_plus_one_tick": pnl_at_plus_one_tick,
            "window": {"start": window.start.isoformat(), "end": window.end.isoformat()},
            "parameters": parameters,
            "friction_tested": friction_tested,
            "trades": _trades(artifacts["trades"], artifacts["fills"], time_zone),
            "equity": _equity(artifacts["equity"]),
        }
    )


def _trades(trades: pl.DataFrame, fills: pl.DataFrame, time_zone: str) -> list[dict[str, object]]:
    """Each trade as the metrics read it, with its entry's fidelity, the first fill of its
    entry order's, and the hour of its entry's fill in `time_zone`."""
    entries = fills.select(pl.col("order").alias("entry_order"), "fidelity").unique(
        "entry_order", keep="first", maintain_order=True
    )
    entry_hour = (
        pl.from_epoch("entry_ts", time_unit="ns")
        .dt.replace_time_zone("UTC")
        .dt.convert_time_zone(time_zone)
        .dt.hour()
    )
    joined = trades.join(entries, on="entry_order", how="left", maintain_order="left")
    return joined.select(
        "pnl",
        "gross_pnl",
        "lots",
        "initial_risk",
        "mae_ticks",
        "mfe_ticks",
        pl.col("entry_trade_date").dt.to_string("%Y-%m-%d"),
        entry_hour.alias("entry_hour"),
        "exit_reason",
        "fidelity",
    ).to_dicts()


def _equity(equity: pl.DataFrame) -> list[dict[str, object]]:
    """The account after each decision that values it, with the decision's trade date."""
    valued = equity.filter(pl.col("equity").is_not_null())
    return valued.select(pl.col("trade_date").dt.to_string("%Y-%m-%d"), "equity").to_dicts()


def parameters_of(execution: Execution) -> int:
    """The parameters of an execution template, as the robustness summary counts them: the
    numbers it sets apart from their defaults, such as a stop's ticks, a target's, and the lots
    of a fixed size. A strategy's features and the template's times of day are not counted."""
    return _numbers(execution.model_dump(exclude_defaults=True))


def _numbers(value: object) -> int:
    """The numbers in `value`, a model's dump, a flag not being one."""
    if isinstance(value, bool):
        return 0
    if isinstance(value, int | float | Decimal):
        return 1
    if isinstance(value, dict):
        return sum(_numbers(nested) for nested in value.values())
    if isinstance(value, list | tuple):
        return sum(_numbers(nested) for nested in value)
    return 0
