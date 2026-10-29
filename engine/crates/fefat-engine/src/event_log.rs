//! The run's event log, as `fefat.reference.event_log` keeps it: every placement, activation,
//! trigger, fill, and cancellation, each break the working orders stay through, each ambiguous
//! bar, each stop its exit plan moved or reduced, each funding payment, each roll and the prices
//! it moved, and each default the run took, in the order they happen and with the rule behind
//! them, so that a fill can be followed from the record that priced it back to the decision that
//! placed its order.

use std::fmt;

use fefat_core::fills::Fill;
use fefat_core::instants::Ts;
use fefat_core::orders::{Order, OrderId, OrderKind};
use fefat_core::rolls::Roll;
use fefat_core::units::{Money, Price, Qty};

use crate::book::Shift;
use crate::exit_plan::Move;

/// What happened.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EventKind {
    /// An order placed by a decision, or a bracket's leg placed by its entry's fill.
    Placed,
    /// An order that saw its first record or bar and works (F-ACT-01, F-ACT-02).
    Active,
    /// A stop a trade reached (F-STP-01).
    Triggered,
    /// A fill.
    Filled,
    /// An order cancelled by a fill of its OCO group or by its strategy.
    Cancelled,
    /// The market closed while orders worked, which stay (F-SES-01).
    Break,
    /// A bar whose fills would differ with its extremes swapped (F-BAR-05).
    Ambiguous,
    /// A stop its exit plan moved, by breakeven or a trailing stop (F-PLN-03).
    Moved,
    /// A stop its exit plan reduced to the lots a target left (F-PLN-02).
    Reduced,
    /// An entry signal the template could not act on (F-ENT-02, F-SIZ-04).
    Skipped,
    /// A funding payment (F-FND-01).
    Funding,
    /// A roll of the front (F-ROL-01).
    Rolled,
    /// A default the run took, which its record shows (F-FEE-01).
    Warning,
}

impl fmt::Display for EventKind {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(match self {
            Self::Placed => "placed",
            Self::Active => "active",
            Self::Triggered => "triggered",
            Self::Filled => "filled",
            Self::Cancelled => "cancelled",
            Self::Break => "break",
            Self::Ambiguous => "ambiguous",
            Self::Moved => "moved",
            Self::Reduced => "reduced",
            Self::Skipped => "skipped",
            Self::Funding => "funding",
            Self::Rolled => "rolled",
            Self::Warning => "warning",
        })
    }
}

/// One event at `ts`, of `order` where it concerns one, under `rule`, with the reference
/// engine's words for it.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LogEntry {
    /// When.
    pub ts: Ts,
    /// What happened.
    pub kind: EventKind,
    /// The order it concerns, if one.
    pub order: Option<OrderId>,
    /// The rule of the specification behind it, if one.
    pub rule: Option<&'static str>,
    /// What happened, in words.
    pub text: String,
}

impl LogEntry {
    /// An order a decision placed, active the run's latency later (F-ACT-01).
    pub(crate) fn placed(order: &Order) -> Self {
        let text = format!(
            "order {}: {}, active from {}",
            order.id.0,
            described(order),
            order.activation
        );
        Self::of(
            order.placed_at,
            EventKind::Placed,
            Some(order.id),
            "F-ACT-01",
            text,
        )
    }

    /// A leg of an exit plan that its entry's fill placed (F-OCO-02).
    pub(crate) fn bracket_placed(leg: &Order, entry: OrderId) -> Self {
        let text = format!(
            "order {}: {}, the exit plan of order {}",
            leg.id.0,
            described(leg),
            entry.0
        );
        Self::of(
            leg.placed_at,
            EventKind::Placed,
            Some(leg.id),
            "F-OCO-02",
            text,
        )
    }

    /// An order that sees its first record and works (F-ACT-01).
    pub(crate) fn active(ts: Ts, order: OrderId) -> Self {
        let text = format!("order {} sees its first record", order.0);
        Self::of(ts, EventKind::Active, Some(order), "F-ACT-01", text)
    }

    /// An order that sees its first bar and works (F-ACT-02), logged at the bar's close.
    pub(crate) fn active_on_bar(ts: Ts, order: OrderId) -> Self {
        let text = format!("order {} sees its first bar", order.0);
        Self::of(ts, EventKind::Active, Some(order), "F-ACT-02", text)
    }

    /// A bar whose extremes, swapped, would fill otherwise (F-BAR-05), logged at its close.
    pub(crate) fn ambiguous(ts: Ts) -> Self {
        Self {
            ts,
            kind: EventKind::Ambiguous,
            order: None,
            rule: Some("F-BAR-05"),
            text: "with its extremes swapped the bar fills otherwise".to_owned(),
        }
    }

    /// A stop at `stop` that the trade at `trade` reached (F-STP-01).
    pub(crate) fn triggered(ts: Ts, order: OrderId, stop: Price, trade: Price) -> Self {
        let text = format!(
            "order {}: the trade at {trade} reached the stop at {stop}",
            order.0
        );
        Self::of(ts, EventKind::Triggered, Some(order), "F-STP-01", text)
    }

    /// A fill, by the rule that priced it.
    pub(crate) fn filled(fill: &Fill) -> Self {
        let mut text = format!(
            "order {}: {} {} at {}, {}",
            fill.order.0, fill.side, fill.lots, fill.price, fill.liquidity
        );
        if fill.flags.ambiguous {
            text.push_str(", ambiguous");
        }
        if fill.flags.size_exceeded {
            text.push_str(", size_exceeded");
        }
        Self::of(
            fill.ts,
            EventKind::Filled,
            Some(fill.order),
            fill.rule.id(),
            text,
        )
    }

    /// An order cancelled because `filled`, of its OCO group, filled (F-OCO-01).
    pub(crate) fn cancelled_by_group(ts: Ts, order: OrderId, filled: OrderId) -> Self {
        let text = format!("order {}: order {} of its group filled", order.0, filled.0);
        Self::of(ts, EventKind::Cancelled, Some(order), "F-OCO-01", text)
    }

    /// The stop `stop` its plan reduced to `lots` when `filled`, a target of the plan, filled
    /// (F-PLN-02).
    pub(crate) fn reduced(ts: Ts, stop: OrderId, lots: Qty, filled: OrderId) -> Self {
        let text = format!(
            "order {}: reduced to {lots}, order {} of its plan filled",
            stop.0, filled.0
        );
        Self::of(ts, EventKind::Reduced, Some(stop), "F-PLN-02", text)
    }

    /// A stop its plan moved (F-PLN-03), under the rule that moved it.
    pub(crate) fn moved(ts: Ts, moved: &Move) -> Self {
        let text = format!(
            "order {}: the stop moved from {} to {}",
            moved.order.0, moved.before, moved.after
        );
        Self::of(
            ts,
            EventKind::Moved,
            Some(moved.order),
            moved.rule.id(),
            text,
        )
    }

    /// An entry whose time to live ended, cancelled at the decision `ts` (F-ENT-03).
    pub(crate) fn expired(ts: Ts, order: OrderId) -> Self {
        let text = format!("order {}: its time to live has ended", order.0);
        Self::of(ts, EventKind::Cancelled, Some(order), "F-ENT-03", text)
    }

    /// An entry signal the strategy could not act on at `ts`, and why, under `rule`.
    pub(crate) fn skipped(ts: Ts, why: &str, rule: &'static str) -> Self {
        Self {
            ts,
            kind: EventKind::Skipped,
            order: None,
            rule: Some(rule),
            text: format!("no entry: {why}"),
        }
    }

    /// An order its strategy cancelled.
    pub(crate) fn cancelled_by_strategy(ts: Ts, order: OrderId) -> Self {
        Self {
            ts,
            kind: EventKind::Cancelled,
            order: Some(order),
            rule: None,
            text: format!("order {}: cancelled by the strategy", order.0),
        }
    }

    /// A funding payment at `ts`, `change` to the cash, at the mark (F-FND-01).
    pub(crate) fn funding(ts: Ts, change: Money, mark: Price) -> Self {
        Self {
            ts,
            kind: EventKind::Funding,
            order: None,
            rule: Some("F-FND-01"),
            text: format!("{change} at the mark {mark}"),
        }
    }

    /// A roll at `ts`: the front passes from one contract to the next, its prices by the gap
    /// (F-ROL-01).
    pub(crate) fn rolled(ts: Ts, roll: &Roll) -> Self {
        Self {
            ts,
            kind: EventKind::Rolled,
            order: None,
            rule: Some("F-ROL-01"),
            text: format!(
                "the front passes from {} to {}, a gap of {} ({})",
                roll.rolled_from,
                roll.contract,
                roll.gap,
                roll.reason.word()
            ),
        }
    }

    /// An order a roll moved by its gap (F-ROL-03).
    pub(crate) fn shifted(ts: Ts, shift: &Shift) -> Self {
        let text = format!(
            "order {}: moved by the roll's gap from {} to {}",
            shift.order.0, shift.before, shift.after
        );
        Self::of(ts, EventKind::Moved, Some(shift.order), "F-ROL-03", text)
    }

    /// A leg of a roll, a market order already sent (F-ROL-02).
    pub(crate) fn roll_leg(order: &Order) -> Self {
        let text = format!(
            "order {}: {}, a leg of the roll",
            order.id.0,
            described(order)
        );
        let (ts, id) = (order.placed_at, Some(order.id));
        Self::of(ts, EventKind::Placed, id, "F-ROL-02", text)
    }

    /// An order of the position's exit plan, or an exit, that a flattening roll cancelled
    /// (F-ROL-04).
    pub(crate) fn cancelled_by_roll(ts: Ts, order: OrderId) -> Self {
        let text = format!(
            "order {}: the roll's close leg closes the position",
            order.0
        );
        Self::of(ts, EventKind::Cancelled, Some(order), "F-ROL-04", text)
    }

    /// The first fill the fee table's first schedule prices before its date (F-FEE-01).
    pub(crate) fn fee_table_extended(fill: &Fill) -> Self {
        let text = format!(
            "order {}: the fee table's first schedule prices a fill of a trade date before it",
            fill.order.0
        );
        Self::of(
            fill.ts,
            EventKind::Warning,
            Some(fill.order),
            "F-FEE-01",
            text,
        )
    }

    /// The market closed while `working` orders worked, which stay (F-SES-01).
    pub(crate) fn market_closed(ts: Ts, working: &[OrderId]) -> Self {
        let ids: Vec<String> = working.iter().map(|order| order.0.to_string()).collect();
        Self {
            ts,
            kind: EventKind::Break,
            order: None,
            rule: Some("F-SES-01"),
            text: format!("the market is closed; orders {} stay", ids.join(", ")),
        }
    }

    fn of(
        ts: Ts,
        kind: EventKind,
        order: Option<OrderId>,
        rule: &'static str,
        text: String,
    ) -> Self {
        Self {
            ts,
            kind,
            order,
            rule: Some(rule),
            text,
        }
    }
}

/// Such as `sell stop at 4995 x 1`.
fn described(order: &Order) -> String {
    let at = match order.kind {
        OrderKind::Market => String::new(),
        OrderKind::StopMarket { stop } => format!(" at {stop}"),
        OrderKind::Limit { limit } => format!(" at {limit}"),
    };
    format!("{} {}{at} x {}", order.side, order.kind, order.lots)
}
