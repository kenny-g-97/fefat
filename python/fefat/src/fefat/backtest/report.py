"""A run's report as text (step 2.12, `02` §7), which `Run.report()` prints: the run, the
fidelity era of its trade dates, its trades split by the fidelity of their entry, its main
metrics, and its fidelity check, the error bar of its days at lower fidelity, or why it has none.

    run.report()
"""

from decimal import Decimal

from fefat.backtest.metrics import (
    FidelityCheck,
    FidelityEra,
    FidelityRerun,
    Metrics,
    PeriodOutcome,
    RefusedCheck,
)
from fefat.backtest.record import RunRecord
from fefat.market.calendar import counted
from fefat.market.fidelity import fidelity_in_words

_NO_CHECK = (
    "No fidelity check: {why}, so nothing finer measures the error of the coarser days; it "
    "needs a trades or 1-second file in the store and a run whose fidelity setting reaches it, "
    "as a run without one does."
)


def report_text(record: RunRecord) -> str:
    """The report of the run `record` keeps."""
    metrics, eras = record.metrics, record.fidelity_eras
    return "\n\n".join(
        [
            _heading(record),
            "Fidelity eras\n" + "\n".join(_era_line(era) for era in eras),
            _split_by_fidelity(metrics, eras),
            _metrics(metrics),
            _check(metrics.fidelity_check, eras),
        ]
    )


def _heading(record: RunRecord) -> str:
    spec, window = record.strategy.spec, record.window
    return (
        f"Run {record.run_key[:12]} of {record.instrument.root} {spec['timeframe']} bars from "
        f"{window.start} to {window.end}\nEach trade date filled on its finest data at or "
        f"coarser than {record.config.fidelity}; signal bars built from {record.signal_source}."
    )


def _era_line(era: FidelityEra) -> str:
    return (
        f"  {era.first} to {era.last}  {counted(era.trade_dates, 'trade date'):>16}  {era.fidelity}"
    )


def _split_by_fidelity(metrics: Metrics, eras: tuple[FidelityEra, ...]) -> str:
    lines = ["Trades by the fidelity of their entry"]
    for fidelity, group in metrics.breakdowns.fidelity.items():
        days = sum(era.trade_dates for era in eras if era.fidelity == fidelity)
        lines.append(
            f"  {fidelity!s:<7} {counted(group.trades, 'trade')}, {counted(group.wins, 'win')}, "
            f"P&L {_money(group.pnl)}, over {counted(days, 'trade date')}"
        )
    if len(lines) == 1:
        lines.append("  none")
    return "\n".join(lines)


def _metrics(metrics: Metrics) -> str:
    trades, drawdown, daily = metrics.trades, metrics.drawdown, metrics.daily
    robustness = metrics.robustness
    flags = ", ".join(flag.id for flag in robustness.red_flags) or "none"
    return "\n".join(
        [
            "Metrics",
            f"  {counted(trades.trades, 'trade')}, {counted(trades.wins, 'win')}, win rate "
            f"{_share(trades.win_rate)}, profit factor {_ratio(trades.profit_factor)}, "
            f"expectancy {_ratio(trades.expectancy)}",
            f"  Net P&L {_money(metrics.pnl)}; at one more tick of slippage "
            f"{_money(metrics.pnl_at_plus_one_tick)}",
            f"  Maximum drawdown {_money(drawdown.max_drawdown)} "
            f"({_share(drawdown.max_drawdown_share)} of the capital), longest "
            f"{counted(drawdown.longest_drawdown_days, 'day')} under a peak",
            f"  Sharpe {_ratio(daily.sharpe)}, Sortino {_ratio(daily.sortino)}",
            f"  Robustness {robustness.total_score} of 100: {robustness.verdict}; red flags: "
            f"{flags}",
        ]
    )


def _check(check: FidelityCheck | RefusedCheck | None, eras: tuple[FidelityEra, ...]) -> str:
    if check is None:
        levels = {str(era.fidelity) for era in eras}
        why = "no trade date ran finer than a minute"
        if len(levels) == 1:
            why = f"every trade date ran at {fidelity_in_words(levels.pop())} fidelity"
        return _NO_CHECK.format(why=why)
    if isinstance(check, RefusedCheck):
        return (
            f"Fidelity check from {check.first} to {check.last} refused at {check.fidelity}: "
            f"{check.refused}"
        )
    return "\n".join(
        [
            f"Fidelity check from {check.first} to {check.last}, each run from flat",
            f"  {check.baseline.fidelity} (baseline): {_outcome(check.baseline)}",
            *_rerun_lines(check.at_one_second),
            *_rerun_lines(check.at_one_minute),
        ]
    )


def _outcome(outcome: PeriodOutcome) -> str:
    return (
        f"{counted(outcome.trades, 'trade')}, P&L {_money(outcome.pnl)}, maximum drawdown "
        f"{_money(outcome.max_drawdown)}"
    )


def _rerun_lines(rerun: FidelityRerun) -> list[str]:
    outcome = rerun.outcome
    entries = [abs(price.entry_ticks) for price in rerun.fill_prices]
    exits = [abs(price.exit_ticks) for price in rerun.fill_prices if price.exit_ticks is not None]
    return [
        f"  at {outcome.fidelity}: {counted(outcome.trades, 'trade')} ({rerun.trades_delta:+d}), "
        f"P&L {_money(outcome.pnl)} ({_money(rerun.pnl_delta, signed=True)}), maximum drawdown "
        f"{_money(outcome.max_drawdown)} ({_money(rerun.max_drawdown_delta, signed=True)})",
        f"    {counted(len(entries), 'trade')} matched, {rerun.unmatched_trades} of the "
        f"baseline's and {rerun.extra_trades} of the rerun's alone",
        f"    fill prices apart: entries {_ticks(entries)}; exits {_ticks(exits)}",
    ]


def _ticks(differences: list[float]) -> str:
    if not differences:
        return "none"
    mean = sum(differences) / len(differences)
    return f"{mean:.2f} ticks on average, at most {max(differences):.2f}"


def _money(amount: Decimal, signed: bool = False) -> str:
    return f"{amount:+,.2f}" if signed else f"{amount:,.2f}"


def _share(share: float | None) -> str:
    return "none" if share is None else f"{share:.1%}"


def _ratio(ratio: float | None) -> str:
    return "none" if ratio is None else f"{ratio:.2f}"
