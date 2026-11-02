"""A run's fidelity check (step 2.12, `02` §1.6): the error bar of its days at lower fidelity.
The period that its trade dates finer than a minute span, from the first to the last, runs from
flat at the run's own fidelity, the baseline, and again at 1-second and at 1-minute fidelity,
each trade date on its finest level at or coarser than that (D-58) and every other setting the
run's, so that the data alone differs (F-SLP-01). Each rerun reports its trades, their net profit
and loss, and its maximum drawdown, the capital first (D-63), the differences from the baseline,
and how far the fill prices of the trades both entered at one decision on one side lie from the
baseline's, in ticks. The baseline of a period that is the run's whole window is the run itself.
A period without 1-second bars has no rerun at 1 second, whose trade dates would all fill on the
1-minute bars, as the rerun at 1 minute does. A run without trade dates finer than a minute has
no check; a rerun the engine refuses, as on a
trade date of ticks without bars, refuses the check with the engine's message, not the run.

    run.metrics.fidelity_check         # worked out by every ff.backtest.run
    ff.backtest.fidelity_check(run)    # again, from a saved run on the data it read
"""

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

import fefat_engine
import polars as pl

from fefat.backtest.explain import pinned_snapshots
from fefat.backtest.metrics import (
    FidelityCheck,
    FidelityEra,
    FidelityRerun,
    FillPriceDifference,
    PeriodOutcome,
    RefusedCheck,
    running_drawdown,
)
from fefat.backtest.record import Window
from fefat.backtest.run_inputs import engine_cache_folder
from fefat.config import resolve_paths
from fefat.market.engine_units import micro_units, money_text
from fefat.market.fidelity import ONE_MINUTE, ONE_SECOND, TickFidelity
from fefat.market.schema import Timeframe
from fefat.market.store import Store
from fefat.reference.settings import Replay
from fefat.reference.units import day_number

if TYPE_CHECKING:
    from fefat.backtest.runs import Run


@dataclass(frozen=True)
class PeriodRun:
    """A period run at one fidelity: its trades and the account after each decision, as the
    engine or the run's artifacts give them, and the fidelity eras of its trade dates."""

    fidelity: TickFidelity | Timeframe
    trades: pl.DataFrame
    equity: pl.DataFrame
    eras: tuple[FidelityEra, ...]

    def outcome(self, capital: int) -> PeriodOutcome:
        """Its trades, their net profit and loss, and its maximum drawdown from `capital`."""
        return PeriodOutcome(
            fidelity=self.fidelity,
            eras=self.eras,
            trades=self.trades.height,
            pnl=_money(int(self.trades.get_column("pnl").sum())),
            max_drawdown=_money(_max_drawdown(self.equity, capital)),
        )


@dataclass(frozen=True)
class CheckedRun:
    """What the check reads of a run: its specification as JSON, its signal frame, the config
    the engine read, the folder of its contracts' engine caches, how it replays, its capital in
    micro-units, its window, and the run itself."""

    spec_json: str
    signals: pl.DataFrame
    engine_config: Mapping[str, Any]
    cache_folder: Path
    replay: Replay
    capital: int
    window: Window
    run: PeriodRun


class _RerunRefusedError(Exception):
    """The engine's refusal of a rerun at `fidelity`."""

    def __init__(self, fidelity: TickFidelity | Timeframe, message: str) -> None:
        super().__init__(message)
        self.fidelity = fidelity


def fidelity_check_of(checked: CheckedRun) -> FidelityCheck | RefusedCheck | None:
    """The fidelity check of `checked`, none without trade dates finer than a minute."""
    period = _period(checked.run.eras)
    if period is None:
        return None
    first, last = period
    try:
        baseline = _baseline(checked, period)
        seconds = baseline
        if checked.run.fidelity != ONE_SECOND:
            seconds = _rerun(checked, period, ONE_SECOND)
        minutes = _rerun(checked, period, ONE_MINUTE)
    except _RerunRefusedError as refused:
        return RefusedCheck(first=first, last=last, fidelity=refused.fidelity, refused=str(refused))
    capital, tick = checked.capital, int(checked.engine_config["instrument"]["tick_size"])
    on_seconds = any(era.fidelity == ONE_SECOND for era in seconds.eras)
    return FidelityCheck(
        first=first,
        last=last,
        baseline=baseline.outcome(capital),
        at_one_second=_against(seconds, baseline, capital, tick) if on_seconds else None,
        at_one_minute=_against(minutes, baseline, capital, tick),
    )


def fidelity_check(run: "Run") -> FidelityCheck | RefusedCheck | None:
    """The fidelity check of the saved `run` worked out again from its record and artifacts on
    the store's data, refused unless it is the data the run read: the check its metrics hold."""
    record = run.record
    paths = resolve_paths(os.environ)
    store = Store(paths.data_dir)
    pinned_snapshots(store, record)
    root_and_provider = (record.instrument.root, record.config.provider)
    timeframe = str(record.strategy.spec["timeframe"])
    itself = PeriodRun(
        record.config.fidelity, run.trades, run.equity(timeframe), record.fidelity_eras
    )
    fronts = run.signals.get_column("contract").unique(maintain_order=True).to_list()
    checked = CheckedRun(
        spec_json=json.dumps(record.strategy.spec),
        signals=run.signals,
        engine_config=record.engine_config,
        cache_folder=engine_cache_folder(store, paths, root_and_provider, record.window, fronts),
        replay=record.config.replay,
        capital=micro_units(record.config.capital),
        window=record.window,
        run=itself,
    )
    return fidelity_check_of(checked)


def _period(eras: Sequence[FidelityEra]) -> tuple[date, date] | None:
    """The first and the last trade date of the eras finer than a minute."""
    finer = [era for era in eras if _finer_than_a_minute(era.fidelity)]
    if not finer:
        return None
    return finer[0].first, finer[-1].last


def _finer_than_a_minute(fidelity: TickFidelity | Timeframe) -> bool:
    if isinstance(fidelity, Timeframe):
        return fidelity.nominal_seconds() < ONE_MINUTE.nominal_seconds()
    return True


def _baseline(checked: CheckedRun, period: tuple[date, date]) -> PeriodRun:
    """The run itself when the period is its window, which a rerun from flat would repeat; else
    the period rerun at the run's own fidelity."""
    if period == (checked.window.start, checked.window.end):
        return checked.run
    return _rerun(checked, period, checked.run.fidelity)


def _rerun(
    checked: CheckedRun, period: tuple[date, date], fidelity: TickFidelity | Timeframe
) -> PeriodRun:
    """The period's signal rows run from flat at `fidelity` on its fronts, with the rolls whose
    new front serves it from a trade date after its first (F-ROL-01)."""
    first, last = period
    rows = checked.signals.filter(pl.col("trade_date").is_between(first, last))
    fronts = rows.get_column("contract").unique(maintain_order=True).to_list()
    after, through = day_number(first), day_number(last)
    rolls = checked.engine_config["rolls"]
    within = [roll for roll in rolls if after < roll["trade_date"] <= through]
    config = {**checked.engine_config, "fidelity": str(fidelity), "rolls": within}
    folders = [str(checked.cache_folder / front) for front in fronts]
    spec, replay = checked.spec_json, str(checked.replay)
    try:
        ran = fefat_engine.run_signal_backtest(
            spec, rows, folders, json.dumps(config), replay, trade_paths=False
        )
    except ValueError as error:
        raise _RerunRefusedError(fidelity, str(error)) from error
    eras = tuple(FidelityEra.model_validate(era) for era in ran["summary"]["eras"])
    return PeriodRun(fidelity, pl.DataFrame(ran["trades"]), pl.DataFrame(ran["equity"]), eras)


def _against(rerun: PeriodRun, baseline: PeriodRun, capital: int, tick: int) -> FidelityRerun:
    """`rerun` against `baseline`, the rerun's values less the baseline's, its trades matched
    with the baseline's by the decision that entered them and their side, the n-th of each such
    pair with the n-th."""
    ours, theirs = rerun.outcome(capital), baseline.outcome(capital)
    keys = ["entry_decision", "side", "nth"]
    nth = pl.int_range(pl.len()).over("entry_decision", "side").alias("nth")
    columns = ["entry_decision", "side", "entry_price", "exit_price"]
    base = baseline.trades.select(columns).with_columns(nth)
    other = rerun.trades.select(columns).with_columns(nth)
    matched = base.join(other, on=keys, suffix="_rerun", maintain_order="left")
    entries = (pl.col("entry_price_rerun") - pl.col("entry_price")) / tick
    exits = (pl.col("exit_price_rerun") - pl.col("exit_price")) / tick
    differences = matched.select(
        pl.from_epoch("entry_decision", time_unit="ns").dt.replace_time_zone("UTC"),
        "side",
        entries.alias("entry_ticks"),
        exits.alias("exit_ticks"),
    )
    return FidelityRerun(
        outcome=ours,
        trades_delta=ours.trades - theirs.trades,
        pnl_delta=ours.pnl - theirs.pnl,
        max_drawdown_delta=ours.max_drawdown - theirs.max_drawdown,
        fill_prices=tuple(
            FillPriceDifference.model_validate(row) for row in differences.iter_rows(named=True)
        ),
        unmatched_trades=base.join(other, on=keys, how="anti").height,
        extra_trades=other.join(base, on=keys, how="anti").height,
    )


def _max_drawdown(equity: pl.DataFrame, capital: int) -> int:
    """The deepest fall of the account after each decision below a peak, the capital first, as
    the run's metrics measure it (`02` §7, D-63), in micro-units."""
    account = pl.Series("equity", [capital], dtype=pl.Int64)
    deepest = running_drawdown(account.append(equity.get_column("equity").drop_nulls())).max()
    if not isinstance(deepest, int):
        raise ValueError(f"Expected the deepest drawdown in micro-units, got {deepest!r}.")
    return deepest


def _money(units: int) -> Decimal:
    return Decimal(money_text(units))
