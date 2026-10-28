//! The exit plan's rules one by one, as `python/tests/test_reference_exit_plan.py` holds the
//! reference's; the scenarios S-template-008 to S-template-033 hold them on tapes.

use fefat_core::orders::{OrderId, Side, TargetNumber};
use fefat_core::strategy_spec::TrailUpdate;
use fefat_core::units::{Price, Qty};

use super::live::{LegSettlement, LivePlan, MoveRule, Placement, PlanRow, Proposal};
use super::{
    BreakevenPlan, ExitPlan, PlanError, TrailDistance, TrailingPlan, Trigger, f_brk_01, f_pln_01,
    f_pln_03, f_rnd_01, f_rnd_02, f_trl_03,
};
use crate::exact_decimal::ExactDecimal;

const TICK: Price = Price(250_000_000);

/// A price of `hundredths` hundredths of a point: `500_025` is 5000.25.
fn price(hundredths: i64) -> Price {
    Price(hundredths * 10_000_000)
}

fn exact(number: f64) -> ExactDecimal {
    ExactDecimal::of(number).unwrap()
}

/// A long of `lots` filled at 5000.00 with its stop, order 2, 12 ticks below, its targets from
/// order 3, and `plan`'s breakeven and trailing stop.
fn long_plan(plan: ExitPlan, lots: i64) -> LivePlan {
    let targets = (3..).map(OrderId).zip(TargetNumber::ALL);
    let targets = targets.take(plan.targets.len()).collect();
    let placement = Placement {
        side: Side::Buy,
        fill: price(500_000),
        lots: Qty(lots),
        risk: Some(12),
        stop: Some(OrderId(2)),
        targets,
        market: price(500_000),
    };
    LivePlan::placed(plan, placement)
}

fn with(breakeven: Option<BreakevenPlan>, trailing: Option<TrailingPlan>) -> ExitPlan {
    ExitPlan {
        stop: None,
        targets: Vec::new(),
        breakeven,
        trailing,
    }
}

const fn trailing_in_ticks(ticks: u32, activation: Option<Trigger>) -> TrailingPlan {
    TrailingPlan {
        distance: TrailDistance::Ticks(ticks),
        step_ticks: None,
        activation,
        update: TrailUpdate::Intrabar,
    }
}

#[test]
fn a_distance_rounds_toward_the_entry_for_a_stop_and_away_from_it_for_a_target() {
    // F-RND-01: 0.07 % of 5000.25 is 14.0007 ticks; 1.5 R of 7 ticks is 10.5 ticks.
    let percent = exact(0.07);
    assert_eq!(
        f_rnd_01(percent, 5_000_250_000_000, 100, TICK, false),
        Ok(14)
    );
    let risk = 7 * i128::from(TICK.0);
    assert_eq!(f_rnd_01(exact(1.5), risk, 1, TICK, true), Ok(11));
    assert_eq!(f_rnd_01(exact(1.5), risk, 1, TICK, false), Ok(10));
    assert_eq!(
        f_rnd_01(exact(0.01), 1, 1, TICK, false),
        Ok(1),
        "at least one tick"
    );
    // F-RND-02: a stop at 4997.00 under a fill at 5000.00 risks 12 ticks, and one at the fill 1.
    assert_eq!(
        f_rnd_02(Side::Buy, price(500_000), price(499_700), TICK),
        12
    );
    assert_eq!(
        f_rnd_02(Side::Sell, price(500_000), price(500_300), TICK),
        12
    );
    assert_eq!(f_rnd_02(Side::Buy, price(500_000), price(500_000), TICK), 1);
}

#[test]
fn each_target_takes_its_fraction_of_the_lots_left_rounded_down() {
    // F-PLN-01, S-template-010 and S-template-011.
    let (half, whole) = (exact(0.5), ExactDecimal::ONE);
    assert_eq!(
        f_pln_01(Qty(3), &[half, half, whole]),
        Ok(vec![Qty(1), Qty(1), Qty(1)])
    );
    assert_eq!(f_pln_01(Qty(1), &[half, whole]), Ok(vec![Qty(0), Qty(1)]));
    assert_eq!(f_pln_01(Qty(2), &[half, whole]), Ok(vec![Qty(1), Qty(1)]));
}

#[test]
fn a_stop_moves_up_only_and_never_to_the_market() {
    // F-PLN-03: a long's stop at 4997.00 with the market at 5001.00.
    let (stop, market) = (price(499_700), price(500_100));
    let up = f_pln_03(Side::Buy, stop, price(499_900), market, TICK);
    assert_eq!(up, Ok(Some(price(499_900))));
    let through = f_pln_03(Side::Buy, stop, price(500_200), market, TICK);
    assert_eq!(
        through,
        Ok(Some(price(500_075))),
        "one tick below the market"
    );
    assert_eq!(
        f_pln_03(Side::Buy, stop, price(499_600), market, TICK),
        Ok(None)
    );
    assert_eq!(f_pln_03(Side::Buy, stop, stop, market, TICK), Ok(None));
    // A short's stop moves down only, and never to or below the market.
    let short = f_pln_03(
        Side::Sell,
        price(500_300),
        price(499_800),
        price(499_900),
        TICK,
    );
    assert_eq!(short, Ok(Some(price(499_925))));
}

#[test]
fn breakeven_lies_at_the_fill_plus_its_offset_in_the_positions_favour() {
    // F-BRK-01, S-template-020.
    assert_eq!(
        f_brk_01(Side::Buy, price(500_000), 2, TICK),
        Ok(price(500_050))
    );
    assert_eq!(
        f_brk_01(Side::Buy, price(500_000), -2, TICK),
        Ok(price(499_950))
    );
    assert_eq!(
        f_brk_01(Side::Sell, price(500_000), 2, TICK),
        Ok(price(499_950))
    );
}

#[test]
fn a_trailing_stop_in_steps_moves_by_whole_steps_and_never_back() {
    // F-TRL-03, S-template-025: steps of 4 ticks from 4997.00 toward 4998.75 make one step.
    let stop = price(499_700);
    let stepped = f_trl_03(Side::Buy, stop, price(499_875), Some(4), TICK);
    assert_eq!(stepped, Ok(price(499_800)));
    assert_eq!(
        f_trl_03(Side::Buy, stop, price(499_775), Some(4), TICK),
        Ok(stop)
    );
    assert_eq!(
        f_trl_03(Side::Buy, stop, price(499_600), Some(4), TICK),
        Ok(stop)
    );
    assert_eq!(
        f_trl_03(Side::Buy, stop, price(499_875), None, TICK),
        Ok(price(499_875))
    );
}

#[test]
fn a_targets_fill_reduces_the_stop_and_the_last_lots_cancel_the_rest() {
    // F-PLN-02, S-template-008 and S-template-009.
    let targets = vec![
        super::PlannedTarget {
            at: super::TargetAt::TicksFromFill(8),
            id: None,
            fraction: exact(0.5),
        };
        2
    ];
    let plan = ExitPlan {
        targets,
        ..with(None, None)
    };
    let mut live = long_plan(plan, 2);
    assert_eq!(
        live.settled(OrderId(3), Qty(1)),
        LegSettlement::ReduceTheStop(Qty(1))
    );
    assert_eq!(
        live.settled(OrderId(4), Qty(1)),
        LegSettlement::CancelTheRest
    );
    let mut stopped = long_plan(with(None, None), 2);
    assert_eq!(
        stopped.settled(OrderId(2), Qty(2)),
        LegSettlement::CancelTheRest
    );
}

#[test]
fn breakeven_fires_at_its_trigger_and_after_its_target_then_holds_its_level() {
    // F-BRK-02: 8 ticks above 5000.00 is 5002.00; once fired, F-BRK-01 proposes its level at
    // every later price, so that a level the market held back is reached (S-template-073).
    let breakeven = BreakevenPlan {
        trigger: Trigger::Ticks(8),
        offset_ticks: 0,
    };
    let mut live = long_plan(with(Some(breakeven), None), 1);
    assert_eq!(live.at_price(price(500_175), TICK), Ok(Vec::new()));
    let fired = vec![Proposal {
        level: price(500_000),
        rule: MoveRule::Breakeven,
    }];
    assert_eq!(live.at_price(price(500_200), TICK), Ok(fired.clone()));
    assert_eq!(live.at_price(price(500_300), TICK), Ok(fired), "held");

    let after_first = BreakevenPlan {
        trigger: Trigger::AfterTarget(TargetNumber::First),
        offset_ticks: 0,
    };
    let targets = vec![super::PlannedTarget {
        at: super::TargetAt::TicksFromFill(8),
        id: None,
        fraction: exact(0.5),
    }];
    let plan = ExitPlan {
        targets,
        ..with(Some(after_first), None)
    };
    let mut live = long_plan(plan, 2);
    assert_eq!(live.at_price(price(500_300), TICK), Ok(Vec::new()));
    live.settled(OrderId(3), Qty(1));
    let moved = live.at_price(price(500_200), TICK).unwrap();
    assert_eq!(
        moved.first().map(|proposal| proposal.rule),
        Some(MoveRule::Breakeven)
    );
}

#[test]
fn a_trailing_stop_follows_the_best_price_from_its_activation() {
    // F-TRL-01: 4 ticks behind the best price, active once the trade is 8 ticks up.
    let trailing = trailing_in_ticks(4, Some(Trigger::Ticks(8)));
    let mut live = long_plan(with(None, Some(trailing)), 1);
    assert_eq!(
        live.at_price(price(500_150), TICK),
        Ok(Vec::new()),
        "not active yet"
    );
    let active = live.at_price(price(500_200), TICK).unwrap();
    assert_eq!(
        active.first().map(|proposal| proposal.level),
        Some(price(500_100))
    );
    let lower = live.at_price(price(500_100), TICK).unwrap();
    let held = lower.first().map(|proposal| proposal.level);
    assert_eq!(held, Some(price(500_100)), "the best price stays");
}

#[test]
fn the_stop_takes_the_highest_level_proposed_and_breakeven_among_equals() {
    // F-TRL-01: breakeven at 5000.00 and a trailing level at 5000.00 tie; the trailing level is
    // held one tick short of the market at 5000.25.
    let trailing = trailing_in_ticks(4, None);
    let live = long_plan(with(None, Some(trailing)), 1);
    let proposed = [
        Proposal {
            level: price(500_000),
            rule: MoveRule::Breakeven,
        },
        Proposal {
            level: price(500_000),
            rule: MoveRule::Trailing,
        },
    ];
    let chosen = live.chosen(price(499_700), &proposed, price(500_100), TICK);
    let rule = chosen.unwrap().map(|proposal| proposal.rule);
    assert_eq!(rule, Some(MoveRule::Breakeven));
    let capped = [Proposal {
        level: price(500_100),
        rule: MoveRule::Trailing,
    }];
    let chosen = live
        .chosen(price(499_700), &capped, price(500_025), TICK)
        .unwrap();
    assert_eq!(chosen.map(|proposal| proposal.level), Some(price(500_000)));
}

#[test]
fn a_trailing_stop_by_the_column_moves_at_decisions_to_trail_ref_on_the_tick() {
    // F-TRL-02, S-template-027.
    let by_column = TrailingPlan {
        distance: TrailDistance::Column,
        update: TrailUpdate::BarClose,
        ..trailing_in_ticks(1, None)
    };
    let mut live = long_plan(with(None, Some(by_column)), 1);
    assert_eq!(
        live.at_price(price(500_300), TICK),
        Ok(Vec::new()),
        "decisions alone"
    );
    let row = |trail_ref: i64| PlanRow {
        at: fefat_core::instants::Ts(0),
        trail_feature: None,
        trail_ref: Some(Price(trail_ref * 10_000_000)),
    };
    let proposed = live.at_decision(&row(499_900), TICK).unwrap();
    let to_trail_ref = Proposal {
        level: price(499_900),
        rule: MoveRule::Trailing,
    };
    assert_eq!(proposed, vec![to_trail_ref]);
    let off_the_tick = live.at_decision(&row(499_910), TICK);
    assert!(matches!(off_the_tick, Err(PlanError::OffTheTick { .. })));
}

#[test]
fn a_bar_beyond_a_trailing_plans_best_price_or_a_waiting_trigger_is_not_skipped() {
    // F-PLN-05: the best price is 5000.00 and the breakeven fires 8 ticks up, at 5002.00.
    let trailing = long_plan(with(None, Some(trailing_in_ticks(4, None))), 1);
    let at_its_level = Some(price(499_900));
    assert_eq!(
        trailing.untouched_by(at_its_level, price(499_000), price(500_000), TICK),
        Ok(true)
    );
    assert_eq!(
        trailing.untouched_by(at_its_level, price(499_000), price(500_025), TICK),
        Ok(false)
    );
    // S-template-072: a stop held a tick under the market, at 4998.00, below the trailing level
    // 4999.00, rises at prices under the best price, so no bar is skipped while it stands there.
    assert_eq!(
        trailing.untouched_by(Some(price(499_800)), price(499_850), price(499_975), TICK),
        Ok(false)
    );
    let breakeven = BreakevenPlan {
        trigger: Trigger::Ticks(8),
        offset_ticks: 0,
    };
    let mut waiting = long_plan(with(Some(breakeven), None), 1);
    assert_eq!(
        waiting.untouched_by(None, price(499_000), price(500_175), TICK),
        Ok(true)
    );
    assert_eq!(
        waiting.untouched_by(None, price(499_000), price(500_200), TICK),
        Ok(false)
    );
    // S-template-073: a fired breakeven whose stop the market held at 4999.75, below its level
    // 5000.00, still rises at prices under the best price, so no bar is skipped meanwhile.
    waiting.at_price(price(500_200), TICK).unwrap();
    assert_eq!(
        waiting.untouched_by(Some(price(499_975)), price(500_000), price(500_100), TICK),
        Ok(false)
    );
    assert_eq!(
        waiting.untouched_by(Some(price(500_000)), price(500_025), price(500_100), TICK),
        Ok(true)
    );
}
