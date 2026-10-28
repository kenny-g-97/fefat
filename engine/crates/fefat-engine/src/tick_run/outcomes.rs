//! What the loop produces, step by step and at its end, and what stops it.

use fefat_core::costs::CostLine;
use fefat_core::fidelity::Fidelity;
use fefat_core::fills::Fill;
use fefat_core::instants::{TradeDate, Ts};
use fefat_core::instrument::Contract;
use fefat_core::ledger::{Ledger, LedgerError};
use fefat_core::market_data::{BarRow, MarketDataError};
use fefat_core::units::{Money, Overflow};
use thiserror::Error;

use super::TickRecord;
use crate::book::WorkingOrder;
use crate::event_log::LogEntry;
use crate::exit_plan::PlanError;
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
    /// A session event or a timer at this instant: a roll, or a funding time (F-CLK-02).
    Timer(Ts),
    /// The decision at this instant.
    Decision(Ts),
}

impl Stepped {
    /// The places of the run's timeline the step took: one for a record or a decision, and one
    /// for each record of a skipped block, as a full replay counts them.
    pub(super) const fn events(&self) -> usize {
        match self {
            Self::Skipped { units } => *units,
            Self::Record(_) | Self::Bar(_) | Self::Timer(_) | Self::Decision(_) => 1,
        }
    }
}

/// A fill with what its value moved the cash by, the reference engine's `Fill.cash`, and the
/// contract it is of (F-TAG-01, F-ROL-01).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BookedFill {
    /// The fill, as F-TAG-01 records it.
    pub fill: Fill,
    /// The cash its value moved, rounded against the trader (F-FEE-03).
    pub cash: Money,
    /// The contract it is of: the run's front, or a roll's close leg's contract rolled from.
    pub contract: Contract,
}

/// What a run produces: every order in its last state, the fills, the event log, the ledger it
/// ends with, and its cost lines, each fee of a run that names a fee table and each funding
/// payment, in the order they were paid.
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
    /// The cost lines, in the order they were paid.
    pub costs: Vec<CostLine>,
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
    /// A stop triggered on TBBO, which fills at the next tradeable record's quote (F-STP-02),
    /// when that record is a trade or a bar, on a date that fills on a level without quotes:
    /// how it fills there is not yet specified.
    #[error(
        "Expected a TBBO record at {at} to fill stop {order}, triggered on TBBO (F-STP-02), got \
         a record of {fidelity}"
    )]
    TriggeredWithoutQuotes {
        /// The stop.
        order: u64,
        /// The record's instant.
        at: Ts,
        /// The level the record is of.
        fidelity: Fidelity,
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
    /// Rolls or funding times out of the order of their instants, or two at one instant.
    #[error(
        "Expected the {what} in ascending order of their instants, each once, got {next} after {previous}"
    )]
    TimersOutOfOrder {
        /// `rolls` or `funding times`.
        what: &'static str,
        /// The earlier instant.
        previous: Ts,
        /// The instant after it.
        next: Ts,
    },
    /// A roll that does not roll from the front the one before it left, or that rolls to it.
    #[error(
        "Expected the roll at {at} to roll from {front} to another contract, got {rolled_from} to \
         {contract} (F-ROL-01)"
    )]
    RollFromAnotherFront {
        /// The roll's open.
        at: Ts,
        /// The front the run trades.
        front: Contract,
        /// The contract the roll names as rolled from.
        rolled_from: Contract,
        /// The roll's new front.
        contract: Contract,
    },
    /// A roll whose open comes before the legs of the roll before it have filled.
    #[error(
        "Expected the legs of the roll before {at} to fill before it, got them still on their way \
         (F-ROL-01)"
    )]
    RollBeforeItsLegs {
        /// The second roll's open.
        at: Ts,
    },
    /// A funding time with an open position and no price to value it at.
    #[error("Expected a mark at the funding of {at}, got none (F-FND-01)")]
    FundingWithoutMark {
        /// The funding time.
        at: Ts,
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
    /// An entry's exit plan could not be placed.
    #[error(transparent)]
    Plan(#[from] PlanError),
}

fn listed(levels: &[Fidelity]) -> String {
    let names: Vec<String> = levels.iter().map(ToString::to_string).collect();
    names.join(", ")
}
