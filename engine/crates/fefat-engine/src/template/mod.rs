//! The execution template's basic subset on ticks, as `fefat.reference.template` runs it (step 2.3,
//! D-53): a market entry that ignores opposite signals; a stop in ticks or at the signal frame's
//! `stop_price` and one target in ticks, as an R multiple of a stop in ticks, or at
//! `target_price`; signal exits; and a fixed size times `size_mult` in whole lots. The rest of the
//! template, its time rules included, arrives in step 2.8 and is refused until then.

use fefat_core::instants::Ts;
use fefat_core::instrument::InstrumentParameters;
use fefat_core::ledger::Position;
use fefat_core::orders::Side;
use fefat_core::strategy_spec::{
    EntryOrder, Execution, Limits, OppositeSignal, OutOfBounds, Sizing, StopRule, StrategySpec,
    TargetPrice, TimeRules,
};
use fefat_core::units::{PRICE_UNITS, Price, Qty};
use thiserror::Error;

use crate::book::{Bracket, BracketLeg, LegPrice};
use crate::exact_decimal::ExactDecimal;
use crate::strategy::{DecisionContext, DecisionError, Strategy};

#[cfg(test)]
mod tests;

const SUBSET: &str = "a market entry, a stop and one target, signal exits, and a fixed size";

/// One row of a signal frame, at one signal close (D-53): its four signals, a null read as false;
/// the raw prices a column stop and a column target take; the size's multiple, where the frame
/// has one; and whether the bar may enter, a null read as true.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct SignalRow {
    /// The signal bar's close, the decision's instant.
    pub ts_close: Ts,
    /// Enter long.
    pub long_entry: bool,
    /// Enter short.
    pub short_entry: bool,
    /// Close a long.
    pub long_exit: bool,
    /// Close a short.
    pub short_exit: bool,
    /// The stop of a column stop, a raw price of the row's contract.
    pub stop_price: Option<Price>,
    /// The target of a column target, a raw price of the row's contract.
    pub target_price: Option<Price>,
    /// The multiple of the fixed size.
    pub size_mult: Option<f64>,
    /// Whether an entry may be placed on the bar.
    pub wake: bool,
}

/// A specification or a signal frame the template refuses.
#[derive(Debug, Clone, PartialEq, Eq, Error)]
pub enum TemplateError {
    /// A value outside the bounds of the specification's schema.
    #[error(transparent)]
    OutOfBounds(#[from] OutOfBounds),
    /// A rule beyond the basic subset.
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

/// Where the template's stop or target goes: ticks from the entry's fill, or the row's column.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum LegRule {
    Ticks(u32),
    Column,
}

/// A specification's basic subset as a strategy over its signal rows, each a decision. At each
/// signal close, in this order: nothing while a market order is on its way out of the position,
/// the exit it placed or a stop triggered on TBBO (F-STP-02); `long_exit` while
/// long or `short_exit` while short closes the position, with signal exits on; with a position
/// or working orders, nothing more, an opposite signal being ignored; on a bar whose `wake` is
/// false, no entry; and otherwise an entry signal enters at the market, its bracket placed when
/// it fills (F-OCO-02).
#[derive(Debug, Clone, PartialEq)]
pub struct TemplateStrategy {
    rows: Vec<SignalRow>,
    signal_exit: bool,
    lots: Qty,
    stop: LegRule,
    target: LegRule,
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
        let stop = stop_rule(execution)?;
        let target = target_rule(execution, stop)?;
        require_rows_in_order(&rows)?;
        Ok(Self {
            rows,
            signal_exit: execution.signal_exit,
            lots: fixed_lots(&execution.sizing, instrument)?,
            stop,
            target,
            tick: instrument.tick_size(),
        })
    }

    fn signals_exit(&self, row: &SignalRow, position: Position) -> bool {
        self.signal_exit
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

    /// The entry's stop and target: in ticks from its fill, or at the row's prices, the stop on
    /// the losing side of the target.
    fn bracket(&self, row: &SignalRow, side: Side) -> Result<Bracket, DecisionError> {
        let stop = self.leg_price(self.stop, row.stop_price, "stop_price", row.ts_close)?;
        let target = self.leg_price(self.target, row.target_price, "target_price", row.ts_close)?;
        if let (LegPrice::At(stop), LegPrice::At(target)) = (stop, target) {
            let on_the_losing_side = match side {
                Side::Buy => stop < target,
                Side::Sell => stop > target,
            };
            if !on_the_losing_side {
                let below = if side == Side::Buy { "below" } else { "above" };
                return Err(DecisionError::Signal {
                    expected: format!("the stop_price {below} the target_price of a {side} entry"),
                    actual: format!("{stop} and {target}"),
                    at: row.ts_close,
                });
            }
        }
        Ok(Bracket {
            stop: BracketLeg {
                id: None,
                price: stop,
            },
            target: BracketLeg {
                id: None,
                price: target,
            },
        })
    }

    fn leg_price(
        &self,
        rule: LegRule,
        column: Option<Price>,
        name: &str,
        at: Ts,
    ) -> Result<LegPrice, DecisionError> {
        let price = match (rule, column) {
            (LegRule::Ticks(ticks), _) => return Ok(LegPrice::TicksFromFill(ticks)),
            (LegRule::Column, Some(price)) => price,
            (LegRule::Column, None) => {
                return Err(DecisionError::Signal {
                    expected: format!("the signal frame's {name} on the entry's bar"),
                    actual: "null".to_owned(),
                    at,
                });
            }
        };
        if price.0.rem_euclid(self.tick.0) != 0 {
            return Err(DecisionError::Signal {
                expected: format!("{name} on the instrument's tick of {}", self.tick),
                actual: price.to_string(),
                at,
            });
        }
        Ok(LegPrice::At(price))
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
        let found = self.rows.binary_search_by_key(&now, |row| row.ts_close);
        let Some(row) = found.ok().and_then(|index| self.rows.get(index)).copied() else {
            return Err(DecisionError::Signal {
                expected: "a signal row at the decision".to_owned(),
                actual: "none".to_owned(),
                at: now,
            });
        };
        if context.is_exiting() {
            return Ok(());
        }
        if self.signals_exit(&row, context.position()) {
            return context.flatten();
        }
        if context.position() != Position::Flat || context.has_working_orders() || !row.wake {
            return Ok(());
        }
        let side = match (row.long_entry, row.short_entry) {
            (true, _) => Side::Buy,
            (false, true) => Side::Sell,
            (false, false) => return Ok(()),
        };
        let bracket = self.bracket(&row, side)?;
        context.market(side, self.lots_at(&row)?, Some(bracket))?;
        Ok(())
    }
}

/// Refuses what the basic subset leaves out (`template.basic_subset_refusals`), time rules
/// included.
fn refuse_the_rest(execution: &Execution) -> Result<(), TemplateError> {
    let refusals = [
        (
            !matches!(execution.entry, EntryOrder::Market {}),
            "an entry other than market",
        ),
        (
            execution.on_opposite_signal != OppositeSignal::Ignore,
            "an opposite signal that is not ignored",
        ),
        (execution.targets.len() != 1, "other than one target"),
        (execution.breakeven.is_some(), "breakeven"),
        (execution.trailing.is_some(), "a trailing stop"),
        (
            execution.time.as_ref().is_some_and(uses_time_rules),
            "time rules",
        ),
        (execution.limits != Limits::default(), "entry limits"),
    ];
    match refusals.iter().find(|(refused, _)| *refused) {
        Some((_, what)) => Err(beyond(what)),
        None => Ok(()),
    }
}

fn uses_time_rules(time: &TimeRules) -> bool {
    time.flat_by.is_some()
        || !time.windows.is_empty()
        || time.max_bars.is_some()
        || time.max_minutes.is_some()
        || time.no_overnight
        || time.no_weekend
}

fn stop_rule(execution: &Execution) -> Result<LegRule, TemplateError> {
    match execution.stop {
        Some(StopRule::Ticks { ticks }) => Ok(LegRule::Ticks(ticks)),
        Some(StopRule::Column {}) => Ok(LegRule::Column),
        Some(_) => Err(beyond("a stop other than ticks or the stop_price column")),
        None => Err(beyond("no stop")),
    }
}

/// The target's distance from the fill in ticks, its own or its R multiple of a stop in ticks,
/// or the `target_price` column.
fn target_rule(execution: &Execution, stop: LegRule) -> Result<LegRule, TemplateError> {
    let Some(target) = execution.targets.first() else {
        return Err(beyond("no target"));
    };
    if target.fraction != 1.0 {
        return Err(beyond("a target closing part of the position"));
    }
    match (&target.price, stop) {
        (TargetPrice::Ticks { ticks }, _) => Ok(LegRule::Ticks(*ticks)),
        (TargetPrice::Column {}, _) => Ok(LegRule::Column),
        (TargetPrice::RMultiple { multiple }, LegRule::Ticks(stop_ticks)) => {
            r_multiple_ticks(*multiple, stop_ticks).map(LegRule::Ticks)
        }
        (TargetPrice::RMultiple { .. }, LegRule::Column) => {
            Err(beyond("an R multiple without a stop in ticks"))
        }
        (TargetPrice::Atr { .. }, _) => Err(beyond("a target at a multiple of a feature")),
    }
}

fn r_multiple_ticks(multiple: f64, stop_ticks: u32) -> Result<u32, TemplateError> {
    let ticks = ExactDecimal::of(multiple)
        .and_then(|exact| exact.whole_times(i64::from(stop_ticks), 1))
        .and_then(|ticks| u32::try_from(ticks).ok());
    ticks.ok_or_else(|| {
        beyond(&format!(
            "an R multiple of {multiple} times {stop_ticks} ticks, off the tick"
        ))
    })
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

fn require_rows_in_order(rows: &[SignalRow]) -> Result<(), TemplateError> {
    let later = rows.iter().skip(1);
    if let Some((earlier, row)) = rows
        .iter()
        .zip(later)
        .find(|(earlier, row)| row.ts_close <= earlier.ts_close)
    {
        return Err(TemplateError::Refused {
            expected: format!(
                "signal rows in ascending order of their closes after {}",
                earlier.ts_close
            ),
            actual: row.ts_close.to_string(),
        });
    }
    match rows.iter().find(|row| row.long_entry && row.short_entry) {
        Some(row) => Err(TemplateError::Refused {
            expected: "one of long_entry and short_entry per bar with a market entry".to_owned(),
            actual: format!("both on the signal close of {}", row.ts_close),
        }),
        None => Ok(()),
    }
}

fn beyond(what: &str) -> TemplateError {
    TemplateError::BeyondTheSubset {
        refused: what.to_owned(),
    }
}
