//! The signal rows the template decides on (D-53), one per signal close, and what it requires of
//! them before a run: rows in ascending order of their closes, one entry signal per row under a
//! market entry, and the instant of the flat-by time on every row exactly when the specification
//! has one.

use fefat_core::instants::{TradeDate, Ts};
use fefat_core::strategy_spec::Execution;
use fefat_core::units::Price;

use super::TemplateError;

/// One row of a signal frame, at one signal close (D-53): its four signals, a null read as false;
/// the raw prices of the columns the exit plan reads (`stop_price`, `target_price`,
/// `trail_ref`); the features its rules name; the size's multiple, where the frame has one;
/// whether the bar may enter, a null read as true; and what the time rules of the specification
/// read on it, as `fefat.reference.time_rules` works them out from the session table: the
/// instant of its trade date's flat-by time, whether it lies before a stop of trading or a
/// weekend, and whether it lies in an entry window (§26).
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct SignalRow {
    /// The signal bar's close, the decision's instant.
    pub ts_close: Ts,
    /// The trade date of the signal bar, on which the limits count (F-LIM-02).
    pub trade_date: Option<TradeDate>,
    /// Enter long.
    pub long_entry: bool,
    /// Enter short.
    pub short_entry: bool,
    /// Close a long.
    pub long_exit: bool,
    /// Close a short.
    pub short_exit: bool,
    /// The price of an entry at the column, a raw price of the row's contract.
    pub entry_price: Option<Price>,
    /// The stop of a column stop, a raw price of the row's contract.
    pub stop_price: Option<Price>,
    /// The target of a column target, a raw price of the row's contract.
    pub target_price: Option<Price>,
    /// The level of a trailing stop by the column, a raw price of the row's contract.
    pub trail_ref: Option<Price>,
    /// The features the exit plan's rules name, on this row.
    pub features: RowFeatures,
    /// The multiple of the fixed size.
    pub size_mult: Option<f64>,
    /// Whether an entry may be placed on the bar.
    pub wake: bool,
    /// The instant of the flat-by time on the row's trade date: from it the position is closed
    /// and no entry placed (F-TIM-01).
    pub flat_by: Option<Ts>,
    /// Whether the row lies from the last signal close before a stop of trading until trading
    /// resumes (F-TIM-03).
    pub session_end: Option<bool>,
    /// Whether it lies so before a stop over a weekend (F-TIM-03).
    pub week_end: Option<bool>,
    /// Whether an entry may be placed at its close, inside an entry window (F-TIM-04).
    pub in_window: Option<bool>,
    /// The blackout column the limits name: true keeps the row from entering, false and null do
    /// not (F-LIM-01).
    pub blackout: Option<bool>,
}

impl SignalRow {
    /// A row closing at `ts_close` with no signal, price, feature, or size multiple, on which an
    /// entry may be placed, with no flat-by time.
    pub const fn at(ts_close: Ts) -> Self {
        Self {
            ts_close,
            trade_date: None,
            long_entry: false,
            short_entry: false,
            long_exit: false,
            short_exit: false,
            entry_price: None,
            stop_price: None,
            target_price: None,
            trail_ref: None,
            features: RowFeatures::NONE,
            size_mult: None,
            wake: true,
            flat_by: None,
            session_end: None,
            week_end: None,
            in_window: None,
            blackout: None,
        }
    }
}

/// The features an exit plan's rules read on a row, each from the column its rule names: the
/// stop's, each target's in order, and the trailing stop's (F-RND-01, F-TRL-02).
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct RowFeatures {
    /// The feature of a stop at a multiple of one.
    pub stop: Option<f64>,
    /// The feature of each target at a multiple of one, in order.
    pub targets: [Option<f64>; 3],
    /// The feature of a trailing stop at a multiple of one.
    pub trailing: Option<f64>,
}

impl RowFeatures {
    /// No feature on the row.
    pub const NONE: Self = Self {
        stop: None,
        targets: [None; 3],
        trailing: None,
    };
}

/// Refuses rows out of the order of their closes, and a row with both entry signals under a
/// `market` entry.
pub(super) fn require_rows_in_order(rows: &[SignalRow], market: bool) -> Result<(), TemplateError> {
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
    match rows
        .iter()
        .find(|row| market && row.long_entry && row.short_entry)
    {
        Some(row) => Err(TemplateError::Refused {
            expected: "one of long_entry and short_entry per bar with a market entry".to_owned(),
            actual: format!("both on the signal close of {}", row.ts_close),
        }),
        None => Ok(()),
    }
}

/// Refuses a signal row without the instant of its flat-by time when the specification has one,
/// and a row with one when it has none: the instants come from the session table, which the
/// reference's `flat_by_instants` reads.
pub(super) fn require_flat_by_on_every_row(
    execution: &Execution,
    rows: &[SignalRow],
) -> Result<(), TemplateError> {
    let flat_by = execution
        .time
        .as_ref()
        .and_then(|time| time.flat_by.as_ref());
    let Some(row) = rows
        .iter()
        .find(|row| row.flat_by.is_some() != flat_by.is_some())
    else {
        return Ok(());
    };
    let expected = flat_by.map_or_else(
        || "no flat-by instant on the rows of a specification without flat_by".to_owned(),
        |time| format!("the instant of the flat-by time {time} on every signal row"),
    );
    let actual = match row.flat_by {
        Some(at) => format!("{at} on the signal close of {}", row.ts_close),
        None => format!("none on the signal close of {}", row.ts_close),
    };
    Err(TemplateError::Refused { expected, actual })
}

/// Refuses a signal row without its trade date when the limits count by trade date (F-LIM-02).
pub(super) fn require_trade_dates(
    execution: &Execution,
    rows: &[SignalRow],
) -> Result<(), TemplateError> {
    let limits = &execution.limits;
    let daily = limits.max_trades_per_day.is_some()
        || limits.max_losses_per_day.is_some()
        || limits.daily_loss_stop.is_some()
        || limits.profit_lock.is_some();
    match rows.iter().find(|row| daily && row.trade_date.is_none()) {
        Some(row) => Err(TemplateError::Refused {
            expected: "the trade_date of every signal row for the daily limits".to_owned(),
            actual: format!("none on the signal close of {}", row.ts_close),
        }),
        None => Ok(()),
    }
}

/// A column a time rule reads: its name, whether the specification has the rule, and its value on
/// a row.
type TimeColumn = (&'static str, bool, fn(&SignalRow) -> Option<bool>);

/// Refuses a signal row without a column a time rule of the specification reads: `session_end`
/// for no overnight, `week_end` for no weekend, and `in_window` for entry windows.
pub(super) fn require_time_columns(
    execution: &Execution,
    rows: &[SignalRow],
) -> Result<(), TemplateError> {
    let Some(time) = execution.time.as_ref() else {
        return Ok(());
    };
    let columns: [TimeColumn; 3] = [
        ("session_end", time.no_overnight, |row| row.session_end),
        ("week_end", time.no_weekend, |row| row.week_end),
        ("in_window", !time.windows.is_empty(), |row| row.in_window),
    ];
    for (column, read, value) in columns {
        if let Some(row) = rows.iter().find(|row| read && value(row).is_none()) {
            return Err(TemplateError::Refused {
                expected: format!("the {column} of every signal row for its time rule"),
                actual: format!("none on the signal close of {}", row.ts_close),
            });
        }
    }
    Ok(())
}
