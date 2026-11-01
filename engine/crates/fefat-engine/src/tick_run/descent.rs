//! Hierarchical replay (`02` §4): the coarsest bar first, then finer bars, then the finest records,
//! descending only where a bar's range can reach a working order's level, an order can become
//! active, an exit plan could move (F-PLN-05), or, with a trade open, the bar can make a new
//! extreme of the trade's path, a block's records cross a whole minute, or the bar can make a new
//! best price of the trade (step 2.13). A block of the finest records inside a bar that nothing
//! can act on, and that ends before the next decision and the next roll or funding time
//! (F-CLK-02), is passed over whole, with what a full replay of it would leave: every working
//! limit resting (F-LMT-04), the market open (F-SES-02), the open trade's excursions at the
//! block's lowest and highest prices, and the position marked at the block's last record
//! (F-MRK-01). The bar's range bounds the prices of the records it holds, which every reader
//! checks where the levels nest, so skipping changes nothing that a full replay finds (skip equals
//! no-skip).

use fefat_core::instants::Ts;
use fefat_core::market_data::{BarColumns, BarRow, MarketDataReader};
use fefat_core::orders::{OrderKind, OrderState, Side};

use super::fills::is_limit;
use super::records::{Unit, bar_row};
use super::{RunError, Stepped, TickRun, Timer};
use crate::book::WorkingOrder;
use crate::exit_plan::LivePlan;

/// How a run reads each trade date's finest records.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Replay {
    /// Every record or bar in turn: the plain replay that skipping is held to.
    Full,
    /// The coarsest bar first, descending to finer bars and records only where an order could
    /// act, and passing over the rest whole.
    Skipping,
}

/// A bar level above a trade date's finest one, which nests its records, and the offsets that
/// take each of its bars down to them (`MarketDataReader::offsets`).
pub(super) struct BarLevel<'run> {
    pub(super) bars: BarColumns<'run>,
    pub(super) offsets: &'run [u32],
}

impl BarLevel<'_> {
    /// The bar holding the finest record `index`, and the place just past that bar's records.
    fn holding(&self, index: usize) -> Option<(BarRow, usize)> {
        let after = self
            .offsets
            .partition_point(|&offset| offset as usize <= index);
        let bar = bar_row(&self.bars, after.checked_sub(1)?)?;
        let end = *self.offsets.get(after)? as usize;
        Some((bar, end))
    }
}

/// The records a skip passes over, up to `end`, of which `last` is the last.
pub(super) struct Block {
    end: usize,
    last: Unit,
}

impl<R: MarketDataReader> TickRun<'_, R> {
    /// The block of the finest records from the next one that a skip may pass over: those of the
    /// coarsest bar holding it, or of a finer one, that come before the next decision (F-CLK-02),
    /// that no order can act on, and that leave the open trade's excursions and path as a full
    /// replay would; none when the run replays in full or no bar holding the record allows it.
    pub(super) fn skippable(&self) -> Option<Block> {
        let day = self.day.as_ref()?;
        let start = self.next_record;
        let instants = day.records.instants();
        let decision = self.decisions.get(self.next_decision).copied();
        let timer = self.next_timer().map(Timer::at);
        let of_bars = day.records.are_bars();
        day.levels.iter().find_map(|level| {
            let (bar, end) = level.holding(start)?;
            let end = decision.map_or(end, |decision| before(instants, start, end, decision, true));
            let end = timer.map_or(end, |at| before(instants, start, end, at, of_bars));
            let last = day.records.get(end.checked_sub(1)?)?;
            let first = *instants.get(start)?;
            let path_stays = || {
                let skippable = self.trades.can_skip(&bar, first, last.ts());
                skippable.unwrap_or(false)
            };
            let nothing_acts = end > start && self.untouched_by(&bar, last.ts()) && path_stays();
            nothing_acts.then_some(Block { end, last })
        })
    }

    /// Whether every record of a block inside `bar`, the last of them available at `last`, finds
    /// the market open and leaves every live order and every exit plan as it was (F-PLN-05).
    fn untouched_by(&self, bar: &BarRow, last: Ts) -> bool {
        let of_bars = self.day.as_ref().is_some_and(|day| day.records.are_bars());
        let open = self.hours.is_open_throughout(bar.ts_open, bar.ts_close);
        let tick = self.ledger.instrument().tick_size();
        let stop_of = |plan: &LivePlan| {
            let stop = self
                .book
                .live()
                .find(|order| Some(order.order.id) == plan.stop());
            stop.and_then(WorkingOrder::level)
        };
        let plans_stay = |plan: &LivePlan| {
            plan.untouched_by(stop_of(plan), bar.low, bar.high, tick)
                .unwrap_or(false)
        };
        open && self
            .book
            .live()
            .all(|order| beyond(order, bar, last, of_bars))
            && self.book.plans().all(plans_stay)
    }

    /// Passes over the block that `first` opens, as a full replay of it would leave the run.
    pub(super) fn skip(&mut self, first: Unit, block: Block) -> Result<Stepped, RunError> {
        self.check_order(first.ts())?;
        let traded = self.trades.is_open();
        let reached = self.day.as_ref().and_then(|day| {
            traded
                .then(|| day.records.range(self.next_record, block.end))
                .flatten()
        });
        if let Some((low, high)) = reached {
            self.trades.reached(low, high)?;
        }
        self.last_record = Some(block.last.ts());
        let units = block.end - self.next_record;
        self.next_record = block.end;
        self.in_break = false;
        let ids = self.book.ids_in(OrderState::Working, is_limit);
        for &id in &ids {
            self.book
                .rest(id)
                .ok_or(RunError::UnknownOrder { order: id.0 })?;
        }
        self.book.give_back_ids(ids);
        // F-MRK-01: the finest record's price, which its bar's close, a vendor's, need not be.
        self.mark_at(block.last.ts(), block.last.last_price())?;
        Ok(Stepped::Skipped { units })
    }
}

/// The end of the records from `start` before `end` that come before an event at `at`
/// (F-CLK-02): those available before it, and those available at it when `at_too`, as for a
/// decision, which comes after every record of its instant, or for a roll or a funding time, which
/// comes after the bars closing then but before the ticks received then.
fn before(instants: &[Ts], start: usize, end: usize, at: Ts, at_too: bool) -> usize {
    let held = instants.get(start..end);
    held.map_or(start, |held| {
        start + held.partition_point(|instant| *instant < at || (at_too && *instant == at))
    })
}

/// Whether no record inside `bar`, the last available at `last`, can act on `order`: a waiting
/// order active only after them (F-ACT-01; on bars F-ACT-02), or a working stop or limit beyond
/// every price of the bar (F-STP-01, F-LMT-01, F-LMT-02, F-BAR-01). A stop triggered on TBBO
/// fills on the next record (F-STP-02), and a working market order fills at once.
fn beyond(order: &WorkingOrder, bar: &BarRow, last: Ts, of_bars: bool) -> bool {
    let (activation, side) = (order.order.activation, order.order.side);
    match (order.state(), order.order.kind) {
        (OrderState::Waiting, _) if of_bars => activation >= last,
        (OrderState::Waiting, _) => activation > last,
        (OrderState::Working, OrderKind::StopMarket { stop }) => match side {
            Side::Buy => stop > bar.high,
            Side::Sell => stop < bar.low,
        },
        (OrderState::Working, OrderKind::Limit { limit }) => match side {
            Side::Buy => limit < bar.low,
            Side::Sell => limit > bar.high,
        },
        _ => false,
    }
}
