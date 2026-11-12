"""What the Rust engine reads of a run (step 2.10), written once for the batches of `fefat-cli
run` (`fefat.reference.rust_batch`) and for `ff.backtest`, which hands them to `fefat_engine`: the
run's config, as `fefat_run::config::RunConfig` reads it, its fidelity, instrument, settings,
trading hours, capital, opening position, fee table, funding rates, and rolls; and the columns
the Rust template reads beside a signal frame's own. Prices, rates, and money are integers in the
engines' units (D-51), instants nanoseconds since the Unix epoch, UTC, and dates days since
1970-01-01.

    config = run_document(fidelity=..., instrument=..., settings=..., hours=..., capital=...,
                          position=None, fees=None, funding=(), rolls=())
    frame = with_engine_columns(spec, signals, sessions)
"""

from collections.abc import Sequence
from decimal import Decimal

import polars as pl

from fefat.market.calendar import SessionTable
from fefat.market.fees import FuturesFee
from fefat.market.fidelity import TickFidelity
from fefat.market.schema import Timeframe
from fefat.reference.costs import RunFees
from fefat.reference.hours import AlwaysOpen, CalendarHours
from fefat.reference.rolls import RollRow
from fefat.reference.settings import RunSettings
from fefat.reference.tape import FundingRate
from fefat.reference.time_rules import with_time_rules
from fefat.reference.units import PRICE_DECIMALS, InstrumentParameters, day_number
from fefat.strategy.signal_frame import rule_features
from fefat.strategy.spec import StrategySpec

TIME_RULE_COLUMNS = ("flat_by", "in_window", "session_end", "week_end")
"""The columns of the time rules, as `with_time_rules` works them out (§26)."""
FEATURE_COLUMNS = (
    "stop_feature",
    "target_feature_1",
    "target_feature_2",
    "target_feature_3",
    "trail_feature",
)
"""The features an exit plan's rules name, under the names of their rules."""
ENGINE_COLUMNS = (*TIME_RULE_COLUMNS, *FEATURE_COLUMNS, "blackout")
"""Every column the Rust template reads beside a signal frame's own."""


def run_document(
    *,
    fidelity: TickFidelity | Timeframe,
    instrument: InstrumentParameters,
    settings: RunSettings,
    hours: AlwaysOpen | CalendarHours,
    capital: int,
    position: dict[str, object] | None,
    fees: RunFees | None,
    funding: Sequence[FundingRate],
    rolls: Sequence[RollRow],
) -> dict[str, object]:
    """A run's config, every setting applied: the finest data it fills on, its instrument, its
    settings, its hours, its capital in micro-units, the position held when its tape starts, its
    fee table, a perpetual's funding rates, and a future's rolls (`fefat_run::config`)."""
    return {
        "fidelity": str(fidelity),
        "instrument": instrument_document(instrument),
        "settings": settings_document(settings),
        "hours": hours_document(hours),
        "capital": capital,
        "position": position,
        "fees": fees_document(fees),
        "funding": [{"ts": rate.ts, "rate": rate_units(rate.rate)} for rate in funding],
        "rolls": [roll_document(roll) for roll in rolls],
    }


def rate_units(rate: Decimal) -> int:
    """A rate as a count of 1e-9 units, as the store holds a funding rate: 0.0001 is 100_000."""
    return _whole_units(rate, PRICE_DECIMALS, "a rate")


def _whole_units(value: Decimal, decimals: int, what: str) -> int:
    """`value` as a count of 10**-decimals, refused where it is finer than that."""
    units = value.scaleb(decimals)
    if units != units.to_integral_value():
        raise ValueError(f"Expected {what} in whole units of 1e-{decimals}, got {value}.")
    return int(units)


def fees_document(fees: RunFees | None) -> dict[str, object] | None:
    """The fee table, each schedule from its trade date in days since 1970-01-01: per contract
    per side in micro-units, or maker and taker rates in 1e-9 units."""
    if fees is None:
        return None
    schedules: list[dict[str, int]] = []
    for day, fee in fees.schedules:
        if isinstance(fee, FuturesFee):
            charge = _whole_units(fee.per_contract_side, 6, "a fee per contract per side")
            schedules.append({"effective_from": day, "per_contract_side": charge})
            continue
        rates = (rate_units(bps.scaleb(-4)) for bps in (fee.maker_bps, fee.taker_bps))
        maker, taker = rates
        schedules.append({"effective_from": day, "maker_rate": maker, "taker_rate": taker})
    kind = "futures" if isinstance(fees.schedules[0][1], FuturesFee) else "crypto"
    return {"kind": kind, "schedules": schedules}


def roll_document(roll: RollRow) -> dict[str, object]:
    """A roll as the roll calendar gives it, with the trade date from which its new front serves
    the run, in days since 1970-01-01."""
    return {
        "trade_date": day_number(roll.trade_date),
        "session_open": roll.session_open,
        "rolled_from": roll.rolled_from,
        "contract": roll.contract,
        "gap": roll.gap,
        "reason": str(roll.reason),
    }


def instrument_document(parameters: InstrumentParameters) -> dict[str, object]:
    """The instrument's tick and money a point in the engines' integers, its lot step in 1e-9
    units."""
    return {
        "tick_size": parameters.tick,
        "money_per_point": parameters.money_per_point,
        "lot_step": int(parameters.lot_step.scaleb(PRICE_DECIMALS)),
    }


def settings_document(settings: RunSettings) -> dict[str, object]:
    """The run settings of F-ACT-01, F-SLP-01, F-LMT-01, F-LMT-02, and F-ROL-04."""
    return {
        "latency_ms": settings.latency_ms,
        "slippage_ticks": {
            "market": settings.slippage_ticks.market,
            "stop": settings.slippage_ticks.stop,
        },
        "limit_fill": str(settings.limit_fill),
        "roll_handling": str(settings.roll_handling),
    }


def hours_document(hours: AlwaysOpen | CalendarHours) -> dict[str, object]:
    """When the market trades (F-SES-02): always, or in the sessions of a calendar, each with its
    halts."""
    if isinstance(hours, AlwaysOpen):
        return {"kind": "always"}
    sessions = [
        {
            "open": session.open,
            "close": session.close,
            "halts": [{"start": halt.start, "end": halt.end} for halt in session.halts],
        }
        for session in hours.sessions()
    ]
    return {"kind": "sessions", "sessions": sessions}


def with_engine_columns(
    spec: StrategySpec, frame: pl.DataFrame, sessions: SessionTable | None
) -> pl.DataFrame:
    """`frame`, a signal frame, in the order of its closes, with the columns the Rust template
    reads beside its own: those of its time rules, as `with_time_rules` works them out; each
    feature its exit plan's rules name, as float64 under the name of its rule; and the column its
    limits name for the blackout, as booleans under `blackout`. A frame already holding one of
    those columns, as a feature named `flat_by` would, is refused, since the engine would read it
    in its rule's place."""
    blackout = spec.execution.limits.blackout
    taken = sorted((set(frame.columns) & set(ENGINE_COLUMNS)) - {blackout})
    if taken:
        raise ValueError(
            "Expected a signal frame without the columns the engine reads for its rules, got "
            f"{', '.join(taken)}: give those features other names."
        )
    timed = with_time_rules(spec, frame.sort("ts_close"), sessions)
    return timed.with_columns(*_feature_columns(spec, frame), *_blackout(spec, frame))


def _blackout(spec: StrategySpec, frame: pl.DataFrame) -> list[pl.Expr]:
    blackout = spec.execution.limits.blackout
    if blackout is None:
        return []
    if blackout not in frame.columns:
        raise ValueError(
            f"Expected the signal frame's {blackout} for the blackout, got no such column."
        )
    return [pl.col(blackout).cast(pl.Boolean).alias("blackout")]


def exit_features(spec: StrategySpec) -> dict[str, str]:
    """The features the exit plan's rules read, each under the name of its rule's column:
    `stop_feature`, `target_feature_1` to `target_feature_3`, and `trail_feature`
    (`fefat.strategy.signal_frame.rule_features`, which the strategy's checks share)."""
    return rule_features(spec.execution)


def _feature_columns(spec: StrategySpec, frame: pl.DataFrame) -> list[pl.Expr]:
    """The features the exit plan's rules name, as float64 columns under the names of their
    rules. A feature the frame lacks stays out, and the Rust template refuses an entry that needs
    it, as the reference's does."""
    return [
        pl.col(feature).cast(pl.Float64).alias(column)
        for column, feature in exit_features(spec).items()
        if feature in frame.columns
    ]
