//! The sizes of the execution template's entries, as `fefat.reference.template.sizing` works them
//! out (`docs/spec/fill-semantics.md` §28): a fixed size in whole lot steps times `size_mult`
//! (F-SIZ-01), the lots a notional amount buys at the entry's price (F-SIZ-02), the lots that lose
//! a risk amount at the stop (F-SIZ-03), and a computed size times `size_mult` rounded down, or no
//! entry with the reason the log gives (F-SIZ-04). Money counts micro-units, exactly until the
//! size is rounded.

use fefat_core::instrument::InstrumentParameters;
use fefat_core::orders::Side;
use fefat_core::strategy_spec::Sizing;
use fefat_core::units::{Money, Overflow, PRICE_UNITS, Price, Qty};

use super::SignalRow;
use super::TemplateError;
use super::limits::micro_units;
use crate::exact_decimal::ExactDecimal;
use crate::exit_plan::{ExitPlan, stop_level};
use crate::strategy::DecisionError;

/// A specification's size, its numbers read exactly once: a fixed number of lots, or one the
/// template works out at each entry.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(super) enum Size {
    Fixed(Qty),
    Computed(ComputedSize),
}

/// A size the template works out at each entry: a notional or a risk amount in micro-units, or a
/// risk as a percentage of equity.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(super) enum ComputedSize {
    Notional(Money),
    RiskAmount(Money),
    RiskPercent(ExactDecimal),
}

impl Size {
    /// The size `sizing` gives, its fixed units in whole lot steps of `instrument` (`lots_of`).
    pub(super) fn of(
        sizing: &Sizing,
        instrument: &InstrumentParameters,
    ) -> Result<Self, TemplateError> {
        let computed = match *sizing {
            Sizing::Fixed { units } => return fixed_lots(units, instrument).map(Self::Fixed),
            Sizing::Notional { amount } => {
                ComputedSize::Notional(micro_units(amount, "sizing.amount")?)
            }
            Sizing::RiskAmount { amount } => {
                ComputedSize::RiskAmount(micro_units(amount, "sizing.amount")?)
            }
            Sizing::RiskPercent { percent } => {
                let exact = ExactDecimal::of(percent).ok_or_else(|| TemplateError::Refused {
                    expected: "a sizing.percent that reads as a decimal".to_owned(),
                    actual: percent.to_string(),
                })?;
                ComputedSize::RiskPercent(exact)
            }
        };
        Ok(Self::Computed(computed))
    }
}

/// Why an entry's size places no entry, and the rule that says so.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(super) struct NoEntry {
    pub(super) why: &'static str,
    pub(super) rule: &'static str,
}

const NO_MARK: NoEntry = NoEntry {
    why: "no mark to price the entry's size",
    rule: "F-SIZ-04",
};
const NO_LOTS: NoEntry = NoEntry {
    why: "the size rounds to no lots",
    rule: "F-SIZ-04",
};
const STOP_NOT_BELOW: NoEntry = NoEntry {
    why: "the stop_price is not below the entry's price",
    rule: "F-SIZ-03",
};

/// What an entry's size reads: its side, its price, a limit's or a stop's or for a market entry
/// the mark at the decision (none before the first), its exit plan, and the equity at the
/// decision.
pub(super) struct EntryPricing<'plan> {
    pub(super) side: Side,
    pub(super) price: Option<Price>,
    pub(super) plan: &'plan ExitPlan,
    pub(super) equity: Money,
}

/// F-SIZ-01: a fixed size of `lots` times the row's `size_mult`, which must make whole lots, at
/// least one, or the run is refused.
pub(super) fn f_siz_01(lots: Qty, row: &SignalRow) -> Result<Qty, DecisionError> {
    let Some(multiple) = row.size_mult else {
        return Ok(lots);
    };
    let multiplied = ExactDecimal::of(multiple).and_then(|exact| exact.whole_times(lots.0, 1));
    match multiplied.and_then(|lots| i64::try_from(lots).ok()) {
        Some(lots) if lots >= 1 => Ok(Qty(lots)),
        _ => Err(DecisionError::Signal {
            expected: "a size_mult that makes whole lots, at least one".to_owned(),
            actual: format!("{multiple} times {lots} lots"),
            at: row.ts_close,
        }),
    }
}

/// F-SIZ-02: the whole lots whose value at `price` is at most `amount`, rounded down.
pub(super) fn f_siz_02(
    amount: Money,
    price: Price,
    instrument: &InstrumentParameters,
) -> Result<i64, Overflow> {
    if price.0 <= 0 {
        return Ok(0);
    }
    lots_within(amount, price, instrument)
}

/// F-SIZ-03: the whole lots that lose at most `amount` from `price` to `stop`, rounded down.
pub(super) fn f_siz_03(
    amount: Money,
    price: Price,
    stop: Price,
    instrument: &InstrumentParameters,
) -> Result<i64, Overflow> {
    let distance = price.checked_sub(stop)?;
    let distance = distance.0.checked_abs().map(Price).ok_or(Overflow {
        operation: "the distance from an entry's price to its stop",
        left: price.0.into(),
        right: stop.0.into(),
    })?;
    lots_within(amount, distance, instrument)
}

/// F-SIZ-04: a computed size times the row's `size_mult`, rounded down to whole lots.
pub(super) fn f_siz_04(lots: i64, row: &SignalRow) -> Result<i64, Overflow> {
    let Some(multiple) = row.size_mult else {
        return Ok(lots);
    };
    let multiplied = ExactDecimal::of(multiple).and_then(|exact| exact.floor_times(lots.into(), 1));
    let multiplied = multiplied.and_then(|lots| i64::try_from(lots).ok());
    multiplied.ok_or(Overflow {
        operation: "a size times its size_mult",
        left: lots.into(),
        right: 1,
    })
}

/// The lots of a notional or risk size (F-SIZ-02 to F-SIZ-04), or why there are none.
pub(super) fn computed_lots(
    size: ComputedSize,
    pricing: &EntryPricing<'_>,
    row: &SignalRow,
    instrument: &InstrumentParameters,
) -> Result<Result<Qty, NoEntry>, DecisionError> {
    let Some(price) = pricing.price else {
        return Ok(Err(NO_MARK));
    };
    let amount = match size {
        ComputedSize::Notional(amount) => {
            let lots = f_siz_04(f_siz_02(amount, price, instrument)?, row)?;
            return Ok(whole(lots));
        }
        ComputedSize::RiskAmount(amount) => amount,
        ComputedSize::RiskPercent(percent) => percent_of(percent, pricing.equity)?,
    };
    let Some(stop) = stop_for(pricing, price, row, instrument.tick_size())? else {
        return Ok(Err(STOP_NOT_BELOW));
    };
    let lots = f_siz_04(f_siz_03(amount, price, stop, instrument)?, row)?;
    Ok(whole(lots))
}

fn whole(lots: i64) -> Result<Qty, NoEntry> {
    if lots < 1 {
        return Err(NO_LOTS);
    }
    Ok(Qty(lots))
}

/// `percent` % of `equity`, rounded down to the micro-unit.
fn percent_of(percent: ExactDecimal, equity: Money) -> Result<Money, Overflow> {
    let amount = percent.floor_times(equity.0.into(), 100);
    let amount = amount.and_then(|amount| i64::try_from(amount).ok());
    amount.map(Money).ok_or(Overflow {
        operation: "a percentage of equity",
        left: equity.0.into(),
        right: 100,
    })
}

/// The stop as F-PLN-01 would place it for a fill at `price`: none when it is not on the losing
/// side of `price`.
fn stop_for(
    pricing: &EntryPricing<'_>,
    price: Price,
    row: &SignalRow,
    tick: Price,
) -> Result<Option<Price>, DecisionError> {
    let Some(planned) = pricing.plan.stop else {
        return Err(DecisionError::Signal {
            expected: "a stop beside a risk size (F-RND-02)".to_owned(),
            actual: "none".to_owned(),
            at: row.ts_close,
        });
    };
    let stop = stop_level(planned.at, pricing.side, price, tick)?;
    let losing = match pricing.side {
        Side::Buy => stop < price,
        Side::Sell => stop > price,
    };
    Ok(losing.then_some(stop))
}

/// The whole lots of `instrument` worth at most `amount` at `price`, above zero, rounded down.
fn lots_within(
    amount: Money,
    price: Price,
    instrument: &InstrumentParameters,
) -> Result<i64, Overflow> {
    let overflow = Overflow {
        operation: "the lots an amount buys",
        left: amount.0.into(),
        right: price.0.into(),
    };
    let one_lot = i128::from(price.0).checked_mul(instrument.money_per_point().0.into());
    let lots = i128::from(amount.0)
        .checked_mul(PRICE_UNITS.into())
        .zip(one_lot.filter(|value| *value > 0))
        .and_then(|(amount, value)| amount.checked_div_euclid(value));
    lots.and_then(|lots| i64::try_from(lots).ok())
        .ok_or(overflow)
}

/// The lots of the fixed size: its units in whole lot steps of the instrument (`lots_of`).
fn fixed_lots(units: f64, instrument: &InstrumentParameters) -> Result<Qty, TemplateError> {
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
