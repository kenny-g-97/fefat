//! The entry limits of the execution template, as `fefat.reference.template.limits` applies them
//! (`docs/spec/fill-semantics.md` §27): the blackout column (F-LIM-01), the counts of each trade
//! date (F-LIM-02), the cooldown after a losing trade (F-LIM-03), and fresh signals (F-LIM-04).
//! Amounts of money count micro-units, a specification's amount rounded down to the micro-unit
//! (F-RND-01).

use fefat_core::instants::{TradeDate, Ts};
use fefat_core::strategy_spec::{Cooldown, Limits};
use fefat_core::units::{MONEY_UNITS, Money, Overflow};

use super::{SignalRow, TemplateError};
use crate::exact_decimal::ExactDecimal;
use crate::strategy::ClosedTrade;

/// An amount of a specification, as the decimal it prints as, in whole micro-units rounded down
/// (F-RND-01).
pub(super) fn micro_units(amount: f64, field: &str) -> Result<Money, TemplateError> {
    let units = ExactDecimal::of(amount).and_then(|exact| exact.floor_times(MONEY_UNITS.into(), 1));
    let units = units.and_then(|units| i64::try_from(units).ok());
    units.map(Money).ok_or_else(|| TemplateError::Refused {
        expected: format!("{field} in micro-units within 64 bits"),
        actual: amount.to_string(),
    })
}

/// What the template counts on one trade date (F-LIM-02): the entries it placed, a pair counting
/// one, and the trades closed: how many lost, and their profit and loss.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct DayCounts {
    trade_date: Option<TradeDate>,
    entries: u32,
    losses: u32,
    pnl: Money,
}

impl DayCounts {
    const fn of(trade_date: Option<TradeDate>) -> Self {
        Self {
            trade_date,
            entries: 0,
            losses: 0,
            pnl: Money(0),
        }
    }
}

/// A template's entry limits and what they have counted: the day's counts, the trades closed so
/// far that a decision has counted, and the cooldown, the last decision it covers by its index
/// and the instant before which it covers decisions (F-LIM-03).
#[derive(Debug, Clone, PartialEq)]
pub(super) struct EntryLimits {
    limits: Limits,
    daily_loss_stop: Option<Money>,
    profit_lock: Option<Money>,
    day: DayCounts,
    counted: usize,
    cooled_through: Option<usize>,
    cooled_until: Option<Ts>,
}

impl EntryLimits {
    /// The limits of a specification, their amounts in micro-units.
    pub(super) fn new(limits: &Limits) -> Result<Self, TemplateError> {
        let amount = |amount: Option<f64>, field| amount.map(|amount| micro_units(amount, field));
        Ok(Self {
            limits: limits.clone(),
            daily_loss_stop: amount(limits.daily_loss_stop, "daily_loss_stop").transpose()?,
            profit_lock: amount(limits.profit_lock, "profit_lock").transpose()?,
            day: DayCounts::of(None),
            counted: 0,
            cooled_through: None,
            cooled_until: None,
        })
    }

    /// How many of the run's closed trades a decision has counted.
    pub(super) const fn counted(&self) -> usize {
        self.counted
    }

    /// The decision of index `decision`, on `trade_date`, counts the trades closed since the
    /// last decision, `trades` (F-LIM-02), and starts a cooldown after each losing one.
    pub(super) fn count(
        &mut self,
        trades: &[ClosedTrade],
        trade_date: Option<TradeDate>,
        decision: usize,
    ) -> Result<(), Overflow> {
        if self.day.trade_date != trade_date {
            self.day = DayCounts::of(trade_date);
        }
        for trade in trades {
            self.day.pnl = self.day.pnl.checked_add(trade.pnl)?;
            if trade.pnl.0 < 0 {
                self.day.losses = self.day.losses.saturating_add(1);
                self.cool_down(trade, decision)?;
            }
        }
        self.counted += trades.len();
        Ok(())
    }

    /// Whether `row`, the decision of index `decision`, may place an entry.
    pub(super) fn allow(&self, row: &SignalRow, decision: usize) -> bool {
        !(f_lim_01(row) || self.f_lim_02() || self.f_lim_03(row.ts_close, decision))
    }

    /// An entry placed, or a pair (F-LIM-02).
    pub(super) const fn entered(&mut self) {
        self.day.entries = self.day.entries.saturating_add(1);
    }

    fn cool_down(&mut self, trade: &ClosedTrade, decision: usize) -> Result<(), Overflow> {
        match self.limits.cooldown_after_loss {
            Some(Cooldown::Bars { bars }) => {
                let through = decision.saturating_add(bars as usize).saturating_sub(1);
                self.cooled_through = self.cooled_through.max(Some(through));
            }
            Some(Cooldown::Minutes { minutes }) => {
                let span = i64::from(minutes) * 60_000_000_000;
                let until = trade.closed_at.checked_add_nanoseconds(span)?;
                self.cooled_until = self.cooled_until.max(Some(until));
            }
            None => {}
        }
        Ok(())
    }

    /// F-LIM-02: whether the day's counts keep the template from entering: its entries at
    /// `max_trades_per_day`, its losing trades at `max_losses_per_day`, or its closed trades'
    /// profit and loss at or below minus `daily_loss_stop` or at or above `profit_lock`.
    fn f_lim_02(&self) -> bool {
        let day = &self.day;
        let limits = &self.limits;
        let reached = [
            limits
                .max_trades_per_day
                .is_some_and(|most| day.entries >= most),
            limits
                .max_losses_per_day
                .is_some_and(|most| day.losses >= most),
            self.daily_loss_stop
                .is_some_and(|stop| day.pnl.0 <= stop.0.saturating_neg()),
            self.profit_lock.is_some_and(|lock| day.pnl >= lock),
        ];
        reached.contains(&true)
    }

    /// F-LIM-03: whether a cooldown after a losing trade covers the decision of index `decision`
    /// at `now`: the `bars` decisions from the one that counted the loss on, or those before its
    /// closing fill plus `minutes`.
    fn f_lim_03(&self, now: Ts, decision: usize) -> bool {
        let by_bars = self
            .cooled_through
            .is_some_and(|through| decision <= through);
        by_bars || self.cooled_until.is_some_and(|until| now < until)
    }
}

/// F-LIM-01: whether the row's blackout column keeps it from entering: true does, false and null
/// do not.
const fn f_lim_01(row: &SignalRow) -> bool {
    matches!(row.blackout, Some(true))
}

/// F-LIM-04: `row` with its entry signals as they count: with `fresh_signal`, only where they were
/// false on the row `before`, the first row's counting; without it, as they are.
pub(super) const fn f_lim_04(fresh: bool, row: SignalRow, before: Option<&SignalRow>) -> SignalRow {
    let Some(before) = before else {
        return row;
    };
    if !fresh {
        return row;
    }
    SignalRow {
        long_entry: row.long_entry && !before.long_entry,
        short_entry: row.short_entry && !before.short_entry,
        ..row
    }
}
