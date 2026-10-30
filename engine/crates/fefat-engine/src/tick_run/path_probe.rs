//! Step 2.13's Done means 2: the questions prop rules ask of a trade's equity
//! (`03-prop-simulator.md` §4.2 and §4.6), asked of each trade's compact path and of its
//! full-resolution path, every mark and every fill while it is open, get the same answers on
//! 10,000 generated months under a fixed seed: the equity at each whole minute; and, from a
//! reference on a fill or a whole minute, for a drawn size and threshold, whether the equity
//! relative to the reference reaches the threshold for the trade or against it, when, at what
//! price, and by how much each crossing first does, which of the two comes first, and the highest
//! and lowest equity from the reference on. A path's equity is the trade's position valued along its
//! prices, each fill valuing it at its own price before it changes the lots held; a bar's possible
//! adverse extreme (§15) is the prop simulator's to weigh, and no point of the engine's path.
//! Recording paths changes nothing else: each month runs with compact paths, as saved runs record
//! them, skipping (`02` §4), with every mark in full, and without paths, and the three agree but
//! for their paths. The months are skip-equals-full's, so that the cases fill on every fidelity
//! and close trades in parts, by reversing, across rolls, across a session's close, and across
//! trade dates.

use std::cell::RefCell;
use std::collections::BTreeMap;

use fefat_core::instants::{NANOSECONDS_PER_MINUTE, Ts};
use fefat_core::orders::OrderId;
use fefat_core::units::Price;
use proptest::prelude::*;
use proptest::test_runner::{Config, RngAlgorithm, TestRng, TestRunner};

use super::skip_equals_full::{DrawnMonth, drawn_month, with_month};
use super::{BookedFill, PathPoint, PathPointKind, Recording, Replay, RunError, RunOutputs};
use super::{Stepped, Trade, TradePath, TradingHours};

/// The run's seed, recorded in the pull request, so that a failure reproduces.
const SEED: u64 = 20_261_030;
const CASES: u32 = 10_000;
/// The tick of the drawn months' instrument, 0.25 in 1e-9 units.
const TICK: i64 = 250_000_000;

/// A question drawn for each trade: its reference, a fill of the trade for an even number and a
/// whole minute for an odd one, the size that multiplies the trade's lots, and the threshold in
/// ticks of one lot.
#[derive(Debug, Clone, Copy)]
struct DrawnQuestion {
    reference: u32,
    size: i64,
    threshold_ticks: i64,
}

fn drawn_questions() -> impl Strategy<Value = Vec<DrawnQuestion>> {
    let question =
        (any::<u32>(), 1_i64..=4, 1_i64..=40).prop_map(|(reference, size, threshold_ticks)| {
            DrawnQuestion {
                reference,
                size,
                threshold_ticks,
            }
        });
    proptest::collection::vec(question, 1..8)
}

/// A month's run: its outputs or what refused it, the records it skipped while a trade was open,
/// and, for each trade, whether the market closed while it was open.
struct Probed {
    outputs: Result<RunOutputs, RunError>,
    skipped_in_trades: usize,
    across_a_close: Vec<bool>,
}

fn probed(month: &DrawnMonth, replay: Replay, recording: Recording) -> Probed {
    with_month(month, replay, |run| {
        let hours: &TradingHours = run.hours;
        let mut run = run.with_recording(recording);
        let mut skipped_in_trades = 0;
        loop {
            let in_trade = run.trades.is_open();
            match run.step() {
                Ok(Some(Stepped::Skipped { units })) if in_trade => skipped_in_trades += units,
                Ok(Some(_)) => {}
                Ok(None) => break,
                Err(error) => {
                    return Probed {
                        outputs: Err(error),
                        skipped_in_trades,
                        across_a_close: Vec::new(),
                    };
                }
            }
        }
        let outputs = run.run();
        let across_a_close = outputs.as_ref().map_or_else(
            |_| Vec::new(),
            |outputs| {
                let trades = outputs.trades.iter();
                let closed =
                    |trade: &Trade| !hours.is_open_throughout(trade.entry_ts, trade.exit_ts);
                trades.map(closed).collect()
            },
        );
        Probed {
            outputs,
            skipped_in_trades,
            across_a_close,
        }
    })
}

/// The outputs but for their paths, which recording alone may change.
fn without_paths(outputs: &Result<RunOutputs, RunError>) -> Result<RunOutputs, RunError> {
    outputs.clone().map(|outputs| RunOutputs {
        trade_paths: Vec::new(),
        ..outputs
    })
}

/// A point of a path as the questions read it: its instant and price, the lots the trade holds
/// after it, positive long, and the order of a fill's point.
#[derive(Debug, Clone, Copy)]
struct Step {
    ts: Ts,
    price: Price,
    held: i64,
    fill: Option<OrderId>,
}

/// `path`'s points but a bar's possible adverse extreme, with the lots `trade` holds after each:
/// its own lots after its entry, none after the fill that closes it, and after any other fill, a
/// roll's leg, an addition, or an exit, the lots that fill moved.
fn steps(path: &TradePath, trade: &Trade, fills: &[BookedFill]) -> Vec<Step> {
    let points = path.points.iter();
    let points: Vec<_> = points
        .filter(|point| point.kind != PathPointKind::PossibleAdverse)
        .collect();
    let last = points.len().saturating_sub(1);
    let mut held = 0;
    let mut steps = Vec::with_capacity(points.len());
    for (index, point) in points.into_iter().enumerate() {
        let fill = point.kind.order();
        if let Some(order) = fill {
            held = match index {
                0 => trade.side.sign() * trade.lots.0,
                _ if index == last => 0,
                _ => held + moved_by(order, fills),
            };
        }
        steps.push(Step {
            ts: point.ts,
            price: point.price,
            held,
            fill,
        });
    }
    steps
}

/// The lots the fill of `order` moved, positive for a buy.
fn moved_by(order: OrderId, fills: &[BookedFill]) -> i64 {
    let booked = fills.iter().find(|booked| booked.fill.order == order);
    let fill = booked.map(|booked| booked.fill);
    fill.map_or(0, |fill| fill.side.sign() * fill.lots.0)
}

/// The equity at each step, from the entry's, in 1e-9 units of price times lots: each step adds
/// the lots held before it times the move of the price to it.
fn equity(steps: &[Step]) -> Vec<i128> {
    let mut equity = Vec::with_capacity(steps.len());
    let mut before: Option<(Step, i128)> = None;
    for &step in steps {
        let value = before.map_or(0, |(previous, value)| {
            let moved = i128::from(step.price.0) - i128::from(previous.price.0);
            value + i128::from(previous.held) * moved
        });
        equity.push(value);
        before = Some((step, value));
    }
    equity
}

/// The whole minutes from the trade's entry's fill on, to just before the fill that closes it.
fn minutes_of(trade: &Trade) -> Vec<Ts> {
    let mut minutes = Vec::new();
    let mut minute = trade.entry_ts.minute_at_or_after().unwrap();
    while minute < trade.exit_ts {
        minutes.push(minute);
        minute = Ts(minute.0 + NANOSECONDS_PER_MINUTE);
    }
    minutes
}

/// The equity at each of `minutes`: the last step's at or before it.
fn equity_at_minutes(steps: &[Step], equity: &[i128], minutes: &[Ts]) -> Vec<i128> {
    minutes
        .iter()
        .map(|minute| {
            let up_to = steps.partition_point(|step| step.ts <= *minute);
            equity[up_to - 1]
        })
        .collect()
}

/// Where a question starts: a fill of the trade, by its order, or a whole minute.
#[derive(Debug, Clone, Copy)]
enum Reference {
    Fill(OrderId),
    Minute(Ts),
}

/// A first crossing: when, at what price, and by how much the equity changed from the reference,
/// times the size.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct Crossing {
    ts: Ts,
    price: Price,
    change: i128,
}

/// What a prop rule asks from a reference, for one size and threshold.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct Answer {
    favourable: Option<Crossing>,
    adverse: Option<Crossing>,
    favourable_first: Option<bool>,
    highest: i128,
    lowest: i128,
}

/// The steps after `reference`, where its equity stands: those after its fill's step, or after
/// every step at or before its minute.
fn after(steps: &[Step], reference: Reference) -> usize {
    match reference {
        Reference::Fill(order) => {
            let at = steps.iter().position(|step| step.fill == Some(order));
            at.unwrap() + 1
        }
        Reference::Minute(minute) => steps.partition_point(|step| step.ts <= minute),
    }
}

fn answer(
    steps: &[Step],
    equity: &[i128],
    reference: Reference,
    question: DrawnQuestion,
) -> Answer {
    let start = after(steps, reference);
    let from = equity[start - 1];
    let threshold = i128::from(question.threshold_ticks * TICK);
    let changes = (start..steps.len()).map(|index| {
        let change = (equity[index] - from) * i128::from(question.size);
        (index, change)
    });
    let changes: Vec<(usize, i128)> = changes.collect();
    let crossing = |wanted: &dyn Fn(i128) -> bool| {
        let first = changes.iter().find(|(_, change)| wanted(*change));
        first.map(|&(index, change)| {
            (
                index,
                Crossing {
                    ts: steps[index].ts,
                    price: steps[index].price,
                    change,
                },
            )
        })
    };
    let favourable = crossing(&|change| change >= threshold);
    let adverse = crossing(&|change| change <= -threshold);
    let favourable_first = match (favourable, adverse) {
        (Some((up, _)), Some((down, _))) => Some(up < down),
        (Some(_), None) => Some(true),
        (None, Some(_)) => Some(false),
        (None, None) => None,
    };
    // From the reference on: its own change, none, counts, as it does for a threshold.
    let moved = std::iter::once(0).chain(changes.iter().map(|&(_, change)| change));
    Answer {
        favourable: favourable.map(|(_, crossing)| crossing),
        adverse: adverse.map(|(_, crossing)| crossing),
        favourable_first,
        highest: moved.clone().max().unwrap_or(0),
        lowest: moved.min().unwrap_or(0),
    }
}

/// The reference a question draws among the trade's fills and its whole minutes.
fn reference_of(question: DrawnQuestion, fills: &[OrderId], minutes: &[Ts]) -> Reference {
    let index = (question.reference / 2) as usize;
    match (question.reference % 2, minutes.is_empty()) {
        (1, false) => Reference::Minute(minutes[index % minutes.len()]),
        _ => Reference::Fill(fills[index % fills.len()]),
    }
}

/// What the cases reached, so that agreement never means that nothing was asked.
#[derive(Debug, Default)]
struct Coverage {
    cases: usize,
    refused: usize,
    trades: usize,
    questions: usize,
    minute_references: usize,
    favourable_crossings: usize,
    adverse_crossings: usize,
    favourable_first: usize,
    adverse_first: usize,
    closed_in_parts: usize,
    across_a_close: usize,
    across_trade_dates: usize,
    across_a_roll: usize,
    possible_adverse: usize,
    skipped_in_trades: usize,
    compact_points: usize,
    full_points: usize,
    minutes: usize,
    kinds: BTreeMap<String, usize>,
}

/// One trade's questions, asked of its compact path and its full one, and what they reached.
fn ask(
    trade: &Trade,
    paths: (&TradePath, &TradePath),
    fills: &[BookedFill],
    questions: &[DrawnQuestion],
    seen: &mut Coverage,
) -> Result<(), TestCaseError> {
    let (compact, full) = paths;
    let (compact_steps, full_steps) = (steps(compact, trade, fills), steps(full, trade, fills));
    let (compact_equity, full_equity) = (equity(&compact_steps), equity(&full_steps));
    let minutes = minutes_of(trade);
    let recorded: Vec<Ts> = compact
        .points
        .iter()
        .filter(|point| point.kind == PathPointKind::Minute)
        .map(|point| point.ts)
        .collect();
    prop_assert_eq!(&recorded, &minutes, "Expected a mark at each whole minute");
    prop_assert_eq!(
        equity_at_minutes(&compact_steps, &compact_equity, &minutes),
        equity_at_minutes(&full_steps, &full_equity, &minutes)
    );
    let fills_of_trade: Vec<OrderId> = full_steps.iter().filter_map(|step| step.fill).collect();
    for &question in questions {
        let reference = reference_of(question, &fills_of_trade, &minutes);
        let compact_answer = answer(&compact_steps, &compact_equity, reference, question);
        let full_answer = answer(&full_steps, &full_equity, reference, question);
        prop_assert_eq!(
            compact_answer,
            full_answer,
            "{:?} {:?}",
            reference,
            question
        );
        seen.questions += 1;
        seen.minute_references += usize::from(matches!(reference, Reference::Minute(_)));
        seen.favourable_crossings += usize::from(full_answer.favourable.is_some());
        seen.adverse_crossings += usize::from(full_answer.adverse.is_some());
        let both = full_answer.favourable.is_some() && full_answer.adverse.is_some();
        seen.favourable_first += usize::from(both && full_answer.favourable_first == Some(true));
        seen.adverse_first += usize::from(both && full_answer.favourable_first == Some(false));
    }
    seen.trades += 1;
    seen.closed_in_parts += usize::from(trade.exits > 1);
    seen.across_a_roll += usize::from(trade.rolls > 0);
    seen.compact_points += compact.points.len();
    seen.full_points += full.points.len();
    seen.minutes += minutes.len();
    for point in &compact.points {
        *seen.kinds.entry(point.kind.to_string()).or_default() += 1;
    }
    Ok(())
}

/// Whether the fills of `path`'s first point and its last, its trade's entry and the fill that
/// closed it, fall on two trade dates.
fn across_trade_dates(path: &TradePath, fills: &[BookedFill]) -> bool {
    let date_of = |point: Option<&PathPoint>| {
        let order = point.and_then(|point| point.kind.order());
        let booked = fills.iter().find(|booked| Some(booked.fill.order) == order);
        booked.map(|booked| booked.trade_date)
    };
    date_of(path.points.first()) != date_of(path.points.last())
}

#[test]
fn compact_trade_paths_answer_what_prop_rules_ask_as_the_full_paths_do_on_10000_months() {
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
    let outcome = runner.run(&(drawn_month(), drawn_questions()), |(month, questions)| {
        let compact = probed(&month, Replay::Skipping, Recording::Paths);
        let full = probed(&month, Replay::Full, Recording::EveryMark);
        let bare = probed(&month, Replay::Skipping, Recording::TradesOnly);
        prop_assert_eq!(
            without_paths(&compact.outputs),
            without_paths(&full.outputs)
        );
        prop_assert_eq!(&bare.outputs, &without_paths(&compact.outputs));
        let mut seen = coverage.borrow_mut();
        seen.cases += 1;
        seen.skipped_in_trades += compact.skipped_in_trades;
        let (Ok(compact_outputs), Ok(full_outputs)) = (&compact.outputs, &full.outputs) else {
            seen.refused += 1;
            return Ok(());
        };
        let trades = &compact_outputs.trades;
        prop_assert_eq!(compact_outputs.trade_paths.len(), trades.len());
        prop_assert_eq!(full_outputs.trade_paths.len(), trades.len());
        let paths = compact_outputs
            .trade_paths
            .iter()
            .zip(&full_outputs.trade_paths);
        for (index, (trade, paths)) in trades.iter().zip(paths).enumerate() {
            ask(trade, paths, &compact_outputs.fills, &questions, &mut seen)?;
            seen.across_a_close += usize::from(compact.across_a_close[index]);
            let dates = across_trade_dates(paths.0, &compact_outputs.fills);
            seen.across_trade_dates += usize::from(dates);
        }
        seen.possible_adverse += compact_outputs
            .trade_paths
            .iter()
            .flat_map(|path| &path.points)
            .filter(|point| point.kind == PathPointKind::PossibleAdverse)
            .count();
        Ok(())
    });
    if let Err(failure) = outcome {
        panic!("Seed {SEED}: {failure}");
    }
    let coverage = coverage.into_inner();
    println!("seed {SEED}: {coverage:#?}");
    assert_eq!(coverage.cases, CASES as usize);
    assert!(coverage.refused <= CASES as usize / 20, "{coverage:#?}");
    assert!(coverage.trades >= CASES as usize / 2, "{coverage:#?}");
    assert!(coverage.questions >= 2 * CASES as usize, "{coverage:#?}");
    assert!(coverage.minute_references >= 2_000, "{coverage:#?}");
    for reached in [
        coverage.favourable_first,
        coverage.adverse_first,
        coverage.closed_in_parts,
        coverage.across_a_close,
        coverage.across_trade_dates,
        coverage.across_a_roll,
        coverage.possible_adverse,
        coverage.skipped_in_trades,
    ] {
        assert!(reached > 0, "{coverage:#?}");
    }
}
