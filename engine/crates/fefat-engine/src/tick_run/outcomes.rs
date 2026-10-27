//! What the loop produces, step by step and at its end, and what stops it.

use fefat_core::fidelity::Fidelity;
use fefat_core::fills::Fill;
use fefat_core::instants::{TradeDate, Ts};
use fefat_core::ledger::{Ledger, LedgerError};
use fefat_core::market_data::{BarRow, MarketDataError};
use fefat_core::units::{Money, Overflow};
use thiserror::Error;

use super::TickRecord;
use crate::book::WorkingOrder;
use crate::event_log::LogEntry;
use crate::strategy::DecisionError;

/// What one step of the run handled.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Stepped {
    /// A tick.
    Record(TickRecord),
    /// A stored bar, replayed as its pseudo-ticks.
    Bar(BarRow),
    /// A block of the finest records that no order could act on, passed over whole.
    Skipped {
        /// How many records it held.
        units: usize,
    },
    /// The decision at this instant.
    Decision(Ts),
}

impl Stepped {
    /// The places of the run's timeline the step took: one for a record or a decision, and one
    /// for each record of a skipped block, as a full replay counts them.
    pub(super) const fn events(&self) -> usize {
        match self {
            Self::Skipped { units } => *units,
            Self::Record(_) | Self::Bar(_) | Self::Decision(_) => 1,
        }
    }
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
#[derive(Debug, Clone, PartialEq, Eq)]
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

impl RunOutputs {
    /// The fills flagged ambiguous, which the run counts (F-BAR-05).
    pub fn ambiguous_fills(&self) -> usize {
        let flagged = self
            .fills
            .iter()
            .filter(|booked| booked.fill.flags.ambiguous);
        flagged.count()
    }
}

/// What stopped a run.
#[derive(Debug, Clone, PartialEq, Eq, Error)]
pub enum RunError {
    /// A trade date whose levels are all finer than the fidelity the run fills on.
    #[error(
        "Expected a level at or coarser than {fidelity} on {trade_date}, which holds {}",
        listed(.present)
    )]
    NoLevelAtOrCoarser {
        /// The trade date.
        trade_date: TradeDate,
        /// The finest fidelity the run fills on.
        fidelity: Fidelity,
        /// The levels the date holds, finest first.
        present: Vec<Fidelity>,
    },
    /// A bar that traded nothing, which no stored bar is (F-BAR-07).
    #[error("Expected stored bars with trades (F-BAR-07), got none closing {ts_close}")]
    BarWithoutTrades {
        /// The bar's close.
        ts_close: Ts,
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

fn listed(levels: &[Fidelity]) -> String {
    let names: Vec<String> = levels.iter().map(ToString::to_string).collect();
    names.join(", ")
}
