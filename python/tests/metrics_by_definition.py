"""A run's metrics worked out from their definitions (`02` §7, step 2.11) in plain Python, apart
from the engine's `fefat-metrics`, which `test_metrics_parity.py` compares with them. It reads the
inputs `fefat_engine.metrics` reads, as the dictionary of their JSON, and gives the dictionary of
the JSON it should write: money as decimals, trade dates as text, and every mean and ratio worked
out in exact fractions before it becomes a float. The robustness summary's scores, verdict, and
red flags are the backtest-expert skill's `evaluate_backtest.py`'s (`skill_script`) on the
inputs the summary records, which `robustness_by_definition` gives from their definitions."""

import importlib.util
from collections import defaultdict
from collections.abc import Callable, Sequence
from datetime import date
from decimal import Decimal
from fractions import Fraction
from functools import cache
from itertools import groupby
from math import ceil, e, floor, isinf, sqrt
from pathlib import Path
from statistics import NormalDist
from types import ModuleType
from typing import Any

MICRO_UNITS = 10**6
NANO_UNITS = 10**9
DAYS_PER_YEAR = 365.25
EULER_MASCHERONI = 0.5772156649015329
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
NORMAL = NormalDist()
SCRIPT = (
    Path(__file__).resolve().parents[2]
    / ".claude"
    / "skills"
    / "backtest-expert"
    / "scripts"
    / "evaluate_backtest.py"
)
DIMENSIONS = {
    "Sample Size": "sample_size",
    "Expectancy": "expectancy",
    "Risk Management": "risk_management",
    "Robustness": "robustness",
    "Execution Realism": "execution_realism",
}
VERDICTS = {"Deploy": "deploy_grade_evidence", "Refine": "refine", "Abandon": "abandon"}

type Json = dict[str, Any]


def money(units: int) -> Decimal:
    """Micro-units as the decimal of the currency: 25_000_000 is 25.000000."""
    return Decimal(units).scaleb(-6)


def ratio(part: int | Fraction, whole: int | Fraction) -> float | None:
    """`part` over `whole` as a float, none over nothing."""
    return float(Fraction(part) / whole) if whole else None


def percent(part: int, whole: int) -> float:
    """`part` over `whole` in percent, zero over nothing, as the script takes a run without
    trades, wins, or losses."""
    return float(Fraction(100 * part, whole)) if whole else 0.0


def metrics_by_definition(inputs: Json) -> Json:
    """The metrics of the run `inputs` describe."""
    trades = inputs["trades"]
    fall = drawdown(inputs["capital"], inputs["equity"])
    return {
        "trades": trade_statistics(trades, inputs["instrument"]),
        "daily": daily_statistics(inputs),
        "drawdown": fall,
        "pnl": money(sum(trade["pnl"] for trade in trades)),
        "pnl_at_plus_one_tick": money(inputs["pnl_at_plus_one_tick"]),
        "breakdowns": breakdowns(trades),
        "robustness": robustness_by_definition(inputs, fall),
    }


def robustness_by_definition(inputs: Json, fall: Json) -> Json:
    """The robustness summary but the script's own scores: the script's inputs, the trades and
    the win rate in percent, the average win, the average loss over the trades that did not win,
    and the drawdown in percent of the capital,
    the window's years rounded to the nearest, the parameters, and the friction; the sample size
    against 30, 100, and 200 trades; and the profit at one more tick of slippage."""
    capital = inputs["capital"]
    pnls = [trade["pnl"] for trade in inputs["trades"]]
    wins, losses = [pnl for pnl in pnls if pnl > 0], [pnl for pnl in pnls if pnl < 0]
    depth = int(fall["max_drawdown"].scaleb(6))
    window = inputs["window"]
    plus_one = inputs["pnl_at_plus_one_tick"]
    tiers = ((200, "high_confidence"), (100, "preferred"), (30, "minimum"), (0, "below_minimum"))
    return {
        "inputs": {
            "total_trades": len(pnls),
            "win_rate": percent(len(wins), len(pnls)),
            "avg_win_pct": percent(sum(wins), len(wins) * capital),
            "avg_loss_pct": percent(-sum(losses), (len(pnls) - len(wins)) * capital),
            "max_drawdown_pct": float(Fraction(100 * depth, capital)),
            "years_tested": floor(
                (days_between(window["start"], window["end"]) + 1) / 365.25 + 0.5
            ),
            "num_parameters": inputs["parameters"],
            "slippage_tested": inputs["friction_tested"],
        },
        "sample_size": next(tier for least, tier in tiers if len(pnls) >= least),
        "pnl_at_plus_one_tick": money(plus_one),
        "fragile_to_slippage": sum(pnls) > 0 and plus_one <= 0,
    }


@cache
def skill_script() -> ModuleType:
    """The backtest-expert skill's `evaluate_backtest.py`, imported from its file as its own
    tests import it."""
    spec = importlib.util.spec_from_file_location("evaluate_backtest", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def scripts_summary(script_inputs: Json) -> Json:
    """What the script gives on `script_inputs`, in the summary's words: its five scores in
    their order, its total and verdict, its red flags, and its profit factor, none where it is
    infinite, and expectancy."""
    result = skill_script().evaluate(**script_inputs)
    factor = result["profit_factor"]
    return {
        "dimensions": [
            {"name": DIMENSIONS[d["name"]], "score": d["score"], "max_score": d["max_score"]}
            for d in result["dimensions"]
        ],
        "total_score": result["total_score"],
        "verdict": VERDICTS[result["verdict"]],
        "red_flags": result["red_flags"],
        "profit_factor": None if isinf(factor) else factor,
        "expectancy": result["expectancy"],
    }


def ticks(amount: int, trade: Json, instrument: Json) -> Fraction:
    """`amount` in ticks of the trade's lots: over the value of one tick of them."""
    value = instrument["tick_size"] * instrument["money_per_point"] * trade["lots"]
    return amount / Fraction(value, NANO_UNITS)


def trade_statistics(trades: Sequence[Json], instrument: Json) -> Json:
    """Wins above zero, losses below; the profit factor, the expectancy in currency, ticks, and
    R; the averages; and the share of the range from the worst marks to the best that the exits
    kept."""
    pnls = [trade["pnl"] for trade in trades]
    wins = [pnl for pnl in pnls if pnl > 0]
    losses = [pnl for pnl in pnls if pnl < 0]
    risked = [Fraction(t["pnl"], t["initial_risk"]) for t in trades if t["initial_risk"]]
    in_ticks = [ticks(trade["pnl"], trade, instrument) for trade in trades]
    ranges = sum(trade["mae_ticks"] + trade["mfe_ticks"] for trade in trades)
    kept = sum(ticks(t["gross_pnl"], t, instrument) + t["mae_ticks"] for t in trades)
    return {
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": ratio(len(wins), len(trades)),
        "profit_factor": ratio(sum(wins), -sum(losses)),
        "expectancy": ratio(sum(pnls), len(trades) * MICRO_UNITS),
        "expectancy_ticks": ratio(sum(in_ticks, Fraction(0)), len(in_ticks)),
        "expectancy_r": ratio(sum(risked, Fraction(0)), len(risked)),
        "average_win": ratio(sum(wins), len(wins) * MICRO_UNITS),
        "average_loss": ratio(sum(losses), len(losses) * MICRO_UNITS),
        "mae_mfe_efficiency": ratio(kept, ranges),
    }


def daily_pnl(capital: int, equity: Sequence[Json]) -> list[tuple[str, int]]:
    """Each trade date's profit and loss: its last equity less the last before it, the first
    day's less the capital."""
    days = []
    before = capital
    for trade_date, points in groupby(equity, key=lambda point: point["trade_date"]):
        last = list(points)[-1]["equity"]
        days.append((trade_date, last - before))
        before = last
    return days


def daily_statistics(inputs: Json) -> Json:
    """The worst day, the best day's share, the CVaR of the worst twentieth of the days, the
    days losing at least the share of the capital, and the ratios of `sharpe_ratios`."""
    capital = inputs["capital"]
    days = daily_pnl(capital, inputs["equity"])
    pnls = [pnl for _, pnl in days]
    threshold = capital * inputs["large_daily_loss"] // NANO_UNITS
    large = sum(1 for pnl in pnls if pnl <= -threshold)
    worst = min(days, key=lambda day: day[1], default=None)
    best, total = max(pnls, default=0), sum(pnls)
    worst_twentieth = ceil(len(pnls) / 20)
    return {
        "days": len(days),
        "worst_day": None if worst is None else {"trade_date": worst[0], "pnl": money(worst[1])},
        "best_day_share": ratio(best, total) if best > 0 and total > 0 else None,
        "cvar_95": ratio(sum(sorted(pnls)[:worst_twentieth]), worst_twentieth * MICRO_UNITS),
        "large_daily_losses": large,
        "large_daily_loss_frequency": ratio(large, len(days)),
        "large_daily_loss_threshold": money(threshold),
        **sharpe_ratios(days, inputs["trials"]),
        "trials": inputs["trials"],
    }


def expected_maximum(trials: int) -> float:
    """The expected largest of `trials` standard normal draws (Bailey and López de Prado, 2014),
    zero for one trial."""
    if trials == 1:
        return 0.0
    first = NORMAL.inv_cdf(1 - 1 / trials)
    second = NORMAL.inv_cdf(1 - 1 / (trials * e))
    return (1 - EULER_MASCHERONI) * first + EULER_MASCHERONI * second


def sharpe_ratios(days: Sequence[tuple[str, int]], trials: int) -> Json:
    """The annualised Sharpe ratio of the daily profit and loss, mean over sample deviation; the
    Sortino ratio over the root mean square of the losing days; the probabilistic Sharpe ratio;
    and the deflated one, at the Sharpe ratio the best of the trials reaches by luck."""
    ratios: Json = dict.fromkeys(("sharpe", "sortino", "probabilistic_sharpe", "deflated_sharpe"))
    if len(days) < 2:
        return ratios
    pnls = [pnl for _, pnl in days]
    count = len(pnls)
    span = (date.fromisoformat(days[-1][0]) - date.fromisoformat(days[0][0])).days + 1
    annual = sqrt(count * DAYS_PER_YEAR / span)
    mean = Fraction(sum(pnls), count)
    downside = sum(min(pnl, 0) ** 2 for pnl in pnls)
    if downside:
        ratios["sortino"] = float(mean) / sqrt(downside / count) * annual
    distances = [pnl - mean for pnl in pnls]
    squares = sum(distance**2 for distance in distances)
    if not squares:
        return ratios
    daily = float(mean) / sqrt(squares / (count - 1))
    ratios["sharpe"] = daily * annual
    second = squares / count
    skewness = float(sum(distance**3 for distance in distances) / count) / float(second) ** 1.5
    kurtosis = float(sum(distance**4 for distance in distances) / count / second**2)
    spread = 1 - skewness * daily + (kurtosis - 1) / 4 * daily**2
    if spread <= 0:
        return ratios
    ratios["probabilistic_sharpe"] = NORMAL.cdf(daily * sqrt(count - 1) / sqrt(spread))
    benchmark = sqrt(spread / (count - 1)) * expected_maximum(trials)
    ratios["deflated_sharpe"] = NORMAL.cdf((daily - benchmark) * sqrt(count - 1) / sqrt(spread))
    return ratios


def drawdown(capital: int, equity: Sequence[Json]) -> Json:
    """The deepest fall of the account below the highest equity before it, the capital first, on
    the first decision's trade date, with its peak's and trough's dates, the first of two as
    deep; and the longest spell under a peak in calendar days, to the recovery or the last date."""
    points = [(point["trade_date"], point["equity"]) for point in equity]
    if points:
        points.insert(0, (points[0][0], capital))
    deepest: tuple[int, str, str] | None = None
    longest, peak, peak_date, fell_from = 0, None, None, None
    for trade_date, value in points:
        if peak is None or value >= peak:
            if fell_from is not None:
                longest = max(longest, days_between(fell_from, trade_date))
            peak, peak_date, fell_from = value, trade_date, None
            continue
        fell_from = peak_date if fell_from is None else fell_from
        if deepest is None or peak - value > deepest[0]:
            deepest = (peak - value, str(peak_date), trade_date)
    if fell_from is not None:
        longest = max(longest, days_between(fell_from, points[-1][0]))
    depth = 0 if deepest is None else deepest[0]
    return {
        "max_drawdown": money(depth),
        "max_drawdown_share": float(Fraction(depth, capital)),
        "peak": None if deepest is None else deepest[1],
        "trough": None if deepest is None else deepest[2],
        "longest_drawdown_days": longest,
    }


def days_between(first: str, last: str) -> int:
    return (date.fromisoformat(last) - date.fromisoformat(first)).days


def breakdowns(trades: Sequence[Json]) -> Json:
    """The trades by exit reason, entry hour, the weekday and the year of the entry's trade date,
    and fidelity, each group's trades, wins, and profit and loss."""
    keys: dict[str, Callable[[Json], str]] = {
        "exit_reason": lambda trade: trade["exit_reason"],
        "hour": lambda trade: str(trade["entry_hour"]),
        "weekday": lambda trade: WEEKDAYS[date.fromisoformat(trade["entry_trade_date"]).weekday()],
        "year": lambda trade: str(date.fromisoformat(trade["entry_trade_date"]).year),
        "fidelity": lambda trade: trade["fidelity"],
    }
    return {name: grouped(trades, key) for name, key in keys.items()}


def grouped(trades: Sequence[Json], key: Callable[[Json], str]) -> Json:
    groups: defaultdict[str, list[int]] = defaultdict(list)
    for trade in trades:
        groups[key(trade)].append(trade["pnl"])
    return {
        name: {
            "trades": len(pnls),
            "wins": sum(1 for pnl in pnls if pnl > 0),
            "pnl": money(sum(pnls)),
        }
        for name, pnls in groups.items()
    }
