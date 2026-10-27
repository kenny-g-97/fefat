//! The run's event log, as `fefat.reference.event_log` keeps it: every placement, activation,
//! trigger, fill, and cancellation, and each break the working orders stay through, in the order
//! they happen and with the rule behind them, so that a fill can be followed from the record that
//! priced it back to the decision that placed its order.

use std::fmt;

use fefat_core::fills::Fill;
use fefat_core::instants::Ts;
use fefat_core::orders::{Order, OrderId, OrderKind};
use fefat_core::units::Price;

/// What happened.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EventKind {
    /// An order placed by a decision, or a bracket's leg placed by its entry's fill.
    Placed,
    /// An order that saw its first record and works (F-ACT-01).
    Active,
    /// A stop a trade reached (F-STP-01).
    Triggered,
    /// A fill.
    Filled,
    /// An order cancelled by a fill of its OCO group or by its strategy.
    Cancelled,
    /// The market closed while orders worked, which stay (F-SES-01).
    Break,
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

    /// A bracket's leg that its entry's fill placed (F-OCO-02).
    pub(crate) fn bracket_placed(leg: &Order, entry: OrderId) -> Self {
        let text = format!(
            "order {}: {}, the bracket of order {}",
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
