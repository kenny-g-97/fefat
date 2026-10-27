//! The rules of `docs/spec/fill-semantics.md` that activate and fill orders, on ticks and on bars,
//! each a small function named after its identifier as `fefat.reference.engine` names it
//! (`f_stp_03` is F-STP-03), so that each fill can be checked against the specification rule by
//! rule. Every rule is written for a buy, and a sell mirrors it (§1).

use std::collections::BTreeSet;

use fefat_core::fidelity::Fidelity;
use fefat_core::fills::{Fill, FillFlags, Liquidity, PricingRule};
use fefat_core::instants::Ts;
use fefat_core::ledger::Position;
use fefat_core::market_data::BarRow;
use fefat_core::orders::{OrderId, OrderKind, Side};
use fefat_core::units::{Money, Overflow, Price, Qty};

use crate::book::WorkingOrder;
use crate::settings::{LimitFill, RunSettings};

/// How a fill is priced: its price, the rule that priced it, its reference before ticks
/// (F-TAG-01), and the size its record shows (F-QTY-01), none on bars.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct Priced {
    pub(crate) price: Price,
    pub(crate) rule: PricingRule,
    pub(crate) reference: Price,
    pub(crate) shown_size: Option<Qty>,
}

/// F-ACT-01: on trades and TBBO an order sees the records after the point of the timeline that
/// placed it, its decision or its entry's fill, received at or after its activation.
pub(crate) fn f_act_01(order: &WorkingOrder, record_ts: Ts, index: usize) -> bool {
    index > order.seen_after && record_ts >= order.order.activation
}

/// F-ACT-02: on bars an order sees the first bar closing after its activation, whole, and every
/// later one.
pub(crate) fn f_act_02(order: &WorkingOrder, bar: &BarRow) -> bool {
    bar.ts_close > order.order.activation
}

/// F-MKT-01: on TBBO, at the quote of the first record it sees, plus the ticks.
pub(crate) fn f_mkt_01(
    side: Side,
    quote: Price,
    ticks: u32,
    tick: Price,
) -> Result<Price, Overflow> {
    side.moved(quote, ticks, tick)
}

/// F-MKT-02: on trades, at the price of the first trade it sees, plus the ticks.
pub(crate) fn f_mkt_02(
    side: Side,
    trade: Price,
    ticks: u32,
    tick: Price,
) -> Result<Price, Overflow> {
    side.moved(trade, ticks, tick)
}

/// F-MKT-03: on bars, at the open of the first bar it sees, plus the ticks.
pub(crate) fn f_mkt_03(
    side: Side,
    bar_open: Price,
    ticks: u32,
    tick: Price,
) -> Result<Price, Overflow> {
    side.moved(bar_open, ticks, tick)
}

/// F-STP-01: a buy stop triggers on a price at or above it, a sell stop at or below it (CME).
pub(crate) fn f_stp_01(side: Side, stop: Price, price: Price) -> bool {
    match side {
        Side::Buy => price >= stop,
        Side::Sell => price <= stop,
    }
}

/// F-STP-02: on TBBO, a triggered stop fills at the next tradeable record's quote, never better
/// than the stop plus the ticks.
pub(crate) fn f_stp_02(
    side: Side,
    stop: Price,
    quote: Price,
    ticks: u32,
    tick: Price,
) -> Result<Price, Overflow> {
    Ok(side.worse(side.moved(stop, ticks, tick)?, quote))
}

/// F-STP-03: on trades, at the worse of the stop plus the ticks and the trigger trade's price: a
/// gap fills at the gap price, with no ticks beyond it.
pub(crate) fn f_stp_03(
    side: Side,
    stop: Price,
    trade: Price,
    ticks: u32,
    tick: Price,
) -> Result<Price, Overflow> {
    Ok(side.worse(side.moved(stop, ticks, tick)?, trade))
}

/// F-STP-04: on bars, at the stop plus the ticks where the path reaches it, and at the worse of
/// that and the open when the bar opens past it (`reached_at` is the open then, else the stop).
pub(crate) fn f_stp_04(
    side: Side,
    stop: Price,
    reached_at: Price,
    ticks: u32,
    tick: Price,
) -> Result<Price, Overflow> {
    Ok(side.worse(side.moved(stop, ticks, tick)?, reached_at))
}

/// F-STP-05: a stop at or through the market when it becomes active fills at once as a market
/// order; with no price seen yet it is on the right side.
pub(crate) fn f_stp_05(side: Side, stop: Price, market: Option<Price>) -> bool {
    market.is_some_and(|market| match side {
        Side::Buy => stop <= market,
        Side::Sell => stop >= market,
    })
}

/// F-LMT-01: a limit fills when the market trades through it: a buy on a price below its limit.
pub(crate) fn f_lmt_01(side: Side, limit: Price, price: Price) -> bool {
    match side {
        Side::Buy => price < limit,
        Side::Sell => price > limit,
    }
}

/// F-LMT-02: with `limit_fill: touch` a price at the limit is enough; on TBBO a quote at or past
/// the limit fills it whatever the setting (F-LMT-01).
pub(crate) fn f_lmt_02(side: Side, limit: Price, price: Price) -> bool {
    match side {
        Side::Buy => price <= limit,
        Side::Sell => price >= limit,
    }
}

/// F-LMT-01 or F-LMT-02, as the run's `limit_fill` says: whether a trade at `price` fills a limit.
pub(crate) fn limit_past(settings: &RunSettings, side: Side, limit: Price, price: Price) -> bool {
    match settings.limit_fill {
        LimitFill::Through => f_lmt_01(side, limit, price),
        LimitFill::Touch => f_lmt_02(side, limit, price),
    }
}

/// F-LMT-03: a limit fills at its own price, never better, even when the market jumps past it.
pub(crate) const fn f_lmt_03(limit: Price) -> Price {
    limit
}

/// F-LMT-04: a limit filled on the first price it sees is a taker, one filled later rested and is
/// a maker; market and stop fills are takers.
pub(crate) const fn f_lmt_04(order: &WorkingOrder) -> Liquidity {
    match (order.order.kind, order.has_rested()) {
        (OrderKind::Limit { .. }, true) => Liquidity::Maker,
        _ => Liquidity::Taker,
    }
}

/// One of a bar's two extremes, replayed in the order F-BAR-02 to F-BAR-04 give.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum Extreme {
    Low,
    High,
}

impl Extreme {
    /// The other extreme.
    pub(crate) const fn other(self) -> Self {
        match self {
            Self::Low => Self::High,
            Self::High => Self::Low,
        }
    }

    /// This extreme's price in `bar`.
    pub(crate) const fn of(self, bar: &BarRow) -> Price {
        match self {
            Self::Low => bar.low,
            Self::High => bar.high,
        }
    }
}

/// F-BAR-01: between two pseudo-ticks the path passes every price: it reaches a stop at its price
/// and a limit where it trades through it (or touches it); only the open can jump past a level.
/// The level the path from `point` to `extreme` reaches `order` at, or none.
pub(crate) fn f_bar_01(
    settings: &RunSettings,
    order: &WorkingOrder,
    point: Price,
    extreme: Price,
) -> Option<Price> {
    let (low, high) = (point.min(extreme), point.max(extreme));
    let side = order.order.side;
    match order.order.kind {
        OrderKind::StopMarket { stop } => (low <= stop && stop <= high).then_some(stop),
        OrderKind::Limit { limit } => {
            let nearest = match side {
                Side::Buy => low,
                Side::Sell => high,
            };
            limit_past(settings, side, limit, nearest).then(|| limit.max(low).min(high))
        }
        OrderKind::Market => None,
    }
}

/// F-BAR-02: holding a position after the open, the adverse extreme comes first: the low for a
/// long, the high for a short.
pub(crate) const fn f_bar_02(position: Position) -> Extreme {
    match position {
        Position::Long(_) => Extreme::Low,
        Position::Flat | Position::Short(_) => Extreme::High,
    }
}

/// F-BAR-03: flat after the open, the extreme favourable to the earliest placed working entry
/// comes first, the lower id at one instant: the high for a buy. With none, the order is moot.
pub(crate) fn f_bar_03<'book>(working: impl Iterator<Item = &'book WorkingOrder>) -> Extreme {
    let earliest = working.min_by_key(|order| (order.order.placed_at, order.order.id));
    match earliest.map(|order| order.order.side) {
        Some(Side::Buy) => Extreme::High,
        Some(Side::Sell) | None => Extreme::Low,
    }
}

/// F-BAR-04: after an entry fills inside a bar, the extremes not yet reached come adverse first
/// for the new position (F-BAR-02), and then the close.
pub(crate) fn f_bar_04(remaining: &mut [Extreme], position: Position) {
    let adverse = f_bar_02(position);
    remaining.sort_by_key(|extreme| *extreme != adverse);
}

/// F-BAR-05: a bar is ambiguous when replaying it with its extremes the other way round gives
/// other fills: another order, another price, or none.
pub(crate) fn f_bar_05(
    real: impl IntoIterator<Item = (OrderId, Price)>,
    swapped: impl IntoIterator<Item = (OrderId, Price)>,
) -> bool {
    real.into_iter().collect::<BTreeSet<_>>() != swapped.into_iter().collect::<BTreeSet<_>>()
}

/// F-BAR-06: a bar's pseudo-ticks happen at its close, when it is available, and its fills carry
/// it.
pub(crate) const fn f_bar_06(bar: &BarRow) -> Ts {
    bar.ts_close
}

/// F-BAR-07: only stored bars are replayed: a bucket without trades has none, so the
/// `zero_volume` rows of the session grid never reach the engine. Whether `bar` is a stored one.
pub(crate) const fn f_bar_07(bar: &BarRow) -> bool {
    bar.volume.0 > 0
}

/// F-SLP-01: the slippage ticks of an order's class, market or stop-market; a stop through the
/// market takes the larger of the two (F-STP-05).
pub(crate) fn f_slp_01(settings: &RunSettings, kind: &OrderKind, through: bool) -> u32 {
    let ticks = settings.slippage;
    match (kind, through) {
        (_, true) => ticks.market.max(ticks.stop),
        (OrderKind::Market, false) => ticks.market,
        (_, false) => ticks.stop,
    }
}

/// F-QTY-01: orders fill whole; on trades and TBBO a fill larger than the size its record shows
/// is flagged.
pub(crate) fn f_qty_01(lots: Qty, shown_size: Option<Qty>) -> FillFlags {
    FillFlags {
        ambiguous: false,
        size_exceeded: shown_size.is_some_and(|shown| lots > shown),
    }
}

/// F-TAG-01: a fill records its fidelity, the rule that priced it, its liquidity, its flags, and
/// its slippage, the ticks it is worse than its reference by. Its fee is costs' (step 2.9).
pub(crate) fn f_tag_01(
    order: &WorkingOrder,
    priced: &Priced,
    ts: Ts,
    fidelity: Fidelity,
    tick: Price,
) -> Result<Fill, Overflow> {
    let order_side = order.order.side;
    let worse_by = priced.price.checked_sub(priced.reference)?.0;
    let slippage = worse_by.checked_mul(order_side.sign()).ok_or(Overflow {
        operation: "a fill's slippage",
        left: worse_by.into(),
        right: order_side.sign().into(),
    })?;
    Ok(Fill {
        order: order.order.id,
        role: order.order.role,
        side: order_side,
        lots: order.order.lots,
        ts,
        price: priced.price,
        rule: priced.rule,
        fidelity,
        liquidity: f_lmt_04(order),
        slippage_ticks: slippage.div_euclid(tick.0),
        flags: f_qty_01(order.order.lots, priced.shown_size),
        fee: Money(0),
    })
}
