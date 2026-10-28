//! Rolls in the loop (`docs/spec/fill-semantics.md` §29, step 2.9), as `fefat.reference.rolls`
//! works them: a roll is a session event at its open, which passes the run to the new front,
//! moves every price the run holds by the gap (F-ROL-03), and sends an open position's legs,
//! market orders already sent that fill before any other order on the first tradeable record or
//! bar after it (F-ROL-02), or the close leg alone with `roll_handling: flatten` (F-ROL-04).

use fefat_core::costs::ScheduleUse;
use fefat_core::fills::Fill;
use fefat_core::instants::Ts;
use fefat_core::instrument::Contract;
use fefat_core::ledger::Position;
use fefat_core::market_data::{BarRow, MarketDataReader};
use fefat_core::orders::{Order, OrderId, OrderKind, OrderRole, Side, TimeInForce};
use fefat_core::rolls::RollReason;
use fefat_core::units::{Price, Qty};

use super::execution::{Execution, FillPoint, closed_and_tagged};
use super::{RunError, TickRecord, TickRun};
use crate::book::WorkingOrder;
use crate::event_log::LogEntry;
use crate::rules;
use crate::settings::RollHandling;

/// A roll's legs on their way (F-ROL-02): the close leg, the open leg, none when the roll
/// flattens (F-ROL-04), the gap, and the contract rolled from.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(super) struct Transfer {
    close: OrderId,
    open: Option<OrderId>,
    gap: Price,
    rolled_from: Contract,
}

impl<R: MarketDataReader> TickRun<'_, R> {
    /// F-ROL-01 to F-ROL-04: the next roll, at `at`, the `index`th event: the front passes to
    /// its contract, every price the run holds moves by its gap, and an open position's legs are
    /// sent, both to transfer it, the close leg alone to flatten it.
    pub(super) fn roll(&mut self, at: Ts, index: usize) -> Result<(), RunError> {
        let Some(roll) = self.rolls.get(self.next_roll).cloned() else {
            return Ok(());
        };
        self.next_roll += 1;
        if self.transfer.is_some() {
            return Err(RunError::RollBeforeItsLegs { at });
        }
        self.log.push(LogEntry::rolled(at, &roll));
        let held = self.ledger.position();
        let flattens = self.roll_handling == RollHandling::Flatten;
        if flattens && held != Position::Flat {
            let cancelled = self.book.cancel_for_roll();
            let entries = cancelled
                .into_iter()
                .map(|id| LogEntry::cancelled_by_roll(at, id));
            self.log.extend(entries);
        }
        let shifts = self.book.shift_by(roll.gap)?;
        self.log
            .extend(shifts.iter().map(|shift| LogEntry::shifted(at, shift)));
        self.ledger.shift_mark(roll.gap)?;
        self.front = roll.contract;
        let (closing, lots) = match held {
            Position::Flat => return Ok(()),
            Position::Long(held) => (Side::Sell, held.lots()),
            Position::Short(held) => (Side::Buy, held.lots()),
        };
        let close = self.send_leg(closing, lots, roll.reason, at, index);
        let opening = closing.opposite();
        let open = (!flattens).then(|| self.send_leg(opening, lots, roll.reason, at, index));
        self.transfer = Some(Transfer {
            close,
            open,
            gap: roll.gap,
            rolled_from: roll.rolled_from,
        });
        Ok(())
    }

    /// A leg of a roll for `reason`: a market order already sent, which no decision cancels
    /// (F-ROL-02).
    fn send_leg(
        &mut self,
        side: Side,
        lots: Qty,
        reason: RollReason,
        at: Ts,
        index: usize,
    ) -> OrderId {
        let order = Order {
            id: self.book.new_id(),
            side,
            lots,
            kind: OrderKind::Market,
            role: OrderRole::Roll(reason),
            time_in_force: TimeInForce::GoodTillCancelled,
            placed_at: at,
            activation: at,
            oco: None,
        };
        self.log.push(LogEntry::roll_leg(&order));
        self.book.place(WorkingOrder::sent(order, index));
        order.id
    }

    /// The roll's legs on the first tradeable record after it, the `index`th event, before any
    /// other order's turn, each at the price a market order of its side takes there: the quote on
    /// TBBO, read no better than the trade, the trade on trades (F-ROL-02, F-SLP-01).
    pub(super) fn transfer_on_record(
        &mut self,
        record: &TickRecord,
        index: usize,
    ) -> Result<(), RunError> {
        let Some(transfer) = self.transfer.take() else {
            return Ok(());
        };
        let at = self.fill_point(record.ts, index);
        let priced = |side: Side| {
            let (price, shown) = record.quoted(side).unwrap_or((record.price, record.size));
            (price, Some(shown))
        };
        self.fill_legs(transfer, at, priced)
    }

    /// The roll's legs at the open of the first tradeable bar after it, filled at its close
    /// (F-ROL-02, F-BAR-06) and before the bar is replayed, so never flagged ambiguous.
    pub(super) fn transfer_on_bar(&mut self, bar: &BarRow, at: FillPoint) -> Result<(), RunError> {
        let Some(transfer) = self.transfer.take() else {
            return Ok(());
        };
        self.fill_legs(transfer, at, |_| (bar.open, None))
    }

    /// Fills the legs, the close leg first, each priced by `priced` for its side, the close leg's
    /// less the gap: a transfer's two leave the trade open and the position's open where it was
    /// (§20, F-TIM-02), and the close leg alone leaves the position flat (F-ROL-04).
    fn fill_legs(
        &mut self,
        transfer: Transfer,
        at: FillPoint,
        priced: impl Fn(Side) -> (Price, Option<Qty>),
    ) -> Result<(), RunError> {
        let Transfer {
            close,
            open,
            gap,
            rolled_from,
        } = transfer;
        let (close_fill, close_schedule) = self.leg(close, gap, at, &priced)?;
        let Some(open) = open else {
            let cash = self.ledger.book(&close_fill)?;
            let flat = self.ledger.position() == Position::Flat;
            let closed = Execution::alone(close_fill, cash, close_schedule, flat);
            return self.record_on(closed, rolled_from);
        };
        let (open_fill, open_schedule) = self.leg(open, Price(0), at, &priced)?;
        let [closed, opened] = self.ledger.transfer(&close_fill, &open_fill)?;
        let close_leg = Execution::alone(close_fill, closed, close_schedule, false);
        self.record_on(close_leg, rolled_from)?;
        let front = self.front.clone();
        let open_leg = Execution::alone(open_fill, opened, open_schedule, false);
        self.record_on(open_leg, front)
    }

    /// The leg `id`, less `gap` for the close leg, closed in the book and tagged as F-ROL-02
    /// prices it, with its fee: the fill, and how the fee table's schedule that priced it was used
    /// (F-FEE-01).
    fn leg(
        &mut self,
        id: OrderId,
        gap: Price,
        at: FillPoint,
        priced: &impl Fn(Side) -> (Price, Option<Qty>),
    ) -> Result<(Fill, ScheduleUse), RunError> {
        let order = self.book.order(id);
        let side = order
            .map(|order| order.order.side)
            .ok_or(RunError::UnknownOrder { order: id.0 })?;
        let (price, shown) = priced(side);
        let ticks = self.settings.slippage.market;
        let leg = rules::f_rol_02(side, price, shown, gap, ticks, self.tick())?;
        let (book, ledger, costs) = (&mut self.book, &self.ledger, &self.costs);
        let (_, fill, schedule) = closed_and_tagged(book, ledger, costs, id, &leg, at)?;
        Ok((fill, schedule))
    }
}
