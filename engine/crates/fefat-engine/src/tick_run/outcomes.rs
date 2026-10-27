//! What the tick loop produces, step by step and at its end, and what stops it.

use fefat_core::fidelity::Fidelity;
use fefat_core::fills::Fill;
use fefat_core::instants::Ts;
use fefat_core::ledger::{Ledger, LedgerError};
use fefat_core::market_data::MarketDataError;
use fefat_core::units::{Money, Overflow};
use thiserror::Error;

use super::TickRecord;
use crate::book::WorkingOrder;
use crate::event_log::LogEntry;
use crate::strategy::DecisionError;

/// What one step of the run handled.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Stepped {
    /// A record.
    Record(TickRecord),
    /// The decision at this instant.
    Decision(Ts),
}

/// A fill with what its value moved the cash by, the reference engine's `Fill.cash`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct BookedFill {
    /// The fill, as F-TAG-01 records it.
    pub fill: Fill,
    /// The cash its value moved, rounded against the trader (F-FEE-03).
    pub cash: Money,
}

/// What a run produces: every order in its last state, the fills, the event log, and the ledger
/// it ends with.
#[derive(Debug, Clone)]
pub struct RunOutputs {
    /// Every order, by id.
    pub orders: Vec<WorkingOrder>,
    /// The fills, in the order they happened.
    pub fills: Vec<BookedFill>,
    /// The event log.
    pub log: Vec<LogEntry>,
    /// The ledger at the end.
    pub ledger: Ledger,
}

/// What stopped a run.
#[derive(Debug, Clone, PartialEq, Eq, Error)]
pub enum RunError {
    /// A fidelity of bars, which step 2.7 replays.
    #[error(
        "Expected a tick fidelity, tbbo or trades, got {fidelity}: bar fidelities arrive in \
         step 2.7"
    )]
    BarFidelity {
        /// The fidelity asked for.
        fidelity: Fidelity,
    },
    /// Decision instants out of order, or one twice.
    #[error(
        "Expected decision instants in ascending order, each once, got {next} after {previous}"
    )]
    DecisionsOutOfOrder {
        /// The earlier instant.
        previous: Ts,
        /// The instant after it.
        next: Ts,
    },
    /// Records out of the order of their receive times, across trade dates.
    #[error("Expected records in the order of their ts_recv, got {next} after {previous}")]
    RecordsOutOfOrder {
        /// The earlier record's instant.
        previous: Ts,
        /// The next record's instant.
        next: Ts,
    },
    /// An order the run lost, which is a defect of the loop.
    #[error("Expected order {order} among the live orders, got none")]
    UnknownOrder {
        /// The order.
        order: u64,
    },
    /// The reader could not serve the records.
    #[error(transparent)]
    MarketData(#[from] MarketDataError),
    /// The ledger refused a fill.
    #[error(transparent)]
    Ledger(#[from] LedgerError),
    /// A price or an instant beyond 64 bits.
    #[error(transparent)]
    Overflow(#[from] Overflow),
    /// The strategy's decision was refused.
    #[error(transparent)]
    Decision(#[from] DecisionError),
}
