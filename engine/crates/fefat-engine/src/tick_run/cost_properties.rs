//! Step 2.9's Done means 2 in the loop: on the months `skip_equals_full` draws, with dated fee
//! tables, funding times, and a roll, after every step the ledger's cash is the run's opening
//! cash moved by each fill's value and by every cost line, each fee line the fee its fill records;
//! and at the end the gross profit and loss, what the fills' values moved the cash by with the
//! position's value at the mark, less the sum of the cost lines, is the net profit and loss, the
//! change of equity. 1,000 cases under a fixed seed, which must pay fees and funding and roll.

use std::cell::RefCell;

use fefat_core::costs::{CostLine, CostReason};
use fefat_core::orders::OrderRole;
use fefat_core::units::Money;
use proptest::prelude::*;
use proptest::test_runner::{Config, RngAlgorithm, TestRng, TestRunner};

use super::skip_equals_full::{CAPITAL, drawn_month, with_month};
use super::{BookedFill, Replay, RunOutputs};

/// The run's seed, recorded in the pull request, so that a failure reproduces.
const SEED: u64 = 20_261_030;
const CASES: u32 = 1_000;

/// What the cases reached, so that agreement never means that nothing was paid.
#[derive(Debug, Default)]
struct Coverage {
    reconciled: usize,
    refused: usize,
    with_fees: usize,
    with_funding: usize,
    rolled: usize,
    held_at_the_end: usize,
}

/// The sum of `amounts`, in micro-units, in 128 bits.
fn sum(amounts: impl Iterator<Item = Money>) -> i128 {
    amounts.map(|amount| i128::from(amount.0)).sum()
}

/// After a step: the cash is the opening cash moved by the fills' values and the cost lines, and
/// each fee line is its fill's fee.
fn cash_reconciles(
    opening: Money,
    fills: &[BookedFill],
    costs: &[CostLine],
    cash: Money,
) -> Result<(), TestCaseError> {
    let moved = sum(fills.iter().map(|booked| booked.cash));
    let paid = sum(costs.iter().map(|line| line.amount));
    prop_assert_eq!(i128::from(cash.0), i128::from(opening.0) + moved - paid);
    for line in costs {
        let CostReason::Fee { order } = line.reason else {
            continue;
        };
        let filled = fills.iter().find(|booked| booked.fill.order == order);
        prop_assert_eq!(filled.map(|booked| booked.fill.fee), Some(line.amount));
    }
    Ok(())
}

/// At the end: gross profit and loss less the cost lines is the net.
fn net_reconciles(opening: Money, outputs: &RunOutputs) -> Result<bool, TestCaseError> {
    let (Ok(value), Ok(equity)) = (outputs.ledger.position_value(), outputs.ledger.equity()) else {
        return Ok(false);
    };
    let capital = i128::from(CAPITAL);
    let moved = sum(outputs.fills.iter().map(|booked| booked.cash));
    let gross = i128::from(opening.0) - capital + moved + i128::from(value.0);
    let paid = sum(outputs.costs.iter().map(|line| line.amount));
    let net = i128::from(equity.0) - capital;
    prop_assert_eq!(gross - paid, net);
    Ok(true)
}

#[test]
fn gross_profit_and_loss_less_the_cost_lines_is_the_net_after_every_step() {
    let mut seed = [0_u8; 32];
    seed[..8].copy_from_slice(&SEED.to_le_bytes());
    let config = Config {
        cases: CASES,
        failure_persistence: None,
        ..Config::default()
    };
    let mut runner =
        TestRunner::new_with_rng(config, TestRng::from_seed(RngAlgorithm::ChaCha, &seed));
    let coverage = RefCell::new(Coverage::default());
    let outcome = runner.run(&drawn_month(), |month| {
        with_month(&month, Replay::Full, |mut run| {
            let opening = run.ledger().cash();
            loop {
                match run.step() {
                    Ok(Some(_)) => {}
                    Ok(None) => break,
                    Err(_) => {
                        coverage.borrow_mut().refused += 1;
                        return Ok(());
                    }
                }
                cash_reconciles(opening, run.fills(), run.cost_lines(), run.ledger().cash())?;
            }
            let outputs = run.run();
            prop_assert!(outputs.is_ok(), "{:?}", outputs);
            let Ok(outputs) = outputs else {
                return Ok(());
            };
            let reconciled = net_reconciles(opening, &outputs)?;
            let mut seen = coverage.borrow_mut();
            seen.reconciled += usize::from(reconciled);
            let paid = |funding: bool| {
                let mut reasons = outputs.costs.iter().map(|line| line.reason);
                reasons.any(|reason| matches!(reason, CostReason::Funding { .. }) == funding)
            };
            let (fees, funding) = (paid(false), paid(true));
            seen.with_fees += usize::from(fees);
            seen.with_funding += usize::from(funding);
            let roles = outputs.fills.iter().map(|booked| booked.fill.role);
            seen.rolled += usize::from(
                roles
                    .into_iter()
                    .any(|role| matches!(role, OrderRole::Roll(_))),
            );
            seen.held_at_the_end += usize::from(
                outputs
                    .ledger
                    .position_value()
                    .is_ok_and(|value| value.0 != 0),
            );
            Ok(())
        })
    });
    if let Err(failure) = outcome {
        panic!("Seed {SEED}: {failure}");
    }
    let coverage = coverage.into_inner();
    println!("seed {SEED}: {coverage:#?}");
    assert!(coverage.reconciled >= 900, "{coverage:#?}");
    assert!(coverage.refused <= CASES as usize / 50, "{coverage:#?}");
    for paid in [
        coverage.with_fees,
        coverage.with_funding,
        coverage.rolled,
        coverage.held_at_the_end,
    ] {
        assert!(paid >= 50, "{coverage:#?}");
    }
}
