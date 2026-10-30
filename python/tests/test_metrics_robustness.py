"""The robustness summary of a run's metrics (step 2.11, Done means 4): three planted runs, one of
too few trades, one fragile to slippage, and a clean one, and a fourth that falls past half its
capital, each through `fefat_engine.metrics`, whose summary equals what the backtest-expert
skill's `evaluate_backtest.py` gives on the inputs the summary records
(`metrics_by_definition.scripts_summary`, which loads the script from the skill's folder as its
own tests load it): the five scores in their order, the total, the verdict, the red flags with
their messages, the profit factor, and the expectancy."""

import json
from datetime import date, timedelta
from typing import Any

import fefat_engine
import polars as pl
import pytest

from fefat.backtest.metrics import Metrics, RedFlagId, Robustness, SampleSize, Verdict
from fefat.backtest.metrics_inputs import friction_tested
from fefat.reference.settings import SlippageTicks
from metrics_by_definition import scripts_summary

USD = 1_000_000
CAPITAL = 50_000 * USD
ES = {"tick_size": 250_000_000, "money_per_point": 50_000_000}
FIRST_TRADE_DATE = date(2016, 1, 4)

type Json = dict[str, Any]


def alternating(wins: int, losses: int, win: int, loss: int) -> list[int]:
    """`wins` trades making `win` USD and `losses` losing `loss`, each loss after a win."""
    return [win, -loss] * losses + [win] * (wins - losses)


def planted_run(pnls: list[int], years: int, plus_one: int, risk: int = 200) -> Json:
    """A run on ES of trades making `pnls` USD in turn, each risking `risk` USD, on trade dates in
    a row in a window of `years`, with three parameters and friction, and its rerun at one more
    tick making `plus_one` USD."""
    trade_dates = [
        (FIRST_TRADE_DATE + timedelta(days=index)).isoformat() for index in range(len(pnls))
    ]
    trades = [
        {
            "pnl": pnl * USD,
            "gross_pnl": (pnl + 5) * USD,
            "lots": 1,
            "initial_risk": risk * USD,
            "mae_ticks": 8,
            "mfe_ticks": 16,
            "entry_trade_date": trade_date,
            "entry_hour": 9,
            "exit_reason": "target_1" if pnl > 0 else "stop",
            "fidelity": "1m",
        }
        for pnl, trade_date in zip(pnls, trade_dates, strict=True)
    ]
    running = [CAPITAL + sum(pnls[: index + 1]) * USD for index in range(len(pnls))]
    last = FIRST_TRADE_DATE + timedelta(days=round(years * 365.25) - 1)
    return {
        "capital": CAPITAL,
        "instrument": ES,
        "trials": 1,
        "large_daily_loss": 20_000_000,
        "pnl_at_plus_one_tick": plus_one * USD,
        "window": {"start": FIRST_TRADE_DATE.isoformat(), "end": last.isoformat()},
        "parameters": 3,
        "friction_tested": True,
        "trades": trades,
        "equity": [
            {"trade_date": trade_date, "equity": equity}
            for trade_date, equity in zip(trade_dates, running, strict=True)
        ],
    }


def summary_of(run: Json) -> Robustness:
    return Metrics.model_validate_json(fefat_engine.metrics(json.dumps(run))).robustness


def assert_the_scripts(summary: Robustness) -> None:
    """The summary is what the script gives on the inputs it records: its scores in their order,
    its total and verdict, its red flags with their messages, its profit factor and expectancy."""
    expected = scripts_summary(summary.inputs.model_dump())
    recorded = summary.model_dump(mode="json")
    assert {key: recorded[key] for key in expected} == expected


def test_a_run_of_too_few_trades_is_flagged_as_the_script_flags_it() -> None:
    summary = summary_of(planted_run(alternating(7, 5, win=300, loss=200), years=8, plus_one=800))

    assert_the_scripts(summary)
    assert summary.inputs.total_trades == 12
    assert summary.sample_size is SampleSize.BELOW_MINIMUM
    assert [flag.id for flag in summary.red_flags] == [RedFlagId.SMALL_SAMPLE]
    assert summary.red_flags[0].message == (
        "Only 12 trades — minimum 30 required for statistical confidence."
    )
    assert summary.dimensions[0].score == 0
    assert summary.verdict is Verdict.REFINE
    assert not summary.fragile_to_slippage


def test_a_run_fragile_to_slippage_says_so_beside_the_scripts_verdict() -> None:
    run = planted_run(alternating(80, 70, win=150, loss=165), years=8, plus_one=-1_425)

    summary = summary_of(run)

    assert_the_scripts(summary)
    assert summary.fragile_to_slippage
    assert summary.pnl_at_plus_one_tick < 0 < sum(trade["pnl"] for trade in run["trades"])
    assert summary.sample_size is SampleSize.PREFERRED
    assert summary.red_flags == ()
    assert summary.verdict is Verdict.DEPLOY_GRADE_EVIDENCE


def test_a_clean_run_is_deploy_grade_evidence_without_red_flags() -> None:
    summary = summary_of(
        planted_run(alternating(140, 110, win=300, loss=200), years=10, plus_one=13_750)
    )

    assert_the_scripts(summary)
    inputs = summary.inputs
    assert (inputs.total_trades, inputs.win_rate, inputs.years_tested) == (250, 56.0, 10)
    assert (inputs.avg_win_pct, inputs.avg_loss_pct) == (0.6, 0.4)
    assert inputs.max_drawdown_pct < 1.0
    assert (inputs.num_parameters, inputs.slippage_tested) == (3, True)
    assert summary.sample_size is SampleSize.HIGH_CONFIDENCE
    assert [dimension.score for dimension in summary.dimensions] == [20, 6, 15, 20, 20]
    assert (summary.total_score, summary.verdict) == (81, Verdict.DEPLOY_GRADE_EVIDENCE)
    assert summary.red_flags == ()
    assert not summary.fragile_to_slippage


def test_a_fall_past_half_the_capital_scores_no_risk_and_is_flagged_as_the_script_does() -> None:
    # Step 2.11's review: the excessive drawdown's red flag, whose message writes the drawdown as
    # Python writes a float, and the risk score of nothing from a fall of half the capital.
    summary = summary_of(planted_run([-777] * 40 + [500] * 80, years=6, plus_one=2_000, risk=777))

    assert_the_scripts(summary)
    assert summary.inputs.max_drawdown_pct == 62.16
    flagged = {flag.id: flag.message for flag in summary.red_flags}
    assert flagged == {
        RedFlagId.EXCESSIVE_DRAWDOWN: (
            "Max drawdown 62.16% exceeds 50% threshold — catastrophic risk."
        )
    }
    assert summary.dimensions[2].score == 0


def test_friction_is_tested_when_the_run_slips_a_tick_or_its_fills_pay_a_fee() -> None:
    # The code review: a fee table's schedule outside the window charges the run nothing.
    unpaid = pl.DataFrame({"fee": [0, 0]}, schema={"fee": pl.Int64})
    paid = pl.DataFrame({"fee": [0, 1_290_000]}, schema={"fee": pl.Int64})
    still = SlippageTicks(market=0, stop=0)

    assert not friction_tested(still, unpaid)
    assert friction_tested(still, paid)
    assert friction_tested(SlippageTicks(market=0, stop=1), unpaid)


def test_trades_that_break_even_count_in_the_scripts_average_loss() -> None:
    # Step 2.11's engine review: the script takes every trade that is not a win as a loss, so its
    # average loss is over the trades that did not win, and its expectancy is the run's mean.
    summary = summary_of(planted_run([500] * 4 + [-500] * 2 + [0] * 4, years=8, plus_one=500))

    assert_the_scripts(summary)
    assert summary.inputs.avg_loss_pct == 100 * 1_000 / (6 * 50_000)
    assert summary.expectancy == pytest.approx(100 * 1_000 / 10 / 50_000)
    assert summary.profit_factor == pytest.approx(2.0)
    assert RedFlagId.NEGATIVE_EXPECTANCY not in {flag.id for flag in summary.red_flags}
