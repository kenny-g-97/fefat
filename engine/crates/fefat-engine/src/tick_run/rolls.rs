//! Rolls in the loop (`docs/spec/fill-semantics.md` §29, step 2.9), as `fefat.reference.rolls`
//! works them: a roll is a session event at its open, which passes the run to the new front,
//! moves every price the run holds by the gap (F-ROL-03), and sends an open position's legs,
//! market orders already sent that fill before any other order on the first tradeable record or
//! bar after it (F-ROL-02), or the close leg alone with `roll_handling: flatten` (F-ROL-04), or
//! none when an order on its way out of all the position's lots does the close leg's work.

use fefat_core::costs::ScheduleUse;
use fefat_core::fills::{Fill, PricingRule};
use fefat_core::instants::Ts;
use fefat_core::instrument::Contract;
use fefat_core::ledger::Position;
use fefat_core::market_data::{BarRow, MarketDataReader};
use fefat_core::orders::{Order, OrderId, OrderKind, OrderRole, Side, TimeInForce};
use fefat_core::rolls::RollReason;
use fefat_core::units::{Price, Qty};

use super::execution::{Execution, FillPoint, closed_and_tagged, execute};
use super::{RunError, TickRecord, TickRun};
use crate::book::WorkingOrder;
use crate::event_log::LogEntry;
use crate::rules::{self, Priced};
use crate::settings::RollHandling;

/// A roll's legs on their way (F-ROL-02): the close leg, or the order on its way out of the
/// position doing its work, the open leg, none when the roll flattens (F-ROL-04) or an order on
/// its way closes the position, the gap, and the contract rolled from.
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
    /// sent, both to transfer it, the close leg alone to flatten it, or none when an order on its
    /// way out of all its lots does the close leg's work.
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
        let closing = match held {
            Position::Flat => None,
            Position::Long(held) => Some((Side::Sell, held.lots())),
            Position::Short(held) => Some((Side::Buy, held.lots())),
        };
        let exiting = closing.and_then(|(side, lots)| self.book.on_its_way_out(side, lots, at));
        if flattens && held != Position::Flat {
            let cancelled = self.book.cancel_for_roll(exiting);
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
        let Some((closing, lots)) = closing else {
            return Ok(());
        };
        if let Some(close) = exiting {
            self.transfer = Some(Transfer {
                close,
                open: None,
                gap: roll.gap,
                rolled_from: roll.rolled_from,
            });
            return Ok(());
        }
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
        self.fill_legs(transfer, at, record.price, priced, |side| {
            record.quoted(side)
        })
    }

    /// The roll's legs at the open of the first tradeable bar after it, filled at its close
    /// (F-ROL-02, F-BAR-06) and before the bar is replayed, so never flagged ambiguous.
    pub(super) fn transfer_on_bar(&mut self, bar: &BarRow, at: FillPoint) -> Result<(), RunError> {
        let Some(transfer) = self.transfer.take() else {
            return Ok(());
        };
        self.fill_legs(transfer, at, bar.open, |_| (bar.open, None), |_| None)
    }

    /// Fills the legs, the close leg first, each priced by `priced` for its side, the close leg's
    /// less the gap, the market at `market`: a transfer's two leave the trade open and the
    /// position's open where it was (§20, F-TIM-02); the close leg alone, or the order on its way
    /// doing its work with its group and its plan, leaves the position flat (F-ROL-04).
    fn fill_legs(
        &mut self,
        transfer: Transfer,
        at: FillPoint,
        market: Price,
        priced: impl Fn(Side) -> (Price, Option<Qty>),
        quoted: impl Fn(Side) -> Option<(Price, Qty)>,
    ) -> Result<(), RunError> {
        let Transfer {
            close,
            open,
            gap,
            rolled_from,
        } = transfer;
        let close_priced = self.leg_priced(close, gap, at, &priced, &quoted)?;
        let Some(open) = open else {
            let (book, ledger, costs) = (&mut self.book, &mut self.ledger, &self.costs);
            let closed = execute(book, ledger, costs, close, &close_priced, at, market)?;
            return self.record_on(closed, rolled_from);
        };
        let (close_fill, close_schedule) = self.leg(close, &close_priced, at)?;
        let open_priced = self.leg_priced(open, Price(0), at, &priced, &quoted)?;
        let (open_fill, open_schedule) = self.leg(open, &open_priced, at)?;
        let [closed, opened] = self.ledger.transfer(&close_fill, &open_fill)?;
        let close_leg = Execution::alone(close_fill, closed, close_schedule, false);
        self.record_on(close_leg, rolled_from)?;
        let open_leg = Execution::alone(open_fill, opened, open_schedule, false);
        self.record(open_leg)
    }

    /// How F-ROL-02 prices the leg `id`, less `gap` for the close leg: at the price `priced` gives
    /// its side, moved by the market slippage ticks; a stop triggered on TBBO doing the close leg's
    /// work at its own F-STP-02 price on the quote `quoted` gives, less the gap.
    fn leg_priced(
        &self,
        id: OrderId,
        gap: Price,
        at: FillPoint,
        priced: &impl Fn(Side) -> (Price, Option<Qty>),
        quoted: &impl Fn(Side) -> Option<(Price, Qty)>,
    ) -> Result<Priced, RunError> {
        let order = self
            .book
            .order(id)
            .ok_or(RunError::UnknownOrder { order: id.0 })?;
        let side = order.order.side;
        if let OrderKind::StopMarket { stop } = order.order.kind {
            return self.stop_doing_the_close_leg(id, side, stop, gap, at, quoted);
        }
        let (price, shown) = priced(side);
        let ticks = self.settings.slippage.market;
        Ok(rules::f_rol_02(
            side,
            price,
            shown,
            gap,
            ticks,
            self.tick(),
        )?)
    }

    /// F-ROL-02, your choice of 2026-10-29: a stop triggered on TBBO doing the close leg's work
    /// fills at the price F-STP-02 gives it on the record, its quote bounded by its moved `stop`
    /// and the stop slippage ticks, less the gap, never better than its stop; a record without a
    /// quote is refused, as without the roll.
    fn stop_doing_the_close_leg(
        &self,
        id: OrderId,
        side: Side,
        stop: Price,
        gap: Price,
        at: FillPoint,
        quoted: &impl Fn(Side) -> Option<(Price, Qty)>,
    ) -> Result<Priced, RunError> {
        let Some((quote, shown_size)) = quoted(side) else {
            return Err(RunError::TriggeredWithoutQuotes {
                order: id.0,
                at: at.ts,
                fidelity: at.fidelity,
            });
        };
        let ticks = self.settings.slippage.stop;
        let price = rules::f_stp_02(side, stop, quote, ticks, self.tick())?;
        Ok(Priced {
            price: price.checked_sub(gap)?,
            rule: PricingRule::StopAtNextQuote,
            reference: stop.checked_sub(gap)?,
            shown_size: Some(shown_size),
        })
    }

    /// The leg `id` closed in the book and tagged as `leg` prices it, with its fee: the fill, and
    /// how the fee table's schedule that priced it was used (F-FEE-01).
    fn leg(
        &mut self,
        id: OrderId,
        leg: &Priced,
        at: FillPoint,
    ) -> Result<(Fill, ScheduleUse), RunError> {
        let (book, ledger, costs) = (&mut self.book, &self.ledger, &self.costs);
        let (_, fill, schedule) = closed_and_tagged(book, ledger, costs, id, leg, at)?;
        Ok((fill, schedule))
    }

    /// F-ROL-03: a run that ends before its roll's legs fill leaves the position on the old
    /// contract, valued at its own price, the mark less the gap.
    pub(super) fn value_before_the_legs(&mut self) -> Result<(), RunError> {
        let Some(transfer) = &self.transfer else {
            return Ok(());
        };
        let back = Price(0).checked_sub(transfer.gap)?;
        self.ledger.shift_mark(back)?;
        Ok(())
    }
}
