//! How a record of the tick level works the run's orders (`fefat.reference.engine._on_record`):
//! the market's hours (F-SES-01, F-SES-02), the orders that see their first record (F-ACT-01,
//! F-MKT-01, F-MKT-02, F-STP-05), stops triggered and filled (F-STP-01 to F-STP-03), limits filled
//! or resting (F-LMT-01 to F-LMT-04); and each fill, on ticks or on bars, executed in the book
//! and the ledger with its OCO group (F-OCO-01), its exit plan's open lots (F-PLN-02), and the
//! exit plan an entry carries (F-OCO-02, F-PLN-01), then logged; and the price marked, which each
//! plan follows (F-MRK-01, F-PLN-04).

use fefat_core::fidelity::Fidelity;
use fefat_core::fills::PricingRule;
use fefat_core::instants::Ts;
use fefat_core::ledger::Ledger;
use fefat_core::market_data::MarketDataReader;
use fefat_core::orders::{Order, OrderId, OrderKind, OrderState};
use fefat_core::units::{Price, Qty};

use super::{BookedFill, RunError, TickRecord, TickRun};
use crate::book::{Book, Closing};
use crate::event_log::LogEntry;
use crate::exit_plan::{self, FilledAt, Move};
use crate::rules::{self, Priced};

/// Where a fill happens in the run: its instant, the point of the timeline after which its exit
/// plan's legs see records (F-OCO-02), and the fidelity of the data that priced it (F-TAG-01).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(super) struct FillPoint {
    pub(super) ts: Ts,
    pub(super) index: usize,
    pub(super) fidelity: Fidelity,
}

/// A fill as the book and the ledger took it, before the log records it: the fill with the cash
/// its value moved, the orders of its OCO group or its exit plan it cancelled, the stop of its
/// plan it reduced with the lots left (F-PLN-02), and its exit plan's legs.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(super) struct Execution {
    pub(super) booked: BookedFill,
    pub(super) cancelled: Vec<OrderId>,
    pub(super) reduced: Option<(OrderId, Qty)>,
    pub(super) legs: Vec<Order>,
}

/// Fills `id` as `priced` says at `at`, the market at `market`: the book closes it, the ledger
/// books it, its OCO group is cancelled (F-OCO-01), its plan settles its open lots (F-PLN-02),
/// and the exit plan of an entry is placed (F-OCO-02, F-PLN-01).
pub(super) fn execute(
    book: &mut Book,
    ledger: &mut Ledger,
    id: OrderId,
    priced: &Priced,
    at: FillPoint,
    market: Price,
) -> Result<Execution, RunError> {
    let filled = book
        .close(id, Closing::Filled)
        .ok_or(RunError::UnknownOrder { order: id.0 })?;
    let tick = ledger.instrument().tick_size();
    let fill = rules::f_tag_01(&filled, priced, at.ts, at.fidelity, tick)?;
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
    let legs = exit_plan::place(book, &filled, priced.price, market, filled_at, tick)?;
    Ok(Execution {
        booked: BookedFill { fill, cash },
        cancelled,
        reduced: settled.reduced,
        legs,
    })
}

impl<R: MarketDataReader> TickRun<'_, R> {
    /// A record: the stops the record before triggered, market orders since, which fill before
    /// the orders that become active on it (F-STP-02); the orders that see their first record;
    /// the stops this one triggers; then the limits, so that a stop beats a limit of its group
    /// (F-OCO-01); then the mark (F-MRK-01), which each exit plan follows (F-PLN-04). Each loop
    /// takes the ids in its state at its start and passes over an order an earlier fill closed.
    pub(super) fn on_record(&mut self, record: &TickRecord, index: usize) -> Result<(), RunError> {
        if !self.tradeable(record.ts) {
            return Ok(());
        }
        if self.book.has_live() {
            self.work_orders(record, index)?;
        }
        self.ledger.mark_at(record.price);
        let moves = self.book.marked(record.price, self.tick())?;
        self.log_moves(record.ts, &moves);
        Ok(())
    }

    /// Logs the stops their plans moved at `ts` (F-PLN-03).
    pub(super) fn log_moves(&mut self, ts: Ts, moves: &[Move]) {
        let entries = moves.iter().map(|moved| LogEntry::moved(ts, moved));
        self.log.extend(entries);
    }

    /// The live orders' turn on a tradeable record, in the order of `on_record`.
    fn work_orders(&mut self, record: &TickRecord, index: usize) -> Result<(), RunError> {
        for id in self.book.ids_in(OrderState::Triggered, |_| true) {
            self.fill_triggered(id, record, index)?;
        }
        for id in self.book.ids_in(OrderState::Waiting, |_| true) {
            let waiting = self.book.live_in(id, OrderState::Waiting);
            if waiting.is_some_and(|order| rules::f_act_01(order, record.ts, index)) {
                self.first_record(id, record, index)?;
            }
        }
        for id in self.book.ids_in(OrderState::Working, is_stop) {
            self.trigger(id, record, index)?;
        }
        for id in self.book.ids_in(OrderState::Working, is_limit) {
            self.limit_on_record(id, record, index)?;
        }
        Ok(())
    }

    /// F-SES-02: whether the market trades at `ts`; at the first record of a break, the working
    /// orders stay and the log says so (F-SES-01).
    pub(super) fn tradeable(&mut self, ts: Ts) -> bool {
        let tradeable = self.hours.is_open(ts);
        if !tradeable && !self.in_break {
            let working = self.book.live_ids();
            if !working.is_empty() {
                self.log.push(LogEntry::market_closed(ts, &working));
            }
        }
        self.in_break = !tradeable;
        tradeable
    }

    /// An order's first record (F-ACT-01): a market order fills on it, at the quote on TBBO
    /// (F-MKT-01) or the trade on trades (F-MKT-02), and so does a stop at or through the market,
    /// the mark before this record, with the larger class's ticks (F-STP-05); any other order
    /// works from it.
    fn first_record(
        &mut self,
        id: OrderId,
        record: &TickRecord,
        index: usize,
    ) -> Result<(), RunError> {
        let market = self.ledger.mark();
        let order = self
            .book
            .activate(id)
            .ok_or(RunError::UnknownOrder { order: id.0 })?;
        let (side, kind) = (order.order.side, order.order.kind);
        let through = match kind {
            OrderKind::StopMarket { stop } => rules::f_stp_05(side, stop, market),
            OrderKind::Market | OrderKind::Limit { .. } => false,
        };
        if kind != OrderKind::Market && !through {
            self.log.push(LogEntry::active(record.ts, id));
            return Ok(());
        }
        let (ticks, tick) = (rules::f_slp_01(&self.settings, &kind, through), self.tick());
        let priced = match record.quoted(side) {
            Some((reference, shown_size)) => Priced {
                price: rules::f_mkt_01(side, reference, ticks, tick)?,
                rule: PricingRule::MarketAtQuote,
                reference,
                shown_size: Some(shown_size),
            },
            None => Priced {
                price: rules::f_mkt_02(side, record.price, ticks, tick)?,
                rule: PricingRule::MarketAtTrade,
                reference: record.price,
                shown_size: Some(record.size),
            },
        };
        let rule = if through {
            PricingRule::StopThroughMarket
        } else {
            priced.rule
        };
        self.fill(id, Priced { rule, ..priced }, record, index)
    }

    /// F-STP-02: a stop triggered on TBBO fills at this record's quote, never better than the
    /// stop plus the ticks.
    fn fill_triggered(
        &mut self,
        id: OrderId,
        record: &TickRecord,
        index: usize,
    ) -> Result<(), RunError> {
        let Some(order) = self.book.live_in(id, OrderState::Triggered) else {
            return Ok(());
        };
        let side = order.order.side;
        let Some(stop) = order.level() else {
            return Ok(());
        };
        let Some((quoted, shown_size)) = record.quoted(side) else {
            return Err(RunError::TriggeredWithoutQuotes {
                order: id.0,
                at: record.ts,
                fidelity: self.fidelity,
            });
        };
        let ticks = self.settings.slippage.stop;
        let priced = Priced {
            price: rules::f_stp_02(side, stop, quoted, ticks, self.tick())?,
            rule: PricingRule::StopAtNextQuote,
            reference: stop,
            shown_size: Some(shown_size),
        };
        self.fill(id, priced, record, index)
    }

    /// F-STP-01: a working stop the trade reaches triggers; on trades it fills at once (F-STP-03),
    /// on TBBO at the next tradeable record's quote (F-STP-02).
    fn trigger(&mut self, id: OrderId, record: &TickRecord, index: usize) -> Result<(), RunError> {
        let Some(order) = self.book.live_in(id, OrderState::Working) else {
            return Ok(());
        };
        let (side, Some(stop)) = (order.order.side, order.level()) else {
            return Ok(());
        };
        if !rules::f_stp_01(side, stop, record.price) {
            return Ok(());
        }
        self.log
            .push(LogEntry::triggered(record.ts, id, stop, record.price));
        if record.quote.is_some() {
            self.book
                .trigger(id)
                .ok_or(RunError::UnknownOrder { order: id.0 })?;
            return Ok(());
        }
        let ticks = self.settings.slippage.stop;
        let priced = Priced {
            price: rules::f_stp_03(side, stop, record.price, ticks, self.tick())?,
            rule: PricingRule::StopOnTrades,
            reference: stop,
            shown_size: Some(record.size),
        };
        self.fill(id, priced, record, index)
    }

    /// A working limit fills when the trade passes it (F-LMT-01, F-LMT-02), or on TBBO when its
    /// quote does, at its own price (F-LMT-03); otherwise it rests (F-LMT-04).
    fn limit_on_record(
        &mut self,
        id: OrderId,
        record: &TickRecord,
        index: usize,
    ) -> Result<(), RunError> {
        let Some(order) = self.book.live_in(id, OrderState::Working) else {
            return Ok(());
        };
        let (side, Some(limit)) = (order.order.side, order.level()) else {
            return Ok(());
        };
        let traded = rules::limit_past(&self.settings, side, limit, record.price);
        let (filled, shown_size) = match record.quoted(side) {
            Some((quoted, quoted_size)) if !traded => {
                (rules::f_lmt_02(side, limit, quoted), quoted_size)
            }
            Some(_) | None => (traded, record.size),
        };
        if !filled {
            self.book
                .rest(id)
                .ok_or(RunError::UnknownOrder { order: id.0 })?;
            return Ok(());
        }
        let priced = Priced {
            price: rules::f_lmt_03(limit),
            rule: PricingRule::LimitAtItsPrice,
            reference: limit,
            shown_size: Some(shown_size),
        };
        self.fill(id, priced, record, index)
    }

    /// Fills `id` as `priced` says on `record`, the `index`th event, the market at its trade, and
    /// logs it.
    fn fill(
        &mut self,
        id: OrderId,
        priced: Priced,
        record: &TickRecord,
        index: usize,
    ) -> Result<(), RunError> {
        let at = FillPoint {
            ts: record.ts,
            index,
            fidelity: self.fidelity,
        };
        let (book, ledger) = (&mut self.book, &mut self.ledger);
        let execution = execute(book, ledger, id, &priced, at, record.price)?;
        self.record(execution);
        Ok(())
    }

    /// Logs a fill, the orders of its group or its plan it cancelled, the stop of its plan it
    /// reduced, and its exit plan's legs, as the reference's `EventLog.filled` does, and keeps it
    /// among the run's fills.
    pub(super) fn record(&mut self, execution: Execution) {
        let Execution {
            booked,
            cancelled,
            reduced,
            legs,
        } = execution;
        let (ts, id) = (booked.fill.ts, booked.fill.order);
        self.log.push(LogEntry::filled(&booked.fill));
        let cancelled = cancelled
            .into_iter()
            .map(|other| LogEntry::cancelled_by_group(ts, other, id));
        self.log.extend(cancelled);
        if let Some((stop, lots)) = reduced {
            self.log.push(LogEntry::reduced(ts, stop, lots, id));
        }
        let placed = legs.iter().map(|leg| LogEntry::bracket_placed(leg, id));
        self.log.extend(placed);
        self.fills.push(booked);
    }

    fn tick(&self) -> Price {
        self.ledger.instrument().tick_size()
    }
}

/// Whether an order is a stop, which a price at or through its level triggers (F-STP-01).
pub(super) fn is_stop(kind: &OrderKind) -> bool {
    matches!(kind, OrderKind::StopMarket { .. })
}

/// Whether an order is a limit, which fills at its price or better (F-LMT-01).
pub(super) fn is_limit(kind: &OrderKind) -> bool {
    matches!(kind, OrderKind::Limit { .. })
}
