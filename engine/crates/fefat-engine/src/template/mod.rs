//! The execution template, as `fefat.reference.template` runs it (steps 2.3 and 2.8, D-53): its
//! entries (`entries`, §25), each carrying its exit plan (`exits`, §22 to §24); signal exits and
//! opposite signals; the time rules (§26), from what each signal row gives for them; and a fixed
//! size times `size_mult` in whole lots. The limits and the other sizes arrive later in step 2.8
//! and are refused until then.

mod entries;
mod exits;
mod rows;
#[cfg(test)]
mod tests;

pub use rows::{RowFeatures, SignalRow};

use fefat_core::instants::Ts;
use fefat_core::instrument::InstrumentParameters;
use fefat_core::ledger::Position;
use fefat_core::orders::{ExitReason, Side};
use fefat_core::strategy_spec::{
    EntryOrder, Execution, Limits, OppositeSignal, OutOfBounds, Sizing, StrategySpec,
};
use fefat_core::units::{PRICE_UNITS, Price, Qty};
use thiserror::Error;

use crate::exact_decimal::ExactDecimal;
use crate::exit_plan::PlanRow;
use crate::strategy::{DecisionContext, DecisionError, Entry, Strategy};

const SUBSET: &str = "any entry, exit plan, and time rule, and a fixed size";

/// A specification or a signal frame the template refuses.
#[derive(Debug, Clone, PartialEq, Eq, Error)]
pub enum TemplateError {
    /// A value outside the bounds of the specification's schema.
    #[error(transparent)]
    OutOfBounds(#[from] OutOfBounds),
    /// A rule beyond what the template runs so far.
    #[error(
        "Expected a StrategySpec within the tick engine's basic subset ({SUBSET}), got {refused}: \
         the rest arrives in step 2.8"
    )]
    BeyondTheSubset {
        /// What the specification holds beyond it.
        refused: String,
    },
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
/// this order (F-ENT-01): the exit plans' turn at the decision (F-PLN-04); nothing more while a
/// market order is on its way out of the position or into it, its own exit or a stop triggered on
/// TBBO (F-STP-02); from the trade date's flat-by time, and from the last signal close before a
/// stop of trading with no overnight or before a weekend with no weekend, the position is closed,
/// the working orders cancelled, and no entry placed (F-TIM-01, F-TIM-03); a position held
/// max_bars decisions or max_minutes is closed (F-TIM-02); `long_exit` while long or `short_exit`
/// while short closes the position, with signal exits on; with a position or working orders,
/// nothing more, an opposite signal being ignored; on a bar whose `wake` is false, or outside the
/// entry windows (F-TIM-04), no entry; and otherwise an entry signal enters at the market, its
/// exit plan placed when it fills (F-PLN-01).
#[derive(Debug, Clone, PartialEq)]
pub struct TemplateStrategy {
    rows: Vec<SignalRow>,
    execution: Execution,
    lots: Qty,
    tick: Price,
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
        refuse_the_rest(execution)?;
        let market = matches!(execution.entry, EntryOrder::Market {});
        rows::require_rows_in_order(&rows, market)?;
        rows::require_flat_by_on_every_row(execution, &rows)?;
        rows::require_time_columns(execution, &rows)?;
        Ok(Self {
            rows,
            execution: execution.clone(),
            lots: fixed_lots(&execution.sizing, instrument)?,
            tick: instrument.tick_size(),
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

    /// The lots of an entry on `row`: the fixed size times its `size_mult`, in whole lots.
    fn lots_at(&self, row: &SignalRow) -> Result<Qty, DecisionError> {
        let Some(multiple) = row.size_mult else {
            return Ok(self.lots);
        };
        let lots = ExactDecimal::of(multiple).and_then(|exact| exact.whole_times(self.lots.0, 1));
        match lots.and_then(|lots| i64::try_from(lots).ok()) {
            Some(lots) if lots >= 1 => Ok(Qty(lots)),
            _ => Err(DecisionError::Signal {
                expected: "a size_mult that makes whole lots, at least one".to_owned(),
                actual: format!("{multiple} times {} lots", self.lots),
                at: row.ts_close,
            }),
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
        let minutes = time
            .max_minutes
            .map(|minutes| i64::from(minutes) * 60_000_000_000);
        let after = minutes.and_then(|span| opened_at.checked_add_nanoseconds(span).ok());
        after
            .is_some_and(|after| now >= after)
            .then_some(ExitReason::MaxMinutes)
    }

    /// Enters on `sides`, each order with its exit plan (F-ENT-02, F-PLN-01), flat with nothing
    /// working or `reversing`; an offset entry with no mark yet places nothing, and the log says
    /// why.
    fn enter(
        &self,
        row: &SignalRow,
        context: &mut DecisionContext<'_>,
        sides: Vec<Side>,
        reversing: bool,
    ) -> Result<(), DecisionError> {
        let entry = &self.execution.entry;
        let mut placed = Vec::with_capacity(sides.len());
        for side in sides {
            let Some(kind) = entries::f_ent_02(entry, side, row, context.mark(), self.tick)? else {
                context.skipped("no mark to count the entry's offset from", "F-ENT-02");
                return Ok(());
            };
            let plan = exits::exit_plan_of(&self.execution, row, side, self.tick)?;
            placed.push(Entry {
                side,
                kind,
                lots: self.lots_at(row)?,
                time_in_force: entries::time_in_force(entry),
                plan: Some(plan),
            });
        }
        if !placed.is_empty() {
            context.enter(placed, reversing)?;
        }
        Ok(())
    }

    fn row_at(&self, now: Ts) -> Result<SignalRow, DecisionError> {
        let found = self.rows.binary_search_by_key(&now, |row| row.ts_close);
        let row = found.ok().and_then(|index| self.rows.get(index)).copied();
        row.ok_or_else(|| DecisionError::Signal {
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
        let row = self.row_at(now)?;
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
        let allowed = row.wake && row.in_window != Some(false);
        let on_opposite = self.execution.on_opposite_signal;
        if let Some(side) = entries::f_ent_04(on_opposite, &row, context.position()) {
            context.flatten(ExitReason::OppositeSignal)?;
            if on_opposite == OppositeSignal::Reverse && allowed {
                self.enter(&row, context, vec![side], true)?;
            }
            return Ok(());
        }
        if self.signals_exit(&row, context.position()) {
            return context.flatten(ExitReason::SignalExit);
        }
        if context.position() == Position::Flat && !context.has_working_orders() && allowed {
            self.enter(&row, context, entries::f_ent_01(&row), false)?;
        }
        Ok(())
    }
}

/// Refuses what the template does not run yet (`template.basic_subset_refusals`): entry limits.
fn refuse_the_rest(execution: &Execution) -> Result<(), TemplateError> {
    if execution.limits != Limits::default() {
        return Err(beyond("entry limits"));
    }
    Ok(())
}

/// The lots of the fixed size: its units in whole lot steps of the instrument (`lots_of`).
fn fixed_lots(sizing: &Sizing, instrument: &InstrumentParameters) -> Result<Qty, TemplateError> {
    let Sizing::Fixed { units } = *sizing else {
        return Err(beyond("a size other than fixed"));
    };
    let lot_step = instrument.lot_step().0;
    let lots = ExactDecimal::of(units)
        .and_then(|exact| exact.whole_times(PRICE_UNITS, lot_step))
        .and_then(|lots| i64::try_from(lots).ok());
    match lots {
        Some(lots) if lots >= 1 => Ok(Qty(lots)),
        _ => Err(TemplateError::Refused {
            expected: format!("a size in whole lots of {}", Price(lot_step)),
            actual: units.to_string(),
        }),
    }
}

fn beyond(what: &str) -> TemplateError {
    TemplateError::BeyondTheSubset {
        refused: what.to_owned(),
    }
}
