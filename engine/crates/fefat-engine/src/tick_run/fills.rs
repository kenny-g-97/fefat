//! How a record of the tick level works the run's orders (`fefat.reference.engine._on_record`):
//! the market's hours (F-SES-01, F-SES-02), the orders that see their first record (F-ACT-01,
//! F-MKT-01, F-MKT-02, F-STP-05), stops triggered and filled (F-STP-01 to F-STP-03), limits filled
//! or resting (F-LMT-01 to F-LMT-04); and each fill, on ticks or on bars, executed in the book
//! and the ledger with its OCO group (F-OCO-01) and its bracket (F-OCO-02), then logged.

use fefat_core::fidelity::Fidelity;
use fefat_core::fills::PricingRule;
use fefat_core::instants::Ts;
use fefat_core::ledger::Ledger;
use fefat_core::market_data::MarketDataReader;
use fefat_core::orders::{Order, OrderId, OrderKind, OrderRole, OrderState, TimeInForce};
use fefat_core::units::Price;

use super::{BookedFill, RunError, TickRecord, TickRun};
use crate::book::{Book, BracketLink, Closing, WorkingOrder};
use crate::event_log::LogEntry;
use crate::rules::{self, Priced};

/// Where a fill happens in the run: its instant, the point of the timeline after which its
/// bracket's legs see records (F-OCO-02), and the fidelity of the data that priced it (F-TAG-01).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(super) struct FillPoint {
    pub(super) ts: Ts,
    pub(super) index: usize,
    pub(super) fidelity: Fidelity,
}

/// A fill as the book and the ledger took it, before the log records it: the fill with the cash
/// its value moved, the orders of its OCO group it cancelled, and its bracket's legs.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(super) struct Execution {
    pub(super) booked: BookedFill,
    pub(super) cancelled: Vec<OrderId>,
    pub(super) legs: Vec<Order>,
}

/// Fills `id` as `priced` says at `at`: the book closes it, the ledger books it, its OCO group is
/// cancelled (F-OCO-01), and its bracket placed (F-OCO-02).
pub(super) fn execute(
    book: &mut Book,
    ledger: &mut Ledger,
    id: OrderId,
    priced: &Priced,
    at: FillPoint,
) -> Result<Execution, RunError> {
    let filled = book
        .close(id, Closing::Filled)
        .ok_or(RunError::UnknownOrder { order: id.0 })?;
    let tick = ledger.instrument().tick_size();
    let fill = rules::f_tag_01(&filled, priced, at.ts, at.fidelity, tick)?;
    let cash = ledger.book(&fill)?;
    let cancelled = book.group_of(&filled);
    for &other in &cancelled {
        book.close(other, Closing::Cancelled);
    }
    let legs = place_bracket(book, &filled, priced.price, at, tick)?;
    Ok(Execution {
        booked: BookedFill { fill, cash },
        cancelled,
        legs,
    })
}

/// The stop and the target of `entry`'s bracket, placed at its fill at `fill` as one OCO group,
/// active at once and seeing the records after the fill's (F-OCO-02).
fn place_bracket(
    book: &mut Book,
    entry: &WorkingOrder,
    fill: Price,
    at: FillPoint,
    tick: Price,
) -> Result<Vec<Order>, RunError> {
    let BracketLink::Entry(bracket) = entry.link else {
        return Ok(Vec::new());
    };
    let (stop, target) = bracket.prices(entry.order.side, fill, tick)?;
    let stop_id = bracket.stop.id.unwrap_or_else(|| book.new_id());
    let target_id = bracket.target.id.unwrap_or_else(|| book.new_id());
    let legs = [
        (stop_id, OrderKind::StopMarket { stop }, OrderRole::Stop),
        (
            target_id,
            OrderKind::Limit { limit: target },
            OrderRole::Target,
        ),
    ];
    let mut placed = Vec::with_capacity(legs.len());
    for (id, kind, role) in legs {
        let order = Order {
            id,
            side: entry.order.side.opposite(),
            lots: entry.order.lots,
            kind,
            role,
            time_in_force: TimeInForce::GoodTillCancelled,
            placed_at: at.ts,
            activation: at.ts,
            oco: None,
        };
        let leg = BracketLink::LegOf(entry.order.id);
        book.place(WorkingOrder::placed(order, at.index, leg));
        placed.push(order);
    }
    Ok(placed)
}

impl<R: MarketDataReader> TickRun<'_, R> {
    /// A record: the stops the record before triggered, market orders since, which fill before
    /// the orders that become active on it (F-STP-02); the orders that see their first record;
    /// the stops this one triggers; then the limits, so that a stop beats a limit of its group
    /// (F-OCO-01); then the mark (F-MRK-01). Each loop takes the ids in its state at its start
    /// and passes over an order an earlier fill closed.
    pub(super) fn on_record(&mut self, record: &TickRecord, index: usize) -> Result<(), RunError> {
        if !self.tradeable(record.ts) {
            return Ok(());
        }
        if self.book.has_live() {
            self.work_orders(record, index)?;
        }
        self.ledger.mark_at(record.price);
        Ok(())
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
        let is_stop = |kind: &OrderKind| matches!(kind, OrderKind::StopMarket { .. });
        for id in self.book.ids_in(OrderState::Working, is_stop) {
            self.trigger(id, record, index)?;
        }
        let is_limit = |kind: &OrderKind| matches!(kind, OrderKind::Limit { .. });
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
        self.fill(id, Priced { rule, ..priced }, record.ts, index)
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
        let (Some(stop), Some((quoted, shown_size))) = (order.level(), record.quoted(side)) else {
            return Ok(());
        };
        let ticks = self.settings.slippage.stop;
        let priced = Priced {
            price: rules::f_stp_02(side, stop, quoted, ticks, self.tick())?,
            rule: PricingRule::StopAtNextQuote,
            reference: stop,
            shown_size: Some(shown_size),
        };
        self.fill(id, priced, record.ts, index)
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
        self.fill(id, priced, record.ts, index)
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
        self.fill(id, priced, record.ts, index)
    }

    /// Fills `id` as `priced` says at `ts`, the `index`th event, and logs it.
    fn fill(&mut self, id: OrderId, priced: Priced, ts: Ts, index: usize) -> Result<(), RunError> {
        let at = FillPoint {
            ts,
            index,
            fidelity: self.fidelity,
        };
        let execution = execute(&mut self.book, &mut self.ledger, id, &priced, at)?;
        self.record(execution);
        Ok(())
    }

    /// Logs a fill, the orders of its group it cancelled, and its bracket's legs, as the
    /// reference's `EventLog.filled` does, and keeps it among the run's fills.
    pub(super) fn record(&mut self, execution: Execution) {
        let Execution {
            booked,
            cancelled,
            legs,
        } = execution;
        let (ts, id) = (booked.fill.ts, booked.fill.order);
        self.log.push(LogEntry::filled(&booked.fill));
        let cancelled = cancelled
            .into_iter()
            .map(|other| LogEntry::cancelled_by_group(ts, other, id));
        self.log.extend(cancelled);
        let placed = legs.iter().map(|leg| LogEntry::bracket_placed(leg, id));
        self.log.extend(placed);
        self.fills.push(booked);
    }

    fn tick(&self) -> Price {
        self.ledger.instrument().tick_size()
    }
}
