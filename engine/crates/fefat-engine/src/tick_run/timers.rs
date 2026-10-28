//! A run's session events and timers (F-CLK-02): a future's rolls at their sessions' opens (§29),
//! which `rolls` works, and a perpetual's funding times, when an open position pays or receives
//! at the mark (F-FND-01); and the fee table, funding rates, and rolls a run is given.

use fefat_core::costs::{CostLine, CostReason, FundingRate};
use fefat_core::instants::Ts;
use fefat_core::ledger::Position;
use fefat_core::market_data::MarketDataReader;
use fefat_core::rolls::Roll;
use fefat_core::units::Money;

use super::{RunError, Stepped, TickRun};
use crate::event_log::LogEntry;
use crate::settings::{RollHandling, RunCosts};

/// A session event or a timer (F-CLK-02): a roll at its session's open, or a funding time.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(super) enum Timer {
    Roll(Ts),
    Funding(FundingRate),
}

impl Timer {
    pub(super) const fn at(self) -> Ts {
        match self {
            Self::Roll(at) => at,
            Self::Funding(rate) => rate.ts,
        }
    }
}

impl<R: MarketDataReader> TickRun<'_, R> {
    /// The run paying `costs`: its fee table, and a perpetual's funding rates, in ascending order
    /// of their times.
    pub fn with_costs(mut self, costs: RunCosts) -> Result<Self, RunError> {
        let times: Vec<Ts> = costs.funding.iter().map(|rate| rate.ts).collect();
        in_order("funding times", &times)?;
        self.costs = costs;
        Ok(self)
    }

    /// The run across `rolls`, the roll calendar's for its trade dates, in ascending order of
    /// their opens, each rolling from the front the one before it left, the first from the
    /// reader's contract (F-ROL-01), doing with an open position what `handling` says.
    pub fn with_rolls(
        mut self,
        rolls: Vec<Roll>,
        handling: RollHandling,
    ) -> Result<Self, RunError> {
        let opens: Vec<Ts> = rolls.iter().map(|roll| roll.session_open).collect();
        in_order("rolls", &opens)?;
        let mut front = &self.front;
        for roll in &rolls {
            if roll.rolled_from != *front || roll.contract == *front {
                return Err(RunError::RollFromAnotherFront {
                    at: roll.session_open,
                    front: front.clone(),
                    rolled_from: roll.rolled_from.clone(),
                    contract: roll.contract.clone(),
                });
            }
            front = &roll.contract;
        }
        self.rolls = rolls;
        self.roll_handling = handling;
        Ok(self)
    }

    /// The next roll or funding time, a roll first at one instant.
    pub(super) fn next_timer(&self) -> Option<Timer> {
        let roll = self.rolls.get(self.next_roll);
        let roll = roll.map(|roll| Timer::Roll(roll.session_open));
        let funding = self.costs.funding.get(self.next_funding).copied();
        match (roll, funding.map(Timer::Funding)) {
            (Some(roll), Some(funding)) if funding.at() < roll.at() => Some(funding),
            (Some(roll), _) => Some(roll),
            (None, funding) => funding,
        }
    }

    pub(super) fn on_timer(&mut self, timer: Timer, index: usize) -> Result<Stepped, RunError> {
        match timer {
            Timer::Roll(at) => self.roll(at, index)?,
            Timer::Funding(rate) => self.pay_funding(rate)?,
        }
        Ok(Stepped::Timer(timer.at()))
    }

    /// F-FND-01: a funding time; an open position pays or receives at the mark, which counts in
    /// the trade open (§20) and is a cost line.
    fn pay_funding(&mut self, rate: FundingRate) -> Result<(), RunError> {
        self.next_funding += 1;
        if self.ledger.position() == Position::Flat {
            return Ok(());
        }
        let Some(mark) = self.ledger.mark() else {
            return Err(RunError::FundingWithoutMark { at: rate.ts });
        };
        let change = self.ledger.pay_funding(rate.rate)?;
        self.trade_cash = self.trade_cash.checked_add(change)?;
        self.cost_lines.push(CostLine {
            ts: rate.ts,
            amount: Money(0).checked_sub(change)?,
            reason: CostReason::Funding { rate: rate.rate },
        });
        self.log.push(LogEntry::funding(rate.ts, change, mark));
        Ok(())
    }
}

/// Refuses `instants` out of ascending order, or one twice.
fn in_order(what: &'static str, instants: &[Ts]) -> Result<(), RunError> {
    let pairs = instants.iter().zip(instants.iter().skip(1));
    match pairs.into_iter().find(|(previous, next)| next <= previous) {
        Some((&previous, &next)) => Err(RunError::TimersOutOfOrder {
            what,
            previous,
            next,
        }),
        None => Ok(()),
    }
}
