//! How a record of the tick level works the run's orders (`fefat.reference.engine._on_record`):
//! the market's hours (F-SES-01, F-SES-02), the orders that see their first record (F-ACT-01,
//! F-MKT-01, F-MKT-02, F-STP-05), stops triggered and filled (F-STP-01 to F-STP-03), limits filled
//! or resting (F-LMT-01 to F-LMT-04); and each fill, on ticks or on bars, executed in the book
//! and the ledger with its fee (F-FEE-01, F-FEE-02), its OCO group (F-OCO-01), its exit plan's
//! open lots (F-PLN-02), and the exit plan an entry carries (F-OCO-02, F-PLN-01), then logged on
//! the run's front with its cost line; and the price marked, which each plan follows (F-MRK-01,
//! F-PLN-04).

use fefat_core::costs::{CostLine, CostReason};
use fefat_core::fidelity::Fidelity;
use fefat_core::fills::{Fill, PricingRule};
use fefat_core::instants::{TradeDate, Ts};
use fefat_core::instrument::Contract;
use fefat_core::ledger::{Ledger, Position};
use fefat_core::market_data::MarketDataReader;
use fefat_core::orders::{Order, OrderId, OrderKind, OrderState};
use fefat_core::units::{Money, Price, Qty};

use super::{BookedFill, RunError, TickRecord, TickRun};
use crate::book::{Book, Closing, WorkingOrder};
use crate::event_log::LogEntry;
use crate::exit_plan::{self, FilledAt, Move};
use crate::rules::{self, Priced};
use crate::settings::RunCosts;
use crate::strategy::ClosedTrade;

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

/// A fill as the book and the ledger took it, before the log records it: the fill, the cash its
/// value moved, whether the fee table's first schedule priced it before its date (F-FEE-01), the
/// orders of its OCO group or its exit plan it cancelled, the stop of its plan it reduced with the
/// lots left (F-PLN-02), its exit plan's legs, and whether it left the position flat, closing a
/// trade (§20).
#[derive(Debug, Clone, PartialEq, Eq)]
pub(super) struct Execution {
    pub(super) fill: Fill,
    pub(super) cash: Money,
    pub(super) extended: bool,
    pub(super) cancelled: Vec<OrderId>,
    pub(super) reduced: Option<(OrderId, Qty)>,
    pub(super) legs: Vec<Order>,
    pub(super) flat_after: bool,
}

impl Execution {
    /// A fill that set nothing off, a roll's leg (F-ROL-02).
    pub(super) const fn alone(fill: Fill, cash: Money, extended: bool, flat_after: bool) -> Self {
        Self {
            fill,
            cash,
            extended,
            cancelled: Vec::new(),
            reduced: None,
            legs: Vec::new(),
            flat_after,
        }
    }
}

/// Closes `id` in the book, filled, and tags its fill as `priced` says at `at`, with the fee the
/// run's fee table prices it at on its trade date (F-TAG-01, F-FEE-01, F-FEE-02): the order, the
/// fill, and whether the table's first schedule priced it before its date.
pub(super) fn closed_and_tagged(
    book: &mut Book,
    ledger: &Ledger,
    costs: &RunCosts,
    id: OrderId,
    priced: &Priced,
    at: FillPoint,
) -> Result<(WorkingOrder, Fill, bool), RunError> {
    let filled = book
        .close(id, Closing::Filled)
        .ok_or(RunError::UnknownOrder { order: id.0 })?;
    let instrument = ledger.instrument();
    let (lots, liquidity) = (filled.order.lots, rules::f_lmt_04(&filled));
    let (fee, extended) = costs.fee(&instrument, priced.price, lots, liquidity, at.trade_date)?;
    let tick = instrument.tick_size();
    let fill = rules::f_tag_01(&filled, priced, at.ts, at.fidelity, tick, fee)?;
    Ok((filled, fill, extended))
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
    let (filled, fill, extended) = closed_and_tagged(book, ledger, costs, id, priced, at)?;
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
    let legs = exit_plan::place(book, &filled, priced.price, market, filled_at, tick)?;
    Ok(Execution {
        fill,
        cash,
        extended,
        cancelled,
        reduced: settled.reduced,
        legs,
        flat_after: ledger.position() == Position::Flat,
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
        self.transfer_on_record(record, index)?;
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
        let at = self.fill_point(record.ts, index);
        let (book, ledger, costs) = (&mut self.book, &mut self.ledger, &self.costs);
        let execution = execute(book, ledger, costs, id, &priced, at, record.price)?;
        self.record(execution)
    }

    /// Where a fill at `ts`, the `index`th event, happens: on the trade date being read.
    pub(super) const fn fill_point(&self, ts: Ts, index: usize) -> FillPoint {
        FillPoint {
            ts,
            index,
            fidelity: self.fidelity,
            trade_date: self.trade_date,
        }
    }

    /// Logs a fill on the run's front, as [`Self::record_on`] does.
    pub(super) fn record(&mut self, execution: Execution) -> Result<(), RunError> {
        let front = self.front.clone();
        self.record_on(execution, front)
    }

    /// Logs a fill, after a warning the first time the fee table's first schedule prices a fill
    /// before its date (F-FEE-01), with the orders of its group or its plan it cancelled, the stop
    /// of its plan it reduced, and its exit plan's legs, as the reference's `EventLog.filled`
    /// does, and keeps it among the run's fills, on `contract`, with its fee's cost line when the
    /// run names a fee table; its money counts in the trade open, and the fill that leaves the
    /// position flat closes it (§20).
    pub(super) fn record_on(
        &mut self,
        execution: Execution,
        contract: Contract,
    ) -> Result<(), RunError> {
        let Execution {
            fill,
            cash,
            extended,
            cancelled,
            reduced,
            legs,
            flat_after,
        } = execution;
        let moved = cash.checked_sub(fill.fee)?;
        self.trade_cash = self.trade_cash.checked_add(moved)?;
        if flat_after {
            let closed_at = fill.ts;
            let pnl = std::mem::replace(&mut self.trade_cash, Money(0));
            self.closed_trades.push(ClosedTrade { closed_at, pnl });
        }
        if extended && !self.warned {
            self.warned = true;
            self.log.push(LogEntry::fee_table_extended(&fill));
        }
        if self.costs.fees.is_some() {
            let reason = CostReason::Fee { order: fill.order };
            let (ts, amount) = (fill.ts, fill.fee);
            self.cost_lines.push(CostLine { ts, amount, reason });
        }
        let (ts, id) = (fill.ts, fill.order);
        self.log.push(LogEntry::filled(&fill));
        let cancelled = cancelled
            .into_iter()
            .map(|other| LogEntry::cancelled_by_group(ts, other, id));
        self.log.extend(cancelled);
        if let Some((stop, lots)) = reduced {
            self.log.push(LogEntry::reduced(ts, stop, lots, id));
        }
        let placed = legs.iter().map(|leg| LogEntry::bracket_placed(leg, id));
        self.log.extend(placed);
        self.fills.push(BookedFill {
            fill,
            cash,
            contract,
        });
        Ok(())
    }

    pub(super) fn tick(&self) -> Price {
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
