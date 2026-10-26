//! The event loop over the tick level of a [`MarketDataReader`] for one instrument (step 2.6), as
//! `fefat.reference.engine.ReferenceEngine` runs trades and TBBO records. Events come in the
//! order of F-CLK-02: at one instant the records received then, in the order the data holds them
//! (F-CLK-03), and then the decision. A record received while the market is closed is not
//! tradeable (F-SES-02), and the working orders stay (F-SES-01). On a tradeable record, the
//! orders that see their first record activate (F-ACT-01), and a market order or a stop through
//! the market fills on it (F-MKT-01, F-MKT-02, F-STP-05); stops triggered on the record before
//! fill at its quote (F-STP-02); stops trigger (F-STP-01), on trades filling at once (F-STP-03);
//! limits fill (F-LMT-01 to F-LMT-04); and the position is marked (F-MRK-01). Each fill cancels
//! its OCO group (F-OCO-01), places its bracket (F-OCO-02), and is booked in the [`Ledger`].

#[cfg(test)]
mod properties;
#[cfg(test)]
mod tests;

use fefat_core::fidelity::Fidelity;
use fefat_core::fills::{Fill, PricingRule};
use fefat_core::instants::{TradeDate, Ts};
use fefat_core::ledger::{Ledger, LedgerError};
use fefat_core::market_data::{MarketDataError, MarketDataReader, TbboColumns, TradeColumns};
use fefat_core::orders::{Order, OrderId, OrderKind, OrderRole, OrderState, Side, TimeInForce};
use fefat_core::units::{Money, Overflow, Price, Qty};
use thiserror::Error;

use crate::book::{Book, WorkingOrder};
use crate::event_log::LogEntry;
use crate::hours::TradingHours;
use crate::rules::{self, Priced};
use crate::settings::RunSettings;
use crate::strategy::{DecisionContext, DecisionError, Strategy};

/// A TBBO record's quote: the best bid and ask just before its trade, with their sizes.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Quote {
    /// The best bid.
    pub bid: Price,
    /// The best ask.
    pub ask: Price,
    /// The lots bid.
    pub bid_size: Qty,
    /// The lots offered.
    pub ask_size: Qty,
}

impl Quote {
    /// The quote an order of `side` takes, the ask for a buy, and its size.
    const fn of(self, side: Side) -> (Price, Qty) {
        match side {
            Side::Buy => (self.ask, self.ask_size),
            Side::Sell => (self.bid, self.bid_size),
        }
    }
}

/// One record of the tick level: a trade print, with its quote on TBBO.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct TickRecord {
    /// When it was received (F-CLK-01).
    pub ts: Ts,
    /// The trade's price.
    pub price: Price,
    /// The trade's size in lots.
    pub size: Qty,
    /// The quote, on TBBO.
    pub quote: Option<Quote>,
}

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

/// One trade date's records of the run's level, as the reader serves them.
enum DayRecords<'run> {
    Trades(TradeColumns<'run>),
    Tbbo(TbboColumns<'run>),
}

impl DayRecords<'_> {
    fn get(&self, index: usize) -> Option<TickRecord> {
        match self {
            Self::Trades(trades) => Some(TickRecord {
                ts: *trades.ts_recv.get(index)?,
                price: *trades.price.get(index)?,
                size: *trades.size.get(index)?,
                quote: None,
            }),
            Self::Tbbo(tbbo) => Some(TickRecord {
                ts: *tbbo.ts_recv.get(index)?,
                price: *tbbo.price.get(index)?,
                size: *tbbo.size.get(index)?,
                quote: Some(Quote {
                    bid: *tbbo.bid.get(index)?,
                    ask: *tbbo.ask.get(index)?,
                    bid_size: *tbbo.bid_size.get(index)?,
                    ask_size: *tbbo.ask_size.get(index)?,
                }),
            }),
        }
    }
}

/// One run of a strategy over the tick level of one contract's trade dates.
pub struct TickRun<'run, R: MarketDataReader> {
    reader: &'run R,
    fidelity: Fidelity,
    hours: &'run TradingHours,
    settings: RunSettings,
    strategy: &'run mut dyn Strategy,
    book: Book,
    ledger: Ledger,
    fills: Vec<BookedFill>,
    log: Vec<LogEntry>,
    in_break: bool,
    decisions: Vec<Ts>,
    next_decision: usize,
    next_day: usize,
    day: Option<DayRecords<'run>>,
    next_record: usize,
    last_record: Option<Ts>,
    timeline: usize,
}

impl<'run, R: MarketDataReader> TickRun<'run, R> {
    /// A run of `strategy` over `reader`'s records of `fidelity`, `tbbo` or `trades`, open during
    /// `hours`, under `settings`, from `ledger`: the run's capital, and the position held when
    /// the tape starts.
    pub fn new(
        reader: &'run R,
        fidelity: Fidelity,
        hours: &'run TradingHours,
        settings: RunSettings,
        ledger: Ledger,
        strategy: &'run mut dyn Strategy,
    ) -> Result<Self, RunError> {
        if let Fidelity::Bars(_) = fidelity {
            return Err(RunError::BarFidelity { fidelity });
        }
        let decisions = strategy.decision_instants();
        let pairs = decisions.iter().zip(decisions.iter().skip(1));
        if let Some((&previous, &next)) =
            pairs.into_iter().find(|(previous, next)| next <= previous)
        {
            return Err(RunError::DecisionsOutOfOrder { previous, next });
        }
        Ok(Self {
            reader,
            fidelity,
            hours,
            settings,
            strategy,
            book: Book::default(),
            ledger,
            fills: Vec::new(),
            log: Vec::new(),
            in_break: false,
            decisions,
            next_decision: 0,
            next_day: 0,
            day: None,
            next_record: 0,
            last_record: None,
            timeline: 0,
        })
    }

    /// Runs to the end of the records and the decisions.
    pub fn run(mut self) -> Result<RunOutputs, RunError> {
        while self.step()?.is_some() {}
        Ok(RunOutputs {
            orders: self.book.into_orders(),
            fills: self.fills,
            log: self.log,
            ledger: self.ledger,
        })
    }

    /// Handles the next event, a record or a decision, and says which; none once both have run
    /// out. At one instant the records come before the decision (F-CLK-02).
    pub fn step(&mut self) -> Result<Option<Stepped>, RunError> {
        let record = self.peek_record()?;
        let decision = self.decisions.get(self.next_decision).copied();
        let index = self.timeline;
        let stepped = match (record, decision) {
            (Some(record), Some(now)) if now < record.ts => self.decide(now, index)?,
            (Some(record), _) => self.receive(record, index)?,
            (None, Some(now)) => self.decide(now, index)?,
            (None, None) => return Ok(None),
        };
        self.timeline += 1;
        Ok(Some(stepped))
    }

    /// The ledger as the run stands.
    pub const fn ledger(&self) -> &Ledger {
        &self.ledger
    }

    /// The fills so far.
    pub fn fills(&self) -> &[BookedFill] {
        &self.fills
    }

    /// The order `id`, live or closed.
    pub fn order(&self, id: OrderId) -> Option<&WorkingOrder> {
        self.book.order(id)
    }

    fn peek_record(&mut self) -> Result<Option<TickRecord>, RunError> {
        loop {
            let next = self.day.as_ref().and_then(|day| day.get(self.next_record));
            if next.is_some() {
                return Ok(next);
            }
            let Some(&trade_date) = self.reader.trade_dates().get(self.next_day) else {
                return Ok(None);
            };
            self.day = Some(self.day_records(trade_date)?);
            self.next_day += 1;
            self.next_record = 0;
        }
    }

    fn day_records(&self, trade_date: TradeDate) -> Result<DayRecords<'run>, MarketDataError> {
        let reader: &'run R = self.reader;
        Ok(match self.fidelity {
            Fidelity::Tbbo => DayRecords::Tbbo(reader.tbbo(trade_date)?),
            Fidelity::Trades | Fidelity::Bars(_) => DayRecords::Trades(reader.trades(trade_date)?),
        })
    }

    fn decide(&mut self, now: Ts, index: usize) -> Result<Stepped, RunError> {
        self.next_decision += 1;
        let latency = self.settings.latency_nanoseconds();
        let position = self.ledger.position();
        let mut context =
            DecisionContext::new(&mut self.book, &mut self.log, position, now, index, latency);
        self.strategy.on_decision(now, &mut context)?;
        Ok(Stepped::Decision(now))
    }

    fn receive(&mut self, record: TickRecord, index: usize) -> Result<Stepped, RunError> {
        if let Some(previous) = self.last_record.filter(|previous| record.ts < *previous) {
            return Err(RunError::RecordsOutOfOrder {
                previous,
                next: record.ts,
            });
        }
        self.last_record = Some(record.ts);
        self.next_record += 1;
        self.on_record(&record, index)?;
        Ok(Stepped::Record(record))
    }

    /// A record: the orders that see their first record, the stops the record before triggered,
    /// the stops this one triggers, then the limits, so that a stop beats a limit of its group
    /// (F-OCO-01); then the mark (F-MRK-01). Each loop takes the ids in its state at its start
    /// and passes over an order an earlier fill closed.
    fn on_record(&mut self, record: &TickRecord, index: usize) -> Result<(), RunError> {
        if !self.tradeable(record.ts) {
            return Ok(());
        }
        for id in self.book.ids_in(OrderState::Waiting, |_| true) {
            let waiting = self.book.live_in(id, OrderState::Waiting);
            if waiting.is_some_and(|order| rules::f_act_01(order, record.ts, index)) {
                self.first_record(id, record, index)?;
            }
        }
        if let Some(quote) = record.quote {
            for id in self.book.ids_in(OrderState::Triggered, |_| true) {
                self.fill_triggered(id, record, quote, index)?;
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
        self.ledger.mark_at(record.price);
        Ok(())
    }

    /// F-SES-02: whether the market trades at `ts`; at the first record of a break, the working
    /// orders stay and the log says so (F-SES-01).
    fn tradeable(&mut self, ts: Ts) -> bool {
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
            .live_mut(id)
            .ok_or(RunError::UnknownOrder { order: id.0 })?;
        order.state = OrderState::Working;
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
        let priced = match record.quote {
            Some(quote) => {
                let (reference, shown_size) = quote.of(side);
                Priced {
                    price: rules::f_mkt_01(side, reference, ticks, tick)?,
                    rule: PricingRule::MarketAtQuote,
                    reference,
                    shown_size,
                }
            }
            None => Priced {
                price: rules::f_mkt_02(side, record.price, ticks, tick)?,
                rule: PricingRule::MarketAtTrade,
                reference: record.price,
                shown_size: record.size,
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
        quote: Quote,
        index: usize,
    ) -> Result<(), RunError> {
        let Some(order) = self.book.live_in(id, OrderState::Triggered) else {
            return Ok(());
        };
        let (side, Some(stop)) = (order.order.side, order.level()) else {
            return Ok(());
        };
        let (quoted, shown_size) = quote.of(side);
        let ticks = self.settings.slippage.stop;
        let priced = Priced {
            price: rules::f_stp_02(side, stop, quoted, ticks, self.tick())?,
            rule: PricingRule::StopAtNextQuote,
            reference: stop,
            shown_size,
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
            let order = self
                .book
                .live_mut(id)
                .ok_or(RunError::UnknownOrder { order: id.0 })?;
            order.state = OrderState::Triggered;
            return Ok(());
        }
        let ticks = self.settings.slippage.stop;
        let priced = Priced {
            price: rules::f_stp_03(side, stop, record.price, ticks, self.tick())?,
            rule: PricingRule::StopOnTrades,
            reference: stop,
            shown_size: record.size,
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
        let (filled, shown_size) = match record.quote {
            Some(quote) if !traded => {
                let (quoted, quoted_size) = quote.of(side);
                (rules::f_lmt_02(side, limit, quoted), quoted_size)
            }
            Some(_) | None => (traded, record.size),
        };
        if !filled {
            let order = self
                .book
                .live_mut(id)
                .ok_or(RunError::UnknownOrder { order: id.0 })?;
            order.rested = true;
            return Ok(());
        }
        let priced = Priced {
            price: rules::f_lmt_03(limit),
            rule: PricingRule::LimitAtItsPrice,
            reference: limit,
            shown_size,
        };
        self.fill(id, priced, record.ts, index)
    }

    /// Fills `id` as `priced` says at `ts`, the `index`th event: the ledger books it, its OCO
    /// group is cancelled (F-OCO-01), its bracket placed (F-OCO-02), and the log says so.
    fn fill(&mut self, id: OrderId, priced: Priced, ts: Ts, index: usize) -> Result<(), RunError> {
        let filled = self
            .book
            .close(id, OrderState::Filled)
            .ok_or(RunError::UnknownOrder { order: id.0 })?;
        let fill = rules::f_tag_01(&filled, &priced, ts, self.fidelity, self.tick())?;
        let cash = self.ledger.book(&fill)?;
        let group = self.book.group_of(&filled);
        for &other in &group {
            self.book.close(other, OrderState::Cancelled);
        }
        let legs = self.place_bracket(&filled, priced.price, ts, index)?;
        self.log.push(LogEntry::filled(&fill));
        let cancelled = group
            .into_iter()
            .map(|other| LogEntry::cancelled_by_group(ts, other, id));
        self.log.extend(cancelled);
        let placed = legs.iter().map(|leg| LogEntry::bracket_placed(leg, id));
        self.log.extend(placed);
        self.fills.push(BookedFill { fill, cash });
        Ok(())
    }

    /// The stop and the target of `entry`'s bracket, placed at its fill at `fill` as one OCO
    /// group, active at once and seeing the records after this one (F-OCO-02).
    fn place_bracket(
        &mut self,
        entry: &WorkingOrder,
        fill: Price,
        ts: Ts,
        index: usize,
    ) -> Result<Vec<Order>, RunError> {
        let Some(bracket) = entry.bracket else {
            return Ok(Vec::new());
        };
        let (stop, target) = bracket.prices(entry.order.side, fill, self.tick())?;
        let stop_id = bracket.stop.id.unwrap_or_else(|| self.book.new_id());
        let target_id = bracket.target.id.unwrap_or_else(|| self.book.new_id());
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
                placed_at: ts,
                activation: ts,
                oco: None,
            };
            self.book.place(WorkingOrder {
                order,
                state: OrderState::Waiting,
                rested: false,
                seen_after: index,
                bracket: None,
                bracket_of: Some(entry.order.id),
            });
            placed.push(order);
        }
        Ok(placed)
    }

    fn tick(&self) -> Price {
        self.ledger.instrument().tick_size()
    }
}
