//! The execution template, as `fefat.reference.template` runs it (steps 2.3 and 2.8, D-53): its
//! entries (`entries`, §25), each carrying its exit plan (`exits`, §22 to §24) and its size
//! (`sizing`, §28); signal exits and opposite signals; the time rules (§26), from what each signal
//! row gives for them; and the entry limits (`limits`, §27).

mod entries;
mod exits;
mod limits;
mod rows;
mod sizing;
#[cfg(test)]
mod tests;

pub use rows::{RowFeatures, SignalRow};

use fefat_core::instants::{NANOSECONDS_PER_MINUTE, Ts};
use fefat_core::instrument::InstrumentParameters;
use fefat_core::ledger::Position;
use fefat_core::orders::{ExitReason, OrderKind, Side};
use fefat_core::strategy_spec::{EntryOrder, Execution, OppositeSignal, OutOfBounds, StrategySpec};
use fefat_core::units::{Money, Qty};
use thiserror::Error;

use crate::exit_plan::{ExitPlan, PlanRow};
use crate::strategy::{DecisionContext, DecisionError, Entry, Strategy};
use limits::EntryLimits;
use sizing::{ComputedSize, EntryPricing, NoEntry, Size};

/// A specification or a signal frame the template refuses.
#[derive(Debug, Clone, PartialEq, Eq, Error)]
pub enum TemplateError {
    /// A value outside the bounds of the specification's schema.
    #[error(transparent)]
    OutOfBounds(#[from] OutOfBounds),
    /// A size, a multiple, or a signal row the template cannot act on.
    #[error("Expected {expected}, got {actual}")]
    Refused {
        /// What the template needs.
        expected: String,
        /// What it was given.
        actual: String,
    },
}

/// A specification as a strategy over its signal rows, each a decision. At each signal close, in
/// this order (F-ENT-01): the trades closed since the last decision are counted (F-LIM-02), the
/// exit plans take their turn (F-PLN-04), and the entries whose time to live has ended are
/// cancelled (F-ENT-03); nothing more while a market order is on its way out of the position or
/// into it, its own exit or a stop triggered on TBBO (F-STP-02); from the trade date's flat-by
/// time, and from the last signal close before a stop of trading with no overnight or before a
/// weekend with no weekend, the position is closed, the working orders cancelled, and no entry
/// placed (F-TIM-01, F-TIM-03); a position held max_bars decisions or max_minutes is closed
/// (F-TIM-02); an entry signal against the position closes or reverses it as
/// `on_opposite_signal` says, and with signal exits on `long_exit` closes a long and `short_exit`
/// a short (F-ENT-04); and flat with nothing working, on a row whose `wake` is true, inside the
/// entry windows (F-TIM-04), and that the limits allow (§27), an entry signal enters (F-ENT-01,
/// F-ENT-02), its size worked out (§28) and its exit plan placed when it fills (F-PLN-01).
#[derive(Debug, Clone, PartialEq)]
pub struct TemplateStrategy {
    rows: Vec<SignalRow>,
    execution: Execution,
    size: Size,
    instrument: InstrumentParameters,
    limits: EntryLimits,
}

impl TemplateStrategy {
    /// The template of `spec` over `rows`, in ascending order of their closes, trading
    /// `instrument`.
    pub fn new(
        spec: &StrategySpec,
        rows: Vec<SignalRow>,
        instrument: &InstrumentParameters,
    ) -> Result<Self, TemplateError> {
        spec.validate()?;
        let execution = &spec.execution;
        let market = matches!(execution.entry, EntryOrder::Market {});
        rows::require_rows_in_order(&rows, market)?;
        rows::require_flat_by_on_every_row(execution, &rows)?;
        rows::require_time_columns(execution, &rows)?;
        rows::require_trade_dates(execution, &rows)?;
        Ok(Self {
            rows,
            execution: execution.clone(),
            size: Size::of(&execution.sizing, instrument)?,
            instrument: *instrument,
            limits: EntryLimits::new(&execution.limits)?,
        })
    }

    fn signals_exit(&self, row: &SignalRow, position: Position) -> bool {
        self.execution.signal_exit
            && match position {
                Position::Flat => false,
                Position::Long(_) => row.long_exit,
                Position::Short(_) => row.short_exit,
            }
    }

    /// The time exit that closes the position and places no entry on `row`, the first that
    /// applies: the flat-by time, then a stop of trading, then a weekend (F-TIM-01, F-TIM-03).
    fn stop_exit(&self, row: &SignalRow) -> Option<ExitReason> {
        let time = self.execution.time.as_ref()?;
        if row.flat_by.is_some_and(|flat_by| row.ts_close >= flat_by) {
            return Some(ExitReason::FlatBy);
        }
        if time.no_overnight && row.session_end == Some(true) {
            return Some(ExitReason::NoOvernight);
        }
        (time.no_weekend && row.week_end == Some(true)).then_some(ExitReason::NoWeekend)
    }

    /// F-TIM-02: the time exit of a position that opened at `opened_at`, at the decision `now`:
    /// `max_bars` from the max_bars-th decision at or after its entry's fill, `max_minutes` from
    /// the first at or after the fill plus the minutes; none for a position held when the tape
    /// starts, which no fill opened.
    fn f_tim_02(&self, now: Ts, opened_at: Option<Ts>) -> Option<ExitReason> {
        let (time, opened_at) = (self.execution.time.as_ref()?, opened_at?);
        let since = self.rows.partition_point(|row| row.ts_close < opened_at);
        let through = self.rows.partition_point(|row| row.ts_close <= now);
        let decisions = through.saturating_sub(since);
        if time.max_bars.is_some_and(|bars| decisions >= bars as usize) {
            return Some(ExitReason::MaxBars);
        }
        // A span past the last instant is never reached, as the reference's integers give
        // (S-template-082).
        let minutes = time
            .max_minutes
            .and_then(|minutes| i64::from(minutes).checked_mul(NANOSECONDS_PER_MINUTE));
        let after = minutes.and_then(|span| opened_at.checked_add_nanoseconds(span).ok());
        after
            .is_some_and(|after| now >= after)
            .then_some(ExitReason::MaxMinutes)
    }

    /// The row's signals, as they count (F-LIM-04): an opposite signal or a signal exit
    /// (F-ENT-04), then an entry where the row and the limits allow one.
    fn signals(
        &mut self,
        row: &SignalRow,
        decision: usize,
        context: &mut DecisionContext<'_>,
    ) -> Result<(), DecisionError> {
        let allowed = row.wake && row.in_window != Some(false) && self.limits.allow(row, decision);
        let on_opposite = self.execution.on_opposite_signal;
        if let Some(side) = entries::f_ent_04(on_opposite, row, context.position()) {
            context.flatten(ExitReason::OppositeSignal)?;
            if on_opposite == OppositeSignal::Reverse && allowed {
                self.enter(row, context, vec![side], true)?;
            }
            return Ok(());
        }
        if self.signals_exit(row, context.position()) {
            return context.flatten(ExitReason::SignalExit);
        }
        if context.position() == Position::Flat && !context.has_working_orders() && allowed {
            self.enter(row, context, entries::f_ent_01(row), false)?;
        }
        Ok(())
    }

    /// Enters on `sides`, each order with its exit plan and its size (F-ENT-02, F-PLN-01, §28),
    /// flat with nothing working or `reversing`; an offset entry with no mark yet places nothing,
    /// nor does an entry whose size has no lots, and the log says why.
    fn enter(
        &mut self,
        row: &SignalRow,
        context: &mut DecisionContext<'_>,
        sides: Vec<Side>,
        reversing: bool,
    ) -> Result<(), DecisionError> {
        let (entry, tick) = (&self.execution.entry, self.instrument.tick_size());
        let mut placed = Vec::with_capacity(sides.len());
        for side in sides {
            let Some(kind) = entries::f_ent_02(entry, side, row, context.mark(), tick)? else {
                context.skipped("no mark to count the entry's offset from", "F-ENT-02");
                return Ok(());
            };
            let plan = exits::exit_plan_of(&self.execution, row, side, tick)?;
            let lots = match self.lots(row, context, side, kind, &plan)? {
                Ok(lots) => lots,
                Err(NoEntry { why, rule }) => {
                    context.skipped(why, rule);
                    continue;
                }
            };
            placed.push(Entry {
                side,
                kind,
                lots,
                time_in_force: entries::time_in_force(entry),
                plan: Some(plan),
            });
        }
        if !placed.is_empty() {
            context.enter(placed, reversing)?;
            self.limits.entered();
        }
        Ok(())
    }

    /// An entry's size (§28): a fixed size times `size_mult`, or a computed one priced at the
    /// order's own price, or for a market order at the mark.
    fn lots(
        &self,
        row: &SignalRow,
        context: &DecisionContext<'_>,
        side: Side,
        kind: OrderKind,
        plan: &ExitPlan,
    ) -> Result<Result<Qty, NoEntry>, DecisionError> {
        let computed = match self.size {
            Size::Fixed(lots) => return Ok(Ok(sizing::f_siz_01(lots, row)?)),
            Size::Computed(computed) => computed,
        };
        let price = match kind {
            OrderKind::Market => context.mark(),
            OrderKind::StopMarket { stop } => Some(stop),
            OrderKind::Limit { limit } => Some(limit),
        };
        let equity = match computed {
            ComputedSize::RiskPercent(_) => context.equity()?,
            ComputedSize::Notional(_) | ComputedSize::RiskAmount(_) => Money(0),
        };
        let pricing = EntryPricing {
            side,
            price,
            plan,
            equity,
        };
        sizing::computed_lots(computed, &pricing, row, &self.instrument)
    }

    fn row_at(&self, now: Ts) -> Result<(usize, SignalRow), DecisionError> {
        let found = self.rows.binary_search_by_key(&now, |row| row.ts_close);
        let found = found
            .ok()
            .and_then(|index| Some((index, *self.rows.get(index)?)));
        found.ok_or_else(|| DecisionError::Signal {
            expected: "a signal row at the decision".to_owned(),
            actual: "none".to_owned(),
            at: now,
        })
    }
}

impl Strategy for TemplateStrategy {
    fn decision_instants(&self) -> Vec<Ts> {
        self.rows.iter().map(|row| row.ts_close).collect()
    }

    fn on_decision(
        &mut self,
        now: Ts,
        context: &mut DecisionContext<'_>,
    ) -> Result<(), DecisionError> {
        let (decision, row) = self.row_at(now)?;
        let closed = context.closed_trades(self.limits.counted());
        self.limits.count(closed, row.trade_date, decision)?;
        context.update_exit_plans(&PlanRow {
            at: row.ts_close,
            trail_feature: row.features.trailing,
            trail_ref: row.trail_ref,
        })?;
        if let Some(at) = entries::f_ent_03(&self.execution.entry, &self.rows, now) {
            context.cancel_entries_placed_by(at);
        }
        if context.is_exiting() || context.is_entering() {
            return Ok(());
        }
        if let Some(reason) = self.stop_exit(&row) {
            if context.position() != Position::Flat || context.has_working_orders() {
                context.flatten(reason)?;
            }
            return Ok(());
        }
        if context.position() != Position::Flat
            && let Some(reason) = self.f_tim_02(now, context.opened_at())
        {
            return context.flatten(reason);
        }
        let before = decision
            .checked_sub(1)
            .and_then(|index| self.rows.get(index));
        let fresh = self.execution.limits.fresh_signal;
        let row = limits::f_lim_04(fresh, row, before);
        self.signals(&row, decision, context)
    }
}
