//! The robustness summary of a run (`08` §4, D-29, step 2.11): the backtest-expert skill's
//! `evaluate_backtest.py` ported operation by operation, so that the same inputs give the same
//! five scores of 20 points (sample size, expectancy, risk management, robustness, execution
//! realism), the same total, verdict, and red flags, ids, severities, and messages, with its own
//! arithmetic: floats where the script divides, truncation where it calls `int()`, and a profit
//! factor without a loss, which the script makes infinite, as none, scoring as the script's does.
//! A run gives the script's inputs: its trades and win rate in percent, its average win and loss
//! and its maximum drawdown in percent of its capital (D-51), the years its window spans rounded
//! to the nearest, its parameters, and whether it paid fees or slippage. Beside the script's,
//! the summary says which of the 30, 100, and 200 trades the run reaches, and carries FEFAT's own
//! evidence of friction: the profit and loss at one more tick of slippage, and whether the run's
//! profit is gone at it. Regimes arrive with the regime breakdown of step 11.4 (D-51).

use fefat_core::units::Money;
use serde::Serialize;

use crate::inputs::MetricsInputs;
use crate::json_units;

/// What the script reads, under its own names.
#[derive(Debug, Clone, Copy, PartialEq, Serialize)]
pub struct ScriptInputs {
    /// The trades.
    pub total_trades: usize,
    /// The wins over the trades, in percent.
    pub win_rate: f64,
    /// The average win over the capital, in percent.
    pub avg_win_pct: f64,
    /// The losses over the trades that did not win, over the capital, in percent, at or
    /// above zero: the script takes every trade that is not a win as a loss, so that a
    /// trade that broke even counts as a loss of nothing.
    pub avg_loss_pct: f64,
    /// The maximum drawdown over the capital, in percent.
    pub max_drawdown_pct: f64,
    /// The years the run's window spans, rounded to the nearest.
    pub years_tested: u32,
    /// The parameters of the strategy.
    pub num_parameters: u32,
    /// Whether the run paid fees or slippage.
    pub slippage_tested: bool,
}

impl ScriptInputs {
    /// What the script reads of the run `inputs` describe, whose deepest fall is
    /// `max_drawdown`, each percentage one division of exact integers: a run without trades wins
    /// none of them, and one without wins or losses averages none; a trade that did not win
    /// counts in the average loss, as the script's expectancy takes it.
    pub fn of(inputs: &MetricsInputs, max_drawdown: Money) -> Self {
        let pnls = || inputs.trades.iter().map(|trade| i128::from(trade.pnl.0));
        let counted = |(count, sum): (i128, i128), pnl: i128| (count + 1, sum + pnl);
        let (wins, profit) = pnls().filter(|pnl| *pnl > 0).fold((0, 0), counted);
        let (_, loss) = pnls().filter(|pnl| *pnl < 0).fold((0, 0), counted);
        let (trades, capital) = (pnls().count(), i128::from(inputs.capital.0));
        Self {
            total_trades: trades,
            win_rate: percent(wins, trades as i128),
            avg_win_pct: percent(profit, wins * capital),
            avg_loss_pct: percent(-loss, (trades as i128 - wins) * capital),
            max_drawdown_pct: percent(i128::from(max_drawdown.0), capital),
            years_tested: inputs.window.years(),
            num_parameters: inputs.parameters,
            slippage_tested: inputs.friction_tested,
        }
    }
}

/// `part` over `whole` in percent, zero over nothing, as the script takes a run without trades,
/// wins, or losses.
fn percent(part: i128, whole: i128) -> f64 {
    if whole == 0 {
        return 0.0;
    }
    (100 * part) as f64 / whole as f64
}

/// A dimension of the summary.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum DimensionName {
    /// The trade count.
    SampleSize,
    /// The win rate and the average win and loss.
    Expectancy,
    /// The maximum drawdown and the profit factor.
    RiskManagement,
    /// The years tested and the parameters.
    Robustness,
    /// Whether friction was tested.
    ExecutionRealism,
}

/// A dimension's score, out of 20.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub struct Dimension {
    /// Which dimension.
    pub name: DimensionName,
    /// Its score.
    pub score: u32,
    /// The most it scores.
    pub max_score: u32,
}

/// The plain verdict of the summary's total.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Verdict {
    /// 70 points or more: the script's `Deploy`.
    DeployGradeEvidence,
    /// 40 points or more.
    Refine,
    /// Fewer.
    Abandon,
}

/// A red flag of the script's checklist.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RedFlagId {
    /// Fewer than 30 trades.
    SmallSample,
    /// No fees or slippage.
    NoSlippageTest,
    /// A drawdown above 50 % of the capital.
    ExcessiveDrawdown,
    /// Seven parameters or more.
    OverOptimized,
    /// Fewer than five years.
    ShortTestPeriod,
    /// The script's expectancy below zero.
    NegativeExpectancy,
    /// A win rate above 90 % with a drawdown below 5 %.
    TooGood,
}

/// How serious a red flag is.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Severity {
    /// High.
    High,
    /// Medium.
    Medium,
}

/// A red flag that fires, with the script's message.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct RedFlag {
    /// Which.
    pub id: RedFlagId,
    /// How serious.
    pub severity: Severity,
    /// What the script says.
    pub message: String,
}

/// The trade counts of the skill's sample sizes: an absolute minimum of 30, 100 preferred, and
/// 200 for high confidence.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SampleSize {
    /// Fewer than 30 trades.
    BelowMinimum,
    /// From 30.
    Minimum,
    /// From 100.
    Preferred,
    /// From 200.
    HighConfidence,
}

/// The robustness summary of a run.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct Robustness {
    /// What the script read.
    pub inputs: ScriptInputs,
    /// The five scores, in the script's order.
    pub dimensions: [Dimension; 5],
    /// Their total, out of 100.
    pub total_score: u32,
    /// The verdict of the total.
    pub verdict: Verdict,
    /// The red flags that fire, in the script's order.
    pub red_flags: Vec<RedFlag>,
    /// Which of 30, 100, and 200 trades the run reaches.
    pub sample_size: SampleSize,
    /// The script's profit factor, from the win rate and the average win and loss; none without a
    /// loss.
    pub profit_factor: Option<f64>,
    /// The script's expectancy, in percent of the capital per trade.
    pub expectancy: f64,
    /// The profit and loss of the rerun at one more tick of slippage (F-SLP-01).
    #[serde(serialize_with = "json_units::money_text")]
    pub pnl_at_plus_one_tick: Money,
    /// Whether the run's profit is gone at one more tick.
    pub fragile_to_slippage: bool,
}

/// The summary of a run whose inputs to the script are `inputs`, whose trades made `pnl`, and
/// whose rerun at one more tick of slippage made `pnl_at_plus_one_tick`.
pub fn robustness(inputs: ScriptInputs, pnl: Money, pnl_at_plus_one_tick: Money) -> Robustness {
    let profit_factor = profit_factor(&inputs);
    let scores = [
        (
            DimensionName::SampleSize,
            sample_size_score(inputs.total_trades),
        ),
        (
            DimensionName::Expectancy,
            expectancy_score(expectancy(&inputs)),
        ),
        (
            DimensionName::RiskManagement,
            risk_management_score(&inputs, profit_factor),
        ),
        (DimensionName::Robustness, robustness_score(&inputs)),
        (
            DimensionName::ExecutionRealism,
            if inputs.slippage_tested { 20 } else { 0 },
        ),
    ];
    let total_score = scores.iter().map(|(_, score)| score).sum::<u32>().min(100);
    Robustness {
        inputs,
        dimensions: scores.map(|(name, score)| Dimension {
            name,
            score,
            max_score: 20,
        }),
        total_score,
        verdict: verdict(total_score),
        red_flags: red_flags(&inputs),
        sample_size: sample_size(inputs.total_trades),
        profit_factor,
        expectancy: expectancy(&inputs),
        pnl_at_plus_one_tick,
        fragile_to_slippage: pnl.0 > 0 && pnl_at_plus_one_tick.0 <= 0,
    }
}

/// The script's `int()` of a score's float, which lies at or above zero.
fn truncated(value: f64) -> u32 {
    value as u32
}

/// `score_sample_size`.
fn sample_size_score(total_trades: usize) -> u32 {
    let trades = total_trades as f64;
    match total_trades {
        0..30 => 0,
        30..100 => 8 + truncated((trades - 30.0) / 70.0 * 7.0),
        100..200 => 15 + truncated((trades - 100.0) / 100.0 * 5.0),
        _ => 20,
    }
}

const fn sample_size(total_trades: usize) -> SampleSize {
    match total_trades {
        0..30 => SampleSize::BelowMinimum,
        30..100 => SampleSize::Minimum,
        100..200 => SampleSize::Preferred,
        _ => SampleSize::HighConfidence,
    }
}

/// `calc_expectancy`, in percent of the capital per trade.
fn expectancy(inputs: &ScriptInputs) -> f64 {
    let win_rate = inputs.win_rate / 100.0;
    win_rate * inputs.avg_win_pct - (1.0 - win_rate) * inputs.avg_loss_pct
}

/// `calc_profit_factor`, none where the script's is infinite.
fn profit_factor(inputs: &ScriptInputs) -> Option<f64> {
    let win_rate = inputs.win_rate / 100.0;
    let loss_component = (1.0 - win_rate) * inputs.avg_loss_pct;
    (loss_component != 0.0).then(|| (win_rate * inputs.avg_win_pct) / loss_component)
}

/// `score_expectancy`.
fn expectancy_score(expectancy: f64) -> u32 {
    if expectancy <= 0.0 {
        return 0;
    }
    if expectancy < 0.5 {
        return 5 + truncated(expectancy / 0.5 * 5.0);
    }
    if expectancy < 1.5 {
        return 10 + truncated((expectancy - 0.5) / 1.0 * 8.0);
    }
    20
}

/// `score_risk_management`: zero from a 50 % drawdown, else the drawdown's points and the profit
/// factor's, an infinite one scoring eight.
fn risk_management_score(inputs: &ScriptInputs, profit_factor: Option<f64>) -> u32 {
    let drawdown = inputs.max_drawdown_pct;
    if drawdown >= 50.0 {
        return 0;
    }
    let drawdown_score = if drawdown < 20.0 {
        12
    } else {
        truncated(12.0 * (50.0 - drawdown) / 30.0)
    };
    let profit_factor_score = match profit_factor {
        Some(factor) if factor < 1.0 => 0,
        Some(factor) if factor < 3.0 => truncated((factor - 1.0) / 2.0 * 8.0),
        _ => 8,
    };
    (drawdown_score + profit_factor_score).min(20)
}

/// `score_robustness`.
fn robustness_score(inputs: &ScriptInputs) -> u32 {
    let years = inputs.years_tested;
    let years_score = match years {
        0..5 => 0,
        5..10 => 5 + truncated(f64::from(years - 5) / 5.0 * 10.0),
        _ => 15,
    };
    let parameter_score = match inputs.num_parameters {
        0..=4 => 5,
        5..=6 => 3,
        7 => 1,
        _ => 0,
    };
    (years_score + parameter_score).min(20)
}

/// `get_verdict`.
const fn verdict(total_score: u32) -> Verdict {
    match total_score {
        70.. => Verdict::DeployGradeEvidence,
        40.. => Verdict::Refine,
        _ => Verdict::Abandon,
    }
}

/// `detect_red_flags`, in its order, with its messages.
fn red_flags(inputs: &ScriptInputs) -> Vec<RedFlag> {
    let expectancy = expectancy(inputs);
    let flags = [
        (inputs.total_trades < 30).then(|| RedFlag {
            id: RedFlagId::SmallSample,
            severity: Severity::High,
            message: format!(
                "Only {} trades — minimum 30 required for statistical confidence.",
                inputs.total_trades
            ),
        }),
        (!inputs.slippage_tested).then(|| RedFlag {
            id: RedFlagId::NoSlippageTest,
            severity: Severity::High,
            message: "Slippage/friction not tested — results may not survive real-world \
                      execution."
                .to_owned(),
        }),
        (inputs.max_drawdown_pct > 50.0).then(|| RedFlag {
            id: RedFlagId::ExcessiveDrawdown,
            severity: Severity::High,
            // shortcut: `{:?}` writes a float as Python's repr does below 1e16 %, a drawdown
            // a capital under 0.1 USD would need; the parity test holds the message to the script's.
            message: format!(
                "Max drawdown {:?}% exceeds 50% threshold — catastrophic risk.",
                inputs.max_drawdown_pct
            ),
        }),
        (inputs.num_parameters >= 7).then(|| RedFlag {
            id: RedFlagId::OverOptimized,
            severity: Severity::Medium,
            message: format!(
                "{} parameters suggests over-optimization / curve-fitting risk.",
                inputs.num_parameters
            ),
        }),
        (inputs.years_tested < 5).then(|| RedFlag {
            id: RedFlagId::ShortTestPeriod,
            severity: Severity::Medium,
            message: format!(
                "Only {} years tested — may miss regime changes (minimum 5 recommended).",
                inputs.years_tested
            ),
        }),
        (expectancy < 0.0).then(|| RedFlag {
            id: RedFlagId::NegativeExpectancy,
            severity: Severity::High,
            message: format!(
                "Negative expectancy ({expectancy:.3}%) — strategy loses money on average."
            ),
        }),
        (inputs.win_rate > 90.0 && inputs.max_drawdown_pct < 5.0).then(|| RedFlag {
            id: RedFlagId::TooGood,
            severity: Severity::Medium,
            message: "Results look too good — audit for look-ahead bias or data issues.".to_owned(),
        }),
    ];
    flags.into_iter().flatten().collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn inputs(total_trades: usize, win_rate: f64, drawdown: f64, years: u32) -> ScriptInputs {
        ScriptInputs {
            total_trades,
            win_rate,
            avg_win_pct: 1.8,
            avg_loss_pct: 1.2,
            max_drawdown_pct: drawdown,
            years_tested: years,
            num_parameters: 3,
            slippage_tested: true,
        }
    }

    #[test]
    fn the_sample_size_scores_at_the_scripts_own_points() {
        let scores: Vec<u32> = [20, 29, 30, 99, 100, 199, 200, 500]
            .into_iter()
            .map(sample_size_score)
            .collect();
        assert_eq!(scores, [0, 0, 8, 14, 15, 19, 20, 20]);
        assert_eq!(sample_size(29), SampleSize::BelowMinimum);
        assert_eq!(sample_size(200), SampleSize::HighConfidence);
    }

    #[test]
    fn the_verdict_turns_at_70_and_40() {
        let verdicts = [100, 70, 69, 40, 39, 0].map(verdict);
        assert_eq!(
            verdicts,
            [
                Verdict::DeployGradeEvidence,
                Verdict::DeployGradeEvidence,
                Verdict::Refine,
                Verdict::Refine,
                Verdict::Abandon,
                Verdict::Abandon,
            ]
        );
    }

    #[test]
    fn a_drawdown_of_half_the_capital_scores_nothing_and_raises_no_flag() {
        let half = inputs(150, 62.0, 50.0, 8);
        assert_eq!(risk_management_score(&half, profit_factor(&half)), 0);
        assert!(red_flags(&half).is_empty());
        let beyond = inputs(150, 62.0, 61.5, 8);
        let flags = red_flags(&beyond);
        assert_eq!(
            flags.first().map(|flag| flag.message.as_str()),
            Some("Max drawdown 61.5% exceeds 50% threshold — catastrophic risk.")
        );
        let round = red_flags(&inputs(150, 62.0, 60.0, 8));
        assert_eq!(
            round.first().map(|flag| flag.message.as_str()),
            Some("Max drawdown 60.0% exceeds 50% threshold — catastrophic risk.")
        );
    }

    #[test]
    fn three_places_round_a_tie_to_the_even_digit_as_python_does() {
        assert_eq!(format!("{:.3}", -0.0625_f64), "-0.062");
        assert_eq!(format!("{:.3}", -0.1875_f64), "-0.188");
        assert_eq!(format!("{:.3}", -0.0005_f64), "-0.001");
        assert_eq!(format!("{:.3}", -1.0005_f64), "-1.000");
    }

    #[test]
    fn a_profit_factor_without_a_loss_scores_eight() {
        let flawless = ScriptInputs {
            avg_loss_pct: 0.0,
            ..inputs(250, 100.0, 1.0, 10)
        };
        assert_eq!(profit_factor(&flawless), None);
        assert_eq!(risk_management_score(&flawless, None), 20);
        let summary = robustness(flawless, Money(1), Money(1));
        assert_eq!(summary.total_score, 100);
        let flags: Vec<RedFlagId> = summary.red_flags.iter().map(|flag| flag.id).collect();
        assert_eq!(flags, [RedFlagId::TooGood]);
    }

    #[test]
    fn the_scripts_example_scores_as_its_readme_runs_it() {
        let summary = robustness(inputs(150, 62.0, 15.0, 8), Money(10), Money(-1));
        let scores = summary.dimensions.map(|dimension| dimension.score);
        assert_eq!(scores, [17, 11, 17, 16, 20]);
        assert_eq!(
            (summary.total_score, summary.verdict),
            (81, Verdict::DeployGradeEvidence)
        );
        assert!(summary.fragile_to_slippage);
    }
}
