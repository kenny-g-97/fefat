//! The rules of `docs/spec/fill-semantics.md` that activate and fill orders on ticks, each a small
//! function named after its identifier as `fefat.reference.engine` names it (`f_stp_03` is
//! F-STP-03), so that each fill can be checked against the specification rule by rule. Every rule
//! is written for a buy, and a sell mirrors it (§1).

use fefat_core::fidelity::Fidelity;
use fefat_core::fills::{Fill, FillFlags, Liquidity, PricingRule};
use fefat_core::instants::Ts;
use fefat_core::orders::{OrderKind, Side};
use fefat_core::units::{Money, Overflow, Price, Qty};

use crate::book::WorkingOrder;
use crate::settings::{LimitFill, RunSettings};

/// How a fill is priced: its price, the rule that priced it, its reference before ticks
/// (F-TAG-01), and the size its record shows (F-QTY-01).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct Priced {
    pub(crate) price: Price,
    pub(crate) rule: PricingRule,
    pub(crate) reference: Price,
    pub(crate) shown_size: Qty,
}

/// F-ACT-01: on trades and TBBO an order sees the records after the point of the timeline that
/// placed it, its decision or its entry's fill, received at or after its activation.
pub(crate) fn f_act_01(order: &WorkingOrder, record_ts: Ts, index: usize) -> bool {
    index > order.seen_after && record_ts >= order.order.activation
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
    match (order.order.kind, order.rested) {
        (OrderKind::Limit { .. }, true) => Liquidity::Maker,
        _ => Liquidity::Taker,
    }
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

/// F-QTY-01: orders fill whole; a fill larger than the size its record shows is flagged.
pub(crate) fn f_qty_01(lots: Qty, shown_size: Qty) -> FillFlags {
    FillFlags {
        ambiguous: false,
        size_exceeded: lots > shown_size,
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
