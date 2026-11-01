//! How a stored bar works the run's orders, as `fefat.reference.engine` replays one (`_on_bar`
//! and `BarReplay`): the market's hours by the bar's open (F-SES-02); the orders that see their
//! first bar (F-ACT-02); the bar replayed as four pseudo-ticks, its open, its extremes in the
//! order F-BAR-02 to F-BAR-04 give, and its close (F-BAR-01), after a roll's legs, which fill at
//! the open of the first bar after the roll (F-ROL-02); when that fills anything, the bar
//! replayed again on a copy with its first extreme the other way round, and every fill of the bar
//! flagged ambiguous when the copy fills otherwise (F-BAR-05); and every fill at the bar's close
//! (F-BAR-06). Each point of the path marked, the open, each extreme reached, and the close, is
//! a price each exit plan follows once the fills at it are done (F-PLN-04), and the open trade's
//! excursions and path follow at the bar's close, a bar no order can act on marked along the same
//! path (step 2.13).

use fefat_core::fills::PricingRule;
use fefat_core::ledger::{Ledger, Position};
use fefat_core::market_data::{BarRow, MarketDataReader};
use fefat_core::orders::{OrderId, OrderKind, OrderState};
use fefat_core::units::Price;

use super::execution::{Execution, FillPoint, execute};
use super::fills::{is_limit, is_stop};
use super::{RunError, TickRun};
use crate::book::{Book, WorkingOrder};
use crate::event_log::LogEntry;
use crate::exit_plan::Move;
use crate::rules::{self, Extreme, Priced};
use crate::settings::{RunCosts, RunSettings};

/// What a bar's replay did, in the order it did it: a fill, a stop its plan moved, or a point of
/// the path marked (F-MRK-01), an extreme or not, which the open trade's excursions and path
/// follow.
#[derive(Debug, Clone, PartialEq, Eq)]
enum BarEvent {
    Filled(Execution),
    Moved(Move),
    Marked(Price, Option<Extreme>),
}

impl<R: MarketDataReader> TickRun<'_, R> {
    /// A stored bar, the `index`th event of the run.
    pub(super) fn on_bar(&mut self, bar: &BarRow, index: usize) -> Result<(), RunError> {
        if !rules::f_bar_07(bar) {
            return Err(RunError::BarWithoutTrades {
                ts_close: bar.ts_close,
            });
        }
        if !self.tradeable(bar.ts_open) {
            return Ok(());
        }
        let at = self.fill_point(rules::f_bar_06(bar), index);
        self.transfer_on_bar(bar, at)?;
        let triggered = self
            .book
            .live()
            .filter(|order| order.state() == OrderState::Triggered);
        if let Some(stop) = triggered.map(|order| order.order.id).min() {
            return Err(RunError::TriggeredWithoutQuotes {
                order: stop.0,
                at: rules::f_bar_06(bar),
                fidelity: self.fidelity,
            });
        }
        if !self.book.has_live() {
            return self.marked_along(bar);
        }
        let ids = self.book.ids_in(OrderState::Waiting, |_| true);
        for &id in &ids {
            let waiting = self.book.live_in(id, OrderState::Waiting);
            if waiting.is_some_and(|order| rules::f_act_02(order, bar)) {
                self.log.push(LogEntry::active_on_bar(at.ts, id));
            }
        }
        self.book.give_back_ids(ids);
        let (mut trial_book, mut trial_ledger) = (self.book.trial(), self.ledger.clone());
        let (settings, costs) = (&self.settings, &self.costs);
        let real = BarReplay::on(&mut self.book, &mut self.ledger, settings, costs, at);
        let mut events = real.run(bar, false)?;
        if fills_of(&events).next().is_some() {
            let trial = BarReplay::on(&mut trial_book, &mut trial_ledger, settings, costs, at);
            let swapped = trial.run(bar, true)?;
            if rules::f_bar_05(fills_of(&events), fills_of(&swapped)) {
                self.log.push(LogEntry::ambiguous(at.ts));
                for event in &mut events {
                    if let BarEvent::Filled(execution) = event {
                        execution.fill.flags.ambiguous = true;
                    }
                }
            }
        }
        for event in events {
            match event {
                BarEvent::Filled(execution) => self.record(execution)?,
                BarEvent::Moved(moved) => self.log_moves(at.ts, &[moved]),
                BarEvent::Marked(price, extreme) => self.trade_marked(bar, price, extreme)?,
            }
        }
        Ok(())
    }

    /// A bar no order can act on: the position marked at its open, its extremes, the adverse one
    /// first for a position held (F-BAR-02), and its close (F-BAR-01, F-MRK-01), as a replay of
    /// its path with orders marks them.
    fn marked_along(&mut self, bar: &BarRow) -> Result<(), RunError> {
        let first = rules::f_bar_02(self.ledger.position());
        let path = [
            (bar.open, None),
            (first.of(bar), Some(first)),
            (first.other().of(bar), Some(first.other())),
            (bar.close, None),
        ];
        for (price, extreme) in path {
            self.trade_marked(bar, price, extreme)?;
        }
        self.ledger.mark_at(bar.close);
        Ok(())
    }

    /// A point of `bar`'s path at `price`, at its close (F-BAR-06), which the open trade follows.
    fn trade_marked(
        &mut self,
        bar: &BarRow,
        price: Price,
        extreme: Option<Extreme>,
    ) -> Result<(), RunError> {
        let on_bar = extreme.map(|reached| (reached, *bar));
        let mark = self.mark(rules::f_bar_06(bar), price, on_bar);
        Ok(self.trades.marked(&mark)?)
    }
}

/// Each fill's order and price, as F-BAR-05 compares them.
fn fills_of(events: &[BarEvent]) -> impl Iterator<Item = (OrderId, Price)> + '_ {
    events.iter().filter_map(|event| match event {
        BarEvent::Filled(execution) => Some((execution.fill.order, execution.fill.price)),
        BarEvent::Moved(_) | BarEvent::Marked(..) => None,
    })
}

/// One bar replayed on one book and ledger, the run's or a copy of them.
struct BarReplay<'replay> {
    book: &'replay mut Book,
    ledger: &'replay mut Ledger,
    settings: &'replay RunSettings,
    costs: &'replay RunCosts,
    at: FillPoint,
    events: Vec<BarEvent>,
}

impl<'replay> BarReplay<'replay> {
    const fn on(
        book: &'replay mut Book,
        ledger: &'replay mut Ledger,
        settings: &'replay RunSettings,
        costs: &'replay RunCosts,
        at: FillPoint,
    ) -> Self {
        Self {
            book,
            ledger,
            settings,
            costs,
            at,
            events: Vec::new(),
        }
    }

    /// The bar's open, its extremes, the first chosen by F-BAR-02 or F-BAR-03 and the other way
    /// round when `swapped`, each entry inside the bar reordering those not yet reached (F-BAR-04),
    /// and its close; the position marked at each extreme reached and at the close (F-MRK-01).
    fn run(mut self, bar: &BarRow, swapped: bool) -> Result<Vec<BarEvent>, RunError> {
        self.open(bar)?;
        let first = match self.ledger.position() {
            Position::Flat => rules::f_bar_03(self.working()),
            held => rules::f_bar_02(held),
        };
        let mut remaining = if swapped {
            vec![first.other(), first]
        } else {
            vec![first, first.other()]
        };
        let mut point = bar.open;
        while let Some(&next) = remaining.first() {
            let extreme = next.of(bar);
            let (reached, opened) = self.leg(point, extreme)?;
            point = reached;
            if point == extreme {
                self.marked(extreme, Some(next))?;
                remaining.remove(0);
            }
            if opened {
                rules::f_bar_04(&mut remaining, self.ledger.position());
            }
        }
        self.leg(point, bar.close)?;
        self.marked(bar.close, None)?;
        Ok(self.events)
    }

    /// A point of the path marked (F-MRK-01), `extreme` when it is one, and each exit plan's turn
    /// at it (F-PLN-04).
    fn marked(&mut self, price: Price, extreme: Option<Extreme>) -> Result<(), RunError> {
        self.ledger.mark_at(price);
        self.events.push(BarEvent::Marked(price, extreme));
        let moves = self.book.marked(price, self.tick())?;
        self.events.extend(moves.into_iter().map(BarEvent::Moved));
        Ok(())
    }

    fn working(&self) -> impl Iterator<Item = &WorkingOrder> {
        let live = self.book.live();
        live.filter(|order| order.state() == OrderState::Working)
    }

    /// The open's pseudo-tick: market orders and stops through the market that see their first
    /// bar, then the stops and the limits the open is past, by id in each class (F-OCO-01); the
    /// limits still working rest (F-LMT-04), and the open marks the position.
    fn open(&mut self, bar: &BarRow) -> Result<(), RunError> {
        let (point, market) = (bar.open, self.ledger.mark());
        let ids = self.book.ids_in(OrderState::Waiting, |_| true);
        for &id in &ids {
            let waiting = self.book.live_in(id, OrderState::Waiting);
            if waiting.is_some_and(|order| rules::f_act_02(order, bar)) {
                self.first_bar(id, point, market)?;
            }
        }
        self.book.give_back_ids(ids);
        let ids = self.book.ids_in(OrderState::Working, is_stop);
        for &id in &ids {
            let Some(order) = self.book.live_in(id, OrderState::Working) else {
                continue;
            };
            let (side, Some(stop)) = (order.order.side, order.level()) else {
                continue;
            };
            if rules::f_stp_01(side, stop, point) {
                let ticks = self.settings.slippage.stop;
                let price = rules::f_stp_04(side, stop, point, ticks, self.tick())?;
                self.fill(point, id, on_bars(price, PricingRule::StopOnBars, stop))?;
            }
        }
        self.book.give_back_ids(ids);
        let ids = self.book.ids_in(OrderState::Working, is_limit);
        for &id in &ids {
            let Some(order) = self.book.live_in(id, OrderState::Working) else {
                continue;
            };
            let (side, Some(limit)) = (order.order.side, order.level()) else {
                continue;
            };
            if rules::limit_past(self.settings, side, limit, point) {
                self.fill(point, id, at_its_price(limit))?;
            }
        }
        self.book.give_back_ids(ids);
        self.book.rest_working_limits();
        self.marked(point, None)
    }

    /// An order's first bar (F-ACT-02): a market order fills at its open (F-MKT-03), and so does
    /// a stop at or through `market`, the mark before the bar, with the larger class's ticks
    /// (F-STP-05); any other order works from the open.
    fn first_bar(
        &mut self,
        id: OrderId,
        point: Price,
        market: Option<Price>,
    ) -> Result<(), RunError> {
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
            return Ok(());
        }
        let ticks = rules::f_slp_01(self.settings, &kind, through);
        let price = rules::f_mkt_03(side, point, ticks, self.tick())?;
        let rule = if through {
            PricingRule::StopThroughMarket
        } else {
            PricingRule::MarketAtBarOpen
        };
        self.fill(point, id, on_bars(price, rule, point))
    }

    /// The path from `from` to `extreme`: the nearest level first, all its orders together, stops
    /// before limits, each by id (F-OCO-01). It ends at the extreme, or where a fill opens a
    /// position, from flat or by reversing one (F-BAR-04): the point reached, and whether one
    /// opened.
    fn leg(&mut self, from: Price, extreme: Price) -> Result<(Price, bool), RunError> {
        let mut point = from;
        loop {
            let reached: Vec<(OrderId, Price, bool)> = self
                .working()
                .filter_map(|order| {
                    let level = rules::f_bar_01(self.settings, order, point, extreme)?;
                    Some((order.order.id, level, is_stop(&order.order.kind)))
                })
                .collect();
            let levels = reached.iter().map(|&(_, level, _)| level);
            let Some(nearest) = levels.min_by_key(|level| level.0.abs_diff(point.0)) else {
                return Ok((extreme, false));
            };
            let mut batch: Vec<(bool, OrderId)> = reached
                .iter()
                .filter(|&&(_, level, _)| level == nearest)
                .map(|&(id, _, stop)| (!stop, id))
                .collect();
            batch.sort_unstable();
            let before = self.ledger.position().signed_lots().0;
            for (limit, id) in batch {
                self.fill_at_level(nearest, id, limit)?;
            }
            point = nearest;
            let after = self.ledger.position().signed_lots().0;
            if after != 0 && before.signum() != after.signum() {
                return Ok((point, true));
            }
        }
    }

    /// A working stop the path reaches at `level`, filled there plus the ticks (F-STP-04), or a
    /// limit it passes, filled at its own price (F-LMT-03); none once an earlier fill of the
    /// level closed it.
    fn fill_at_level(&mut self, level: Price, id: OrderId, limit: bool) -> Result<(), RunError> {
        let Some(order) = self.book.live_in(id, OrderState::Working) else {
            return Ok(());
        };
        let (side, Some(own)) = (order.order.side, order.level()) else {
            return Ok(());
        };
        if limit {
            return self.fill(level, id, at_its_price(own));
        }
        let ticks = self.settings.slippage.stop;
        let price = rules::f_stp_04(side, level, level, ticks, self.tick())?;
        self.fill(level, id, on_bars(price, PricingRule::StopOnBars, level))
    }

    /// A fill at `point` of the path, whose exit plan's legs are judged there at once (F-OCO-02,
    /// F-STP-05): a stop or a target the point is through fills, and the rest work from it.
    fn fill(&mut self, point: Price, id: OrderId, priced: Priced) -> Result<(), RunError> {
        let execution = execute(
            self.book,
            self.ledger,
            self.costs,
            id,
            &priced,
            self.at,
            point,
        )?;
        let legs: Vec<OrderId> = execution.legs.iter().map(|leg| leg.id).collect();
        self.events.push(BarEvent::Filled(execution));
        for leg in legs {
            self.judge_leg(point, leg)?;
        }
        Ok(())
    }

    /// An exit plan's leg placed at `point`: a stop through it fills there as a market order
    /// would, with the larger class's ticks (F-STP-05); a target past it fills at its price
    /// (F-LMT-03); a target short of it rests (F-LMT-04); a stop works from it. None once an
    /// earlier fill closed it.
    fn judge_leg(&mut self, point: Price, id: OrderId) -> Result<(), RunError> {
        let Some(leg) = self.book.activate(id) else {
            return Ok(());
        };
        let (side, kind) = (leg.order.side, leg.order.kind);
        match kind {
            OrderKind::StopMarket { stop } if rules::f_stp_05(side, stop, Some(point)) => {
                let ticks = rules::f_slp_01(self.settings, &kind, true);
                let price = rules::f_mkt_03(side, point, ticks, self.tick())?;
                let rule = PricingRule::StopThroughMarket;
                self.fill(point, id, on_bars(price, rule, point))
            }
            OrderKind::Limit { limit } if rules::limit_past(self.settings, side, limit, point) => {
                self.fill(point, id, at_its_price(limit))
            }
            OrderKind::Limit { .. } => self
                .book
                .rest(id)
                .ok_or(RunError::UnknownOrder { order: id.0 }),
            OrderKind::StopMarket { .. } | OrderKind::Market => Ok(()),
        }
    }

    fn tick(&self) -> Price {
        self.ledger.instrument().tick_size()
    }
}

/// A fill on bars, which show no size (F-QTY-01).
const fn on_bars(price: Price, rule: PricingRule, reference: Price) -> Priced {
    Priced {
        price,
        rule,
        reference,
        shown_size: None,
    }
}

/// A limit filled at its own price, never better (F-LMT-03).
const fn at_its_price(limit: Price) -> Priced {
    on_bars(rules::f_lmt_03(limit), PricingRule::LimitAtItsPrice, limit)
}
