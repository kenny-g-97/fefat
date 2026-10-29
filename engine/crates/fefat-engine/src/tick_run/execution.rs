//! A fill's execution in the book and the ledger, on ticks or on bars: closed and tagged with its
//! fee from the run's fee table on its trade date (F-TAG-01, F-FEE-01, F-FEE-02), its OCO group
//! cancelled (F-OCO-01), its exit plan's open lots settled (F-PLN-02), and the exit plan an entry
//! carries placed (F-OCO-02, F-PLN-01), before the run logs it (`fills`).

use fefat_core::costs::ScheduleUse;
use fefat_core::fidelity::Fidelity;
use fefat_core::fills::Fill;
use fefat_core::instants::{TradeDate, Ts};
use fefat_core::ledger::{Ledger, Position};
use fefat_core::orders::{Order, OrderId};
use fefat_core::units::{Money, Price, Qty};

use super::RunError;
use crate::book::{Book, Closing, WorkingOrder};
use crate::exit_plan::{self, FilledAt};
use crate::rules::{self, Priced};
use crate::settings::RunCosts;

/// Where a fill happens in the run: its instant, the point of the timeline after which its exit
/// plan's legs see records (F-OCO-02), the fidelity of the data that priced it (F-TAG-01), and
/// the trade date that prices its fee (F-FEE-01).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(super) struct FillPoint {
    pub(super) ts: Ts,
    pub(super) index: usize,
    pub(super) fidelity: Fidelity,
    pub(super) trade_date: TradeDate,
}

/// A fill as the book and the ledger took it, before the log records it: the fill, when its order
/// was placed, the cash its value moved, how the fee table's schedule that priced it was used
/// (F-FEE-01), the orders of its OCO group or its exit plan it cancelled, the stop of its plan it
/// reduced with the lots left (F-PLN-02), its exit plan's legs and initial risk in ticks
/// (F-RND-02), and whether it left the position flat, closing a trade (§20).
#[derive(Debug, Clone, PartialEq, Eq)]
pub(super) struct Execution {
    pub(super) fill: Fill,
    pub(super) placed_at: Ts,
    pub(super) cash: Money,
    pub(super) schedule: ScheduleUse,
    pub(super) cancelled: Vec<OrderId>,
    pub(super) reduced: Option<(OrderId, Qty)>,
    pub(super) legs: Vec<Order>,
    pub(super) risk: Option<u32>,
    pub(super) flat_after: bool,
}

impl Execution {
    /// A fill that set nothing off, a roll's leg placed at `placed_at` (F-ROL-02).
    pub(super) const fn alone(
        fill: Fill,
        placed_at: Ts,
        cash: Money,
        schedule: ScheduleUse,
        flat_after: bool,
    ) -> Self {
        Self {
            fill,
            placed_at,
            cash,
            schedule,
            cancelled: Vec::new(),
            reduced: None,
            legs: Vec::new(),
            risk: None,
            flat_after,
        }
    }
}

/// Closes `id` in the book, filled, and tags its fill as `priced` says at `at`, with the fee the
/// run's fee table prices it at on its trade date (F-TAG-01, F-FEE-01, F-FEE-02): the order, the
/// fill, and how the table's schedule that priced it was used.
pub(super) fn closed_and_tagged(
    book: &mut Book,
    ledger: &Ledger,
    costs: &RunCosts,
    id: OrderId,
    priced: &Priced,
    at: FillPoint,
) -> Result<(WorkingOrder, Fill, ScheduleUse), RunError> {
    let filled = book
        .close(id, Closing::Filled)
        .ok_or(RunError::UnknownOrder { order: id.0 })?;
    let instrument = ledger.instrument();
    let (lots, liquidity) = (filled.order.lots, rules::f_lmt_04(&filled));
    let (fee, schedule) = costs.fee(&instrument, priced.price, lots, liquidity, at.trade_date)?;
    let tick = instrument.tick_size();
    let fill = rules::f_tag_01(&filled, priced, at.ts, at.fidelity, tick, fee)?;
    Ok((filled, fill, schedule))
}

/// Fills `id` as `priced` says at `at`, the market at `market`: the book closes it, the ledger
/// books it with its fee, its OCO group is cancelled (F-OCO-01), its plan settles its open lots
/// (F-PLN-02), and the exit plan of an entry is placed (F-OCO-02, F-PLN-01).
pub(super) fn execute(
    book: &mut Book,
    ledger: &mut Ledger,
    costs: &RunCosts,
    id: OrderId,
    priced: &Priced,
    at: FillPoint,
    market: Price,
) -> Result<Execution, RunError> {
    let (filled, fill, schedule) = closed_and_tagged(book, ledger, costs, id, priced, at)?;
    let tick = ledger.instrument().tick_size();
    let cash = ledger.book(&fill)?;
    let mut cancelled = book.group_of(&filled);
    for &other in &cancelled {
        book.close(other, Closing::Cancelled);
    }
    let settled = book.settle(&filled);
    cancelled.extend(settled.cancelled);
    let filled_at = FilledAt {
        ts: at.ts,
        index: at.index,
    };
    let (legs, risk) = exit_plan::place(book, &filled, priced.price, market, filled_at, tick)?;
    Ok(Execution {
        fill,
        placed_at: filled.order.placed_at,
        cash,
        schedule,
        cancelled,
        reduced: settled.reduced,
        legs,
        risk,
        flat_after: ledger.position() == Position::Flat,
    })
}
