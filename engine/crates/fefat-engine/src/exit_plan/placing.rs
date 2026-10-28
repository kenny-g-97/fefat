//! An exit plan placed when its entry fills (F-PLN-01, F-OCO-02), as
//! `fefat.reference.exit_plan.place_exit_plan` places it: its stop, raised at once by a
//! trailing stop that works from the fill, then its targets with their shares of the lots.

use fefat_core::instants::Ts;
use fefat_core::orders::{Order, OrderKind, OrderRole, Side, TargetNumber, TimeInForce};
use fefat_core::units::{Overflow, Price};

use super::live::{LivePlan, Placement};
use super::{
    ExitPlan, PlanError, StopAt, TargetAt, TrailDistance, TrailingPlan, f_pln_01, f_rnd_01,
    f_rnd_02, f_trl_03, f_trl_04,
};
use crate::book::{Book, BracketLink, WorkingOrder};
use crate::exact_decimal::ExactDecimal;

/// When and where in the run a plan's entry filled: its instant, and the place of the run's
/// timeline after which the plan's legs see records (F-OCO-02).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct FilledAt {
    pub(crate) ts: Ts,
    pub(crate) index: usize,
}

/// F-PLN-01, F-OCO-02: the plan `entry` carries, placed when it fills at `fill` with the market at
/// `market`: its stop for all its lots, raised at once by a trailing stop that works from the fill
/// (F-PLN-04), then its targets in order, each with its share of the lots, a target of no lots not
/// placed. The legs work from the fill, without latency, and the book follows the plan while a
/// leg of it lives. Returns the legs placed.
pub(crate) fn place(
    book: &mut Book,
    entry: &WorkingOrder,
    fill: Price,
    market: Price,
    at: FilledAt,
    tick: Price,
) -> Result<Vec<Order>, PlanError> {
    let BracketLink::Entry(plan) = &entry.link else {
        return Ok(Vec::new());
    };
    let side = entry.order.side;
    let leg = |id, kind, lots, role| Order {
        id,
        side: side.opposite(),
        lots,
        kind,
        role,
        time_in_force: TimeInForce::GoodTillCancelled,
        placed_at: at.ts,
        activation: at.ts,
        oco: None,
    };
    let first = plan.stop.map(|stop| stop_level(stop.at, side, fill, tick));
    let first = first.transpose()?;
    let risk = first.map(|stop| f_rnd_02(side, fill, stop, tick));
    let mut legs = Vec::new();
    let mut stop = None;
    if let (Some(planned), Some(level)) = (plan.stop, first) {
        let level = raised_at_the_fill(plan.trailing.as_ref(), side, level, market, tick)?;
        let id = planned.id.unwrap_or_else(|| book.new_id());
        let kind = OrderKind::StopMarket { stop: level };
        legs.push(leg(id, kind, entry.order.lots, OrderRole::Stop));
        stop = Some(id);
    }
    let fractions: Vec<ExactDecimal> = plan.targets.iter().map(|target| target.fraction).collect();
    let shares = f_pln_01(entry.order.lots, &fractions)?;
    let mut targets = Vec::new();
    let numbered = plan.targets.iter().zip(shares).zip(TargetNumber::ALL);
    for ((target, share), number) in numbered.filter(|((_, share), _)| share.0 > 0) {
        let level = target_level(target.at, side, fill, risk, tick, number)?;
        let id = target.id.unwrap_or_else(|| book.new_id());
        let kind = OrderKind::Limit { limit: level };
        legs.push(leg(id, kind, share, OrderRole::Target(number)));
        targets.push((id, number));
    }
    if legs.is_empty() {
        return Ok(legs);
    }
    for order in &legs {
        let link = BracketLink::LegOf(entry.order.id);
        book.place(WorkingOrder::placed(*order, at.index, link));
    }
    let placement = Placement {
        side,
        fill,
        lots: entry.order.lots,
        risk,
        stop,
        targets,
        market,
    };
    book.follow(
        entry.order.id,
        LivePlan::placed(ExitPlan::clone(plan), placement),
    );
    Ok(legs)
}

/// A stop below a long's fill: at a price, in ticks, or a percentage of the fill price rounded
/// down to the tick (F-RND-01).
pub(crate) fn stop_level(
    at: StopAt,
    side: Side,
    fill: Price,
    tick: Price,
) -> Result<Price, Overflow> {
    match at {
        StopAt::Price(price) => Ok(price),
        StopAt::TicksFromFill(ticks) => side.opposite().moved(fill, ticks, tick),
        StopAt::PercentOfFill(percent) => {
            let ticks = f_rnd_01(percent, i128::from(fill.0).abs(), 100, tick, false)?;
            side.opposite().moved(fill, ticks, tick)
        }
    }
}

/// A target above a long's fill: at a price, in ticks, or an R multiple of the initial risk
/// rounded up (F-RND-01, F-RND-02).
fn target_level(
    at: TargetAt,
    side: Side,
    fill: Price,
    risk: Option<u32>,
    tick: Price,
    number: TargetNumber,
) -> Result<Price, PlanError> {
    let ticks = match (at, risk) {
        (TargetAt::Price(price), _) => return Ok(price),
        (TargetAt::TicksFromFill(ticks), _) => ticks,
        (TargetAt::RiskMultiple(multiple), Some(risk)) => {
            let units = i128::from(risk) * i128::from(tick.0);
            f_rnd_01(multiple, units, 1, tick, true)?
        }
        (TargetAt::RiskMultiple(_), None) => {
            return Err(PlanError::RiskWithoutStop {
                target: number.number(),
            });
        }
    };
    Ok(side.moved(fill, ticks, tick)?)
}

/// A stop's first level, raised at once by an intrabar trailing stop that works from the fill,
/// as it would at a price marked (F-PLN-04, F-TRL-03); a trailing stop by the column waits for a
/// decision.
fn raised_at_the_fill(
    trailing: Option<&TrailingPlan>,
    side: Side,
    stop: Price,
    market: Price,
    tick: Price,
) -> Result<Price, Overflow> {
    let Some(trailing) = trailing.filter(|trailing| trailing.activation.is_none()) else {
        return Ok(stop);
    };
    let ticks = match trailing.distance {
        TrailDistance::Ticks(ticks) | TrailDistance::Feature { ticks, .. } => ticks,
        TrailDistance::Column => return Ok(stop),
    };
    if !f_trl_04(trailing, false) {
        return Ok(stop);
    }
    let level = side.opposite().moved(market, ticks, tick)?;
    Ok(side.better(
        stop,
        f_trl_03(side, stop, level, trailing.step_ticks, tick)?,
    ))
}
